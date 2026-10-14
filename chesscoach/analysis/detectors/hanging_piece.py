"""hanging_piece — attacked and SEE for the attacker > 0 (02 §6.1)."""
from __future__ import annotations

import chess

from chesscoach.analysis.board_utils import PIECE_NAME, cname, see_target, sq
from chesscoach.analysis.detectors.base import DetectorContext
from chesscoach.types import Feature

FEATURE_IDS = ("hanging_piece",)
NEEDS_ENGINE = False
MOVE_BASED = False


def detect(board: chess.Board, ctx: DetectorContext) -> list[Feature]:
    out = []
    for square, piece in board.piece_map().items():
        if piece.piece_type == chess.KING:
            continue
        gain = see_target(board, square, not piece.color)
        if gain is not None and gain > 0:
            out.append(Feature(
                id="hanging_piece", side=cname(not piece.color), squares=[sq(square)],
                pieces=[sq(square)],
                data={"piece": PIECE_NAME[piece.piece_type], "owner": cname(piece.color), "see": gain},
            ))
    return out
