"""Layer 1 entry point: analyze(fen_before, move) (docs/02 §7).

PositionFeatures for a position P contain, for both sides:
- static features of P (data has no "created_by"/"via");
- features the move that produced P created (move-based detectors; data.created_by = that move);
- opportunities for the side to move: move-based detectors applied to P after the engine's
  best move, confirmed with the rest of the engine line (data.via = the best move);
- mate_threat features and ThreatInfo from the null-move search (always by the side not to move).
"""
from __future__ import annotations

import logging
from collections import Counter
from types import ModuleType
from typing import Optional

import chess

from chesscoach import config
from chesscoach.analysis import classify as classify_mod
from chesscoach.analysis.board_utils import is_hanging, material
from chesscoach.analysis.book import OpeningBook
from chesscoach.analysis.detectors import (back_rank_weakness, bishops, development, discovered_attack,
                                           double_check, files, fork, hanging_piece, king_safety,
                                           overloaded_defender, pawns, pins, removing_defender, skewer,
                                           space, squares, trapped_piece)
from chesscoach.analysis.detectors.base import DetectorContext
from chesscoach.analysis.engine import EnginePool
from chesscoach.analysis.phase import game_phase
from chesscoach.analysis.structure import classify_structure
from chesscoach.analysis.tablebase import Tablebase
from chesscoach.analysis.threats import find_threats
from chesscoach.types import EngineResult, Feature, MoveAssessment, PositionFeatures

log = logging.getLogger(__name__)
detector_errors: Counter = Counter()   # metric: detector name -> exceptions

DETECTORS: list[ModuleType] = [
    hanging_piece, fork, pins, skewer, discovered_attack, double_check, back_rank_weakness,
    overloaded_defender, trapped_piece, removing_defender,
    pawns, squares, files, bishops, king_safety, development, space,
]
STATIC = [d for d in DETECTORS if not d.MOVE_BASED]
MOVE_BASED = [d for d in DETECTORS if d.MOVE_BASED]
TACTICAL_IDS = {"hanging_piece", "fork", "double_attack", "pin_absolute", "pin_relative", "skewer",
                "discovered_attack", "discovered_check", "double_check", "back_rank_weakness",
                "mate_threat", "overloaded_defender", "trapped_piece", "removing_defender"}


def _run(det: ModuleType, board: chess.Board, ctx: DetectorContext) -> list[Feature]:
    """A detector that throws must not fail the analysis: log, drop, count (02 §7)."""
    try:
        return det.detect(board, ctx)
    except Exception:  # noqa: BLE001
        log.exception("detector %s failed on %s", det.__name__, board.fen())
        detector_errors[det.__name__] += 1
        return []


def static_features(board: chess.Board, phase, engine: Optional[EngineResult] = None) -> list[Feature]:
    ctx = DetectorContext(engine=engine, phase=phase)
    return [f for d in STATIC for f in _run(d, board, ctx)]


def move_features(board_before: chess.Board, move: chess.Move, pv: list[chess.Move],
                  engine_after: Optional[EngineResult] = None, phase="middlegame",
                  tag: str = "created_by") -> list[Feature]:
    """Move-based features created by `move` (pv: engine continuation after it), marked
    data[tag] = move (tag "created_by" for the move just played, "via" for opportunities)."""
    after = board_before.copy(stack=False)
    after.push(move)
    ctx = DetectorContext(engine=engine_after, move=move, board_before=board_before, pv=pv, phase=phase)
    feats = [f for d in MOVE_BASED for f in _run(d, after, ctx)]
    for f in feats:
        f.data[tag] = move.uci()
    return feats


STATIC_TACTICAL_VIA = {"pin_absolute", "pin_relative", "skewer", "trapped_piece", "double_check",
                       "overloaded_defender"}


def static_opportunities(board: chess.Board, move: chess.Move, existing: list[Feature], phase) -> list[Feature]:
    """Static tactical features (pins, skewers, ...) for the mover that `move` creates and that
    involve the moved piece's destination; marked data.via = move."""
    mover = "white" if board.turn == chess.WHITE else "black"
    after = board.copy(stack=False)
    after.push(move)
    to = chess.square_name(move.to_square)
    present = {(f.id, tuple(f.squares)) for f in existing if "via" not in f.data and "created_by" not in f.data}
    out = []
    for f in static_features(after, phase):
        if f.id in STATIC_TACTICAL_VIA and f.side == mover and (f.id, tuple(f.squares)) not in present \
                and (f.id == "trapped_piece" or to in f.squares or to in (f.pieces or [])):
            f.data["via"] = move.uci()
            out.append(f)
    return out


