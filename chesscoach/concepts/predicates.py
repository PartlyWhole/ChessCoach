"""Named predicates for concepts the trigger language cannot express (docs/03 "Trigger language").

A predicate gets a PredicateInput and returns None (no match) or a PredicateResult with the
feature-like evidence and extra slot values. Every predicate is a pure function of the board,
engine output and L1 features — so every claim stays verifiable (AGENTS rule 1). Each one
has its own tests in tests/test_predicates.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import chess

from chesscoach.analysis.board_utils import ccolor, material, sq
from chesscoach.analysis.winprob import line_wp
from chesscoach.types import Color, EngineResult, Feature, PositionFeatures, ThreatInfo


@dataclass
class PredicateInput:
    board: chess.Board                 # the position the role is matched on
    features: PositionFeatures
    engine: Optional[EngineResult]
    user: Color                        # side the concept's idea is for
    move: Optional[chess.Move] = None  # played move (missed/allowed/played roles)
    board_before: Optional[chess.Board] = None


@dataclass
class PredicateResult:
    feature: Feature
    slots: dict[str, str] = field(default_factory=dict)


Predicate = Callable[[PredicateInput], Optional[PredicateResult]]
PREDICATES: dict[str, Predicate] = {}
PREDICATE_SLOTS: dict[str, set[str]] = {}   # slot names each predicate fills (checked at build)


def predicate(name: str, slots: tuple[str, ...] = ()):
    def deco(fn: Predicate) -> Predicate:
        PREDICATES[name] = fn
        PREDICATE_SLOTS[name] = set(slots)
        return fn
    return deco


@predicate("opponent_threat", slots=('threat_square', 'threat_from'))
def opponent_threat(inp: PredicateInput) -> Optional[PredicateResult]:
    """User to move; the null-move search found a threat by the other side gaining >= 0.10."""
    if inp.board.turn != ccolor(inp.user):
        return None
    threats: list[ThreatInfo] = [t for t in inp.features.threats if t.by != inp.user]
    if not threats:
        return None
    t = max(threats, key=lambda x: x.gain_win_prob)
    mv = chess.Move.from_uci(t.move)
    return PredicateResult(
        Feature(id="threat", side=t.by, squares=[sq(mv.from_square), sq(mv.to_square)],
                data={"move": t.move, "gain": t.gain_win_prob, "feature_ids": t.feature_ids}),
        slots={"threat_square": sq(mv.to_square), "threat_from": sq(mv.from_square)})


@predicate("moved_piece_hanging", slots=('square', 'piece'))
def moved_piece_hanging(inp: PredicateInput) -> Optional[PredicateResult]:
    """After the user's opponent's move (allowed role): the piece that was just moved is hanging."""
    if inp.move is None:
        return None
    for f in inp.features.features:
        if f.id == "hanging_piece" and f.side == inp.user and sq(inp.move.to_square) in f.squares:
            return PredicateResult(f, slots={"square": sq(inp.move.to_square), "piece": f.data["piece"]})
    return None


@predicate("sharp_position")
def sharp_position(inp: PredicateInput) -> Optional[PredicateResult]:
    """User to move and only one move holds or wins (sharpness >= 0.8, 02 §4)."""
    if inp.engine is None or inp.board.turn != ccolor(inp.user) or inp.engine.sharpness < 0.8:
        return None
    return PredicateResult(Feature(id="sharp", side=inp.user, squares=[], data={"sharpness": inp.engine.sharpness}))


@predicate("can_castle_now", slots=('king_square',))
def can_castle_now(inp: PredicateInput) -> Optional[PredicateResult]:
    """Opening, move >= 7, user to move, has not castled and castling is legal right now."""
    b = inp.board
    if b.turn != ccolor(inp.user) or b.fullmove_number < 7 or inp.features.phase != "opening":
        return None
    castles = [m for m in b.legal_moves if b.is_castling(m)]
    if not castles:
        return None
    k = b.king(b.turn)
    return PredicateResult(Feature(id="can_castle", side=inp.user, squares=[sq(k)],
                                   data={"moves": [m.uci() for m in castles]}),
                           slots={"king_square": sq(k)})


def _material_signature(board: chess.Board, color: chess.Color) -> str:
    order = [(chess.QUEEN, "Q"), (chess.ROOK, "R"), (chess.BISHOP, "B"), (chess.KNIGHT, "N"), (chess.PAWN, "P")]
    return "K" + "".join(ch * len(board.pieces(pt, color)) for pt, ch in order)


def _signature_predicate(user_sig: str, other_sig: str) -> Predicate:
    def fn(inp: PredicateInput) -> Optional[PredicateResult]:
        u = ccolor(inp.user)
        if _material_signature(inp.board, u) != user_sig or _material_signature(inp.board, not u) != other_sig:
            return None
        k = inp.board.king(not u)
        return PredicateResult(Feature(id="material_signature", side=inp.user, squares=[sq(k)],
                                       data={"user": user_sig, "other": other_sig}),
                               slots={"enemy_king": sq(k)})
    return fn


predicate("kq_vs_k", slots=("enemy_king",))(_signature_predicate("KQ", "K"))
predicate("kr_vs_k", slots=("enemy_king",))(_signature_predicate("KR", "K"))


@predicate("king_inside_square", slots=('pawn_square', 'queening_square'))
def king_inside_square(inp: PredicateInput) -> Optional[PredicateResult]:
    """Pawn endgame (kings and pawns only), user to move, the other side has a passed pawn and
    the user's king is inside that pawn's square, i.e. can reach the queening square in time.
    Uses the classic rule with the defending king on move: inside iff
    distance(king, queening square) <= distance(pawn, queening square), the pawn's distance
    reduced by one from its starting rank (double step). Kings one step outside that are on
    move are not counted (the template says "inside", so the claim stays exact)."""
    b = inp.board
    u = ccolor(inp.user)
    if b.turn != u or material(b, chess.WHITE) - len(b.pieces(chess.PAWN, chess.WHITE)) \
            or material(b, chess.BLACK) - len(b.pieces(chess.PAWN, chess.BLACK)):
        return None
    k = b.king(u)
    best = None
    for f in inp.features.features:
        if f.id != "passed_pawn" or f.side == inp.user:
            continue
        p = chess.parse_square(f.squares[0])
        file = chess.square_file(p)
        promo = chess.square(file, 0 if u == chess.WHITE else 7)   # the other side queens on our back rank
        start_rank = 6 if u == chess.WHITE else 1
        pawn_dist = abs(chess.square_rank(promo) - chess.square_rank(p))
        if chess.square_rank(p) == start_rank:
            pawn_dist -= 1
        king_dist = chess.square_distance(k, promo)
        inside = king_dist <= pawn_dist
        cand = (pawn_dist, f.squares[0], inside, promo)
        if best is None or cand[0] < best[0]:
            best = cand
    if best is None or not best[2]:
        return None
    _, pawn_sq, inside, promo = best
    return PredicateResult(Feature(id="pawn_square", side=inp.user, squares=[pawn_sq, sq(promo)],
                                   data={"inside": inside, "pawn": pawn_sq}),
                           slots={"pawn_square": pawn_sq, "queening_square": sq(promo)})


@predicate("rook_behind_passer", slots=('rook_square', 'pawn_square'))
def rook_behind_passer(inp: PredicateInput) -> Optional[PredicateResult]:
    """Endgame: user has a rook on the same file as a passed pawn (either colour), behind it
    relative to that pawn's direction, with no pieces in between."""
    if inp.features.phase != "endgame":
        return None
    b = inp.board
    u = ccolor(inp.user)
    for f in inp.features.features:
        if f.id != "passed_pawn":
            continue
        p = chess.parse_square(f.squares[0])
        pawn_color = ccolor(f.side)
        fwd = 1 if pawn_color == chess.WHITE else -1
        for r in b.pieces(chess.ROOK, u):
            if chess.square_file(r) != chess.square_file(p):
                continue
            if inp.move is not None and r != inp.move.to_square:
                continue   # played role: the rook must be the piece just moved
            behind = (chess.square_rank(r) - chess.square_rank(p)) * fwd < 0
            if behind and not chess.between(r, p) & b.occupied:
                return PredicateResult(Feature(id="rook_behind_passer", side=inp.user, squares=[sq(r), sq(p)],
                                               pieces=[sq(r)], data={"own_pawn": pawn_color == u}),
                                       slots={"rook_square": sq(r), "pawn_square": sq(p)})
    return None


@predicate("back_rank_mate", slots=('king_square', 'mate_in'))
def back_rank_mate(inp: PredicateInput) -> Optional[PredicateResult]:
    """The other side has back_rank_weakness for the user (side == user) and the engine's best
    line for the user mates (only meaningful on the position where the user is to move)."""
    if inp.engine is None or not inp.engine.lines or inp.board.turn != ccolor(inp.user):
        return None
    line = inp.engine.lines[0]
    if not line.mate or (line.mate > 0) != (inp.user == "white") or abs(line.mate) > 3:
        return None                                   # mate 0 = already mated: nothing to find
    for f in inp.features.features:
        if f.id == "back_rank_weakness" and f.side == inp.user and "via" not in f.data:
            return PredicateResult(f, slots={"king_square": f.data["king"], "mate_in": str(abs(line.mate))})
    return None
