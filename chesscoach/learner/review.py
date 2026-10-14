"""Post-game review builder (docs/06 §4)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import chess

from chesscoach import config
from chesscoach.analysis.analyzer import Analyzer
from chesscoach.concepts.matcher import match, views_after_move
from chesscoach.concepts.registry import Registry
from chesscoach.concepts.render import render
from chesscoach.learner.accuracy import game_accuracy
from chesscoach.learner.srs import ReviewCard
from chesscoach.policy.policy import CoachingPolicy, load_fallback
from chesscoach.types import ConceptHit, MoveAssessment

MIN_GAP_PLIES = 4
MAX_MOMENTS = 3
NO_HIT_IMPORTANCE = 0.3      # moments the engine flags but no concept explains (shown with the engine line)


@dataclass
class PlyAnalysis:
    ply: int
    fen_before: str
    move: str
    assessment: MoveAssessment
    phase: str
    hits: list[ConceptHit]
    is_player: bool


@dataclass
class Moment:
    ply: int
    start_fen: str                  # one ply before the player's move (06 §4 step 3)
    lead_in: Optional[str]          # opponent move auto-played before the player must find the answer
    played: str
    best_line: list[str]
    move_class: str
    concept_id: Optional[str]
    summary: str                    # level-3 text of the top concept, or the engine fallback
    hint_hits: list[ConceptHit] = field(default_factory=list)
    unpunished: bool = False        # the opponent's previous move was a mistake the player missed


@dataclass
class GameReview:
    moments: list[Moment]
    phase_accuracy: dict[str, Optional[float]]
    plies: list[PlyAnalysis]
    cards: list[ReviewCard]


def analyse_game(moves: list[str], player: str, analyzer: Analyzer, registry: Registry, band: str,
                 start_fen: str = chess.STARTING_FEN, depth: Optional[int] = None) -> list[PlyAnalysis]:
    """Step 1: re-analyse every position at review depth; recompute assessments and hits."""
    depth = depth or int(config.get("engine.depth_review"))
    board = chess.Board(start_fen)
    out, prev_after = [], None
    for ply, uci in enumerate(moves):
        fen = board.fen()
        before, after, a, pf_b, pf_a = analyzer.analyze(fen, uci, before=prev_after, depth=depth)
        mover = "white" if board.turn == chess.WHITE else "black"
        hits = match(registry, views_after_move(board, chess.Move.from_uci(uci), a, before, pf_b, after, pf_a),
                     band, review=True)
        out.append(PlyAnalysis(ply, fen, uci, a, pf_b.phase, hits, mover == player))
        board.push_uci(uci)
        prev_after = after
    return out


def _best_hit(hits: list[ConceptHit]) -> Optional[ConceptHit]:
    cands = [h for h in hits if h.role in ("missed", "allowed")]
    return max(cands, key=lambda h: h.importance) if cands else None


def select_moments(plies: list[PlyAnalysis]) -> list[PlyAnalysis]:
    """Step 2: rank player plies by loss × importance of best hit; keep the top 3 at least 4 plies
    apart; always include the single largest swing."""
    mine = [p for p in plies if p.is_player and p.assessment.move_class in ("inaccuracy", "mistake", "blunder")]
    if not mine:
        return []

    def score(p):
        h = _best_hit(p.hits)
        return p.assessment.loss * (h.importance if h else NO_HIT_IMPORTANCE)

    largest = max(mine, key=lambda p: p.assessment.loss)
    chosen = [largest]
    for p in sorted(mine, key=score, reverse=True):
        if len(chosen) >= MAX_MOMENTS:
            break
        if all(abs(p.ply - c.ply) >= MIN_GAP_PLIES for c in chosen):
            chosen.append(p)
    return sorted(chosen, key=lambda p: p.ply)


def build_review(moves: list[str], player: str, analyzer: Analyzer, registry: Registry, band: str,
                 player_id: str = "", game_id: str = "", start_fen: str = chess.STARTING_FEN,
                 depth: Optional[int] = None, fallback: Optional[dict] = None) -> GameReview:
    plies = analyse_game(moves, player, analyzer, registry, band, start_fen, depth)
    fb = load_fallback() if fallback is None else fallback
    moments = []
    for p in select_moments(plies):
        prev = plies[p.ply - 1] if p.ply > 0 else None
        h = _best_hit(p.hits)
        summary = None
        if h is not None:
            summary = render(registry.get(h.concept_id), h, 3)
        if summary is None:
            slots = CoachingPolicy.fallback_slots(chess.Board(p.fen_before), p.assessment, None)
            tmpl = fb.get("engine", {}).get(3)
            summary = tmpl.format(**slots) if tmpl and {"best_san", "pv_san"} <= set(slots) else ""
        unpunished = prev is not None and not prev.is_player and prev.assessment.move_class in ("mistake", "blunder") \
            and any(x.role == "missed" for x in p.hits)
        moments.append(Moment(
            ply=p.ply, start_fen=prev.fen_before if prev else p.fen_before, lead_in=prev.move if prev else None,
            played=p.move, best_line=p.assessment.best_line, move_class=p.assessment.move_class,
            concept_id=h.concept_id if (h and summary and render(registry.get(h.concept_id), h, 3)) else None,
            summary=summary, hint_hits=[x for x in p.hits if x.role in ("missed", "allowed")], unpunished=unpunished))

    accuracy = {}
    for phase in ("opening", "middlegame", "endgame"):
        mine = [p for p in plies if p.is_player and p.phase == phase]
        accuracy[phase] = game_accuracy([p.assessment.win_prob_before for p in mine],
                                        [p.assessment.win_prob_after for p in mine])

    # Step 6: save mistakes/blunders automatically as cards.
    cards = []
    for m in moments:
        if m.move_class not in ("mistake", "blunder") or not m.best_line:
            continue
        concept = registry.concepts.get(m.concept_id) if m.concept_id else None
        plies_n = int((concept.drill or {}).get("max_solution_plies", 3)) if concept else 3
        n = plies_n if plies_n % 2 == 1 else plies_n + 1        # end on the player's move
        kind = "avoid_mistake" if any(h.role == "allowed" and h.concept_id == m.concept_id for h in m.hint_hits) \
            else "find_move"
        pos = plies[m.ply]
        cards.append(ReviewCard.new(player_id, kind, pos.fen_before, m.best_line[:n],
                                    [m.concept_id] if m.concept_id else [], {"game_id": game_id, "ply": m.ply}))
    return GameReview(moments, accuracy, plies, cards)
