"""Detector contract (docs/02 §6).

A detector is a pure function `(board, ctx) -> list[Feature]` in its own module. Each module
declares:

    FEATURE_IDS: tuple[str, ...]   ids it can emit (sub-ids included)
    NEEDS_ENGINE: bool             needs ctx.engine / ctx.pv
    MOVE_BASED: bool               describes what ctx.move created (needs ctx.move)
    detect(board, ctx) -> list[Feature]

Test positions live in tests/positions/detectors/<feature_id>.yaml (08).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import chess

from chesscoach.types import EngineResult, Phase


@dataclass
class DetectorContext:
    engine: Optional[EngineResult] = None      # analysis of `board`
    move: Optional[chess.Move] = None          # move that produced `board` (move-based detectors)
    board_before: Optional[chess.Board] = None # position before `move`
    pv: list[chess.Move] = field(default_factory=list)  # engine best continuation from `board`
    phase: Phase = "middlegame"

    @property
    def mover(self) -> Optional[chess.Color]:
        return None if self.board_before is None else self.board_before.turn
