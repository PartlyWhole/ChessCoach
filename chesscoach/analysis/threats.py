"""Null-move threat detection (02 §6.4): what would the side NOT to move do if it could move
again right now? Threats are always by the side not to move."""
from __future__ import annotations

from typing import Callable, Optional

import chess

from chesscoach import config
from chesscoach.analysis.board_utils import cname, is_hanging, material
from chesscoach.analysis.winprob import line_wp
from chesscoach.types import EngineResult, Feature, Phase, ThreatInfo

MIN_GAIN = 0.10


def skip_threats(board: chess.Board, phase: Phase) -> bool:
    """Null move is illegal in check and misleading in low-material endgames (zugzwang)."""
    if board.is_check() or board.is_game_over():
        return True
    total = material(board, chess.WHITE) + material(board, chess.BLACK)
    return phase == "endgame" and total <= 6


def _aggressive(b: chess.Board, mv: chess.Move, ids: list[str]) -> bool:
    """A threat must do something *to* the side to move. The win-prob gain alone also rewards
    the opponent rescuing its own hanging piece or defending against our mate (both raise its
    win prob vs the real position), which are not threats. Keep: captures, checks, moves that
    realise a tactic, and moves that leave one of our pieces newly en prise (adds "attack")."""
    if b.is_capture(mv) or b.gives_check(mv) or ids:
        return True
    victim = not b.turn
    after = b.copy(stack=False)
    after.push(mv)
    for sq, p in after.piece_map().items():
        if p.color == victim and p.piece_type != chess.KING and is_hanging(after, sq) and not is_hanging(b, sq):
            ids.append("attack")
            return True
    return False


def find_threats(board: chess.Board, engine_result: EngineResult, analyse: Callable[..., EngineResult],
                 phase: Phase, tactical: Callable[[chess.Board, chess.Move, list[chess.Move]], list[str]]
                 ) -> tuple[list[ThreatInfo], list[Feature]]:
    """`analyse(board, depth=, multipv=)`; `tactical(board_after_null, threat_move, pv)` returns the
    tactical feature ids the threat move realises."""
    if skip_threats(board, phase):
        return [], []
    opponent = cname(not board.turn)
    base = line_wp(engine_result.lines[0], opponent)
    b = board.copy(stack=False)
    b.push(chess.Move.null())
    # Fresh board from FEN: UCI cannot transmit a move history containing a null move.
    res = analyse(chess.Board(b.fen()), depth=int(config.get("engine.depth_threat")), multipv=2)
    threats, feats = [], []
    for line in res.lines:
        if not line.moves:
            continue
        gain = line_wp(line, opponent) - base
        if gain < MIN_GAIN:
            continue
        mv = chess.Move.from_uci(line.moves[0])
        ids = tactical(b, mv, [chess.Move.from_uci(m) for m in line.moves[1:]])
        is_mate = line.mate is not None and (line.mate > 0) == (opponent == "white")
        if not is_mate and not _aggressive(b, mv, ids):
            continue
        if is_mate and "mate_threat" not in ids:
            ids.append("mate_threat")
        threats.append(ThreatInfo(by=opponent, move=line.moves[0], gain_win_prob=gain, feature_ids=ids))
        if is_mate and not any(f.id == "mate_threat" for f in feats):
            feats.append(Feature(id="mate_threat", side=opponent,
                                 squares=[chess.square_name(mv.from_square), chess.square_name(mv.to_square)],
                                 data={"move": line.moves[0], "mate_in": abs(line.mate)}))
    return threats, feats
