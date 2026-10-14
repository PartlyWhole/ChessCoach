"""lesson_score per concept category (docs/05 §3), built on L1/L2 so every steer is checkable."""
from __future__ import annotations

from typing import Optional

import chess

from chesscoach.analysis.analyzer import Analyzer
from chesscoach.analysis.structure import STRUCTURES, _score, encode
from chesscoach.concepts.matcher import match, views_for_position
from chesscoach.concepts.registry import Registry


def structure_similarity(board: chess.Board, structure_id: str) -> float:
    """0..1: best share of the target template's cells matched, for either owner."""
    cells = STRUCTURES.get(structure_id)
    if cells is None:
        return 0.0
    w, b = encode(board, chess.WHITE), encode(board, chess.BLACK)
    return max(_score(cells, {"O": w, "T": b}), _score(cells, {"O": b, "T": w}))


class LessonScorer:
    def __init__(self, analyzer: Analyzer, registry: Registry, band: str):
        self.analyzer, self.registry, self.band = analyzer, registry, band

    def __call__(self, board: chess.Board, move: chess.Move, concept_id: str, category: str) -> float:
        after = board.copy(stack=False)
        after.push(move)
        concept = self.registry.concepts.get(concept_id)
        if concept is None:
            return 0.0
        if category == "tactic":
            # The player gets an `available` hit for the concept worth >= 0.10 win prob.
            eng = self.analyzer.engine(after)
            hits = match(self.registry, views_for_position(after, eng, self.analyzer.features(after, eng)),
                         self.band)
            return 1.0 if any(h.concept_id == concept_id and h.role == "available" for h in hits) else 0.0
        if category == "defence":
            # The bot's move creates a threat the player can parry with exactly one good move.
            eng = self.analyzer.engine(after)
            pf = self.analyzer.features(after, eng)
            bot = "white" if board.turn == chess.WHITE else "black"
            return 1.0 if any(t.by == bot for t in pf.threats) and eng.sharpness >= 0.8 else 0.0
        if category == "structure":
            target = (concept.trigger.get("structure") or [None])[0]
            if target is None:
                return 0.0
            # Improvement toward the target, not raw similarity: otherwise almost every move
            # would score > 0 and the bot would "steer" constantly (see 05).
            return max(0.0, structure_similarity(after, target) - structure_similarity(board, target))
        if category == "endgame":
            # A trade that keeps the target material signature reachable.
            return 1.0 if board.is_capture(move) and _signature_reachable(after, concept.trigger.get("predicate")) else 0.0
        return 0.0


_TARGETS = {"kq_vs_k": {chess.QUEEN}, "kr_vs_k": {chess.ROOK}}


def _signature_reachable(board: chess.Board, predicate: Optional[str]) -> bool:
    need = _TARGETS.get(predicate or "")
    if need is None:
        return False
    return any(board.pieces(pt, c) for pt in need for c in (chess.WHITE, chess.BLACK))
