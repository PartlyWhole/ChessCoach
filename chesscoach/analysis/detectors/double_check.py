"""double_check (02 §6.1): side to move is in check from two pieces."""
from __future__ import annotations

import chess

from chesscoach.analysis.board_utils import cname, sq
from chesscoach.analysis.detectors.base import DetectorContext
from chesscoach.types import Feature

FEATURE_IDS = ("double_check",)
NEEDS_ENGINE = False
MOVE_BASED = False


def detect(board: chess.Board, ctx: DetectorContext) -> list[Feature]:
    checkers = list(board.checkers())
    if len(checkers) < 2:
        return []
    return [Feature(id="double_check", side=cname(not board.turn),
                    squares=[sq(board.king(board.turn))] + [sq(c) for c in checkers],
                    pieces=[sq(c) for c in checkers])]
