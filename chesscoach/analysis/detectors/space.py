"""space_advantage (02 §6.2): squares on files c–f in the opponent's half that we attack and no
enemy pawn attacks. Reported for the side ahead when the difference is >= 4."""
from __future__ import annotations

import chess

from chesscoach.analysis.board_utils import cname
from chesscoach.analysis.detectors.base import DetectorContext
from chesscoach.types import Feature

FEATURE_IDS = ("space_advantage",)
NEEDS_ENGINE = False
MOVE_BASED = False
MIN_DIFF = 4


def count(board: chess.Board, color: chess.Color) -> int:
    ranks = range(4, 8) if color == chess.WHITE else range(0, 4)
    n = 0
    for f in (2, 3, 4, 5):
        for r in ranks:
            s = chess.square(f, r)
            if board.is_attacked_by(color, s) and not (board.attackers(not color, s) & board.pieces(chess.PAWN, not color)):
                n += 1
    return n


def detect(board: chess.Board, ctx: DetectorContext) -> list[Feature]:
    w, b = count(board, chess.WHITE), count(board, chess.BLACK)
    if abs(w - b) < MIN_DIFF:
        return []
    side = chess.WHITE if w > b else chess.BLACK
    return [Feature(id="space_advantage", side=cname(side), squares=[],
                    data={"white": w, "black": b, "diff": abs(w - b)})]