def tactical_ids_for_move(board: chess.Board, move: chess.Move, pv: list[chess.Move]) -> list[str]:
    ids = {f.id for f in move_features(board, move, pv) if f.id in TACTICAL_IDS}
    if board.is_capture(move) and not board.is_en_passant(move) and is_hanging(board, move.to_square):
        ids.add("hanging_piece")
    return sorted(ids)


def _moves(ucis: list[str]) -> list[chess.Move]:
    return [chess.Move.from_uci(u) for u in ucis]


class Analyzer:
    def __init__(self, pool: Optional[EnginePool] = None, tablebase: Optional[Tablebase] = None,
                 book: Optional[OpeningBook] = None, threats: bool = True, live: bool = False):
        """live=True caps each search by engine.time_live / engine.time_threat (01 latency budget);
        live=False (review, tests) searches to full depth."""
        self.live = live
        self.pool = pool or EnginePool()
        self.tablebase = tablebase
        self.book = book
        self.threats_enabled = threats

    # ---- engine ----
    def engine(self, board: chess.Board, depth: Optional[int] = None, multipv: Optional[int] = None) -> EngineResult:
        if self.tablebase is not None:
            tb = self.tablebase.probe(board)
            if tb is not None:
                return tb
        t = float(config.get("engine.time_live")) if self.live else None
        return self.pool.analyse(board, depth=depth, multipv=multipv, time=t)

    # ---- features ----
    def features(self, board: chess.Board, result: EngineResult, last_move: Optional[chess.Move] = None,
                 board_before: Optional[chess.Board] = None) -> PositionFeatures:
        in_book = self.book is not None and self.book.has_position(board)
        phase = game_phase(board, in_book=in_book)
        feats = static_features(board, phase, result)
        best = result.lines[0] if result.lines else None

        if last_move is not None and board_before is not None:
            pv = _moves(best.moves) if best else []
            feats += move_features(board_before, last_move, pv, result, phase)

        if best and best.moves and not result.tablebase:
            bm = chess.Move.from_uci(best.moves[0])
            feats += move_features(board, bm, _moves(best.moves[1:]), None, phase, tag="via")
            feats += static_opportunities(board, bm, feats, phase)

        threats = []
        if self.threats_enabled and result.lines:
            threats, threat_feats = find_threats(board, result, self.engine_for_threats, phase, tactical_ids_for_move)
            feats += threat_feats

        structure_id, owner = classify_structure(board)
        if structure_id is not None:
            feats.append(Feature(id="structure", side=owner or "white", squares=[],
                                 data={"structure_id": structure_id, "owner": owner}))
        return PositionFeatures(
            fen=board.fen(), phase=phase,
            material={"white": material(board, chess.WHITE), "black": material(board, chess.BLACK)},
            features=feats, threats=threats, structure_id=structure_id)

    def engine_for_threats(self, board: chess.Board, depth: int, multipv: int) -> EngineResult:
        t = float(config.get("engine.time_threat")) if self.live else None
        return self.pool.analyse(board, depth=depth, multipv=multipv, time=t)

    # ---- 02 §7 output contract ----
    def analyze(self, fen_before: str, move: str | chess.Move, before: Optional[EngineResult] = None,
                depth: Optional[int] = None
                ) -> tuple[EngineResult, EngineResult, MoveAssessment, PositionFeatures, PositionFeatures]:
        """`before` lets the caller reuse the previous move's "after" analysis (01 pipeline step 1)."""
        board = chess.Board(fen_before)
        mv = chess.Move.from_uci(move) if isinstance(move, str) else move
        if not board.is_legal(mv):
            raise ValueError(f"illegal move {mv.uci()} in {fen_before}")
        before = before or self.engine(board, depth=depth)
        after_board = board.copy()
        after_board.push(mv)
        after = self.engine(after_board, depth=depth)
        book = self.book.has_move if self.book is not None else None
        assessment = classify_mod.classify(board, mv, before, after, book=book)
        pf_before = self.features(board, before)
        pf_after = self.features(after_board, after, last_move=mv, board_before=board)
        return before, after, assessment, pf_before, pf_after

    def close(self) -> None:
        self.pool.close()
        if self.tablebase is not None:
            self.tablebase.close()
