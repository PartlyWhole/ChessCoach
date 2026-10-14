"""open_file / half_open_file (02 §6.2).

open_file: no pawns on the file. Emitted once per side; data.occupants lists that side's
rooks/queens on it (may be empty).
half_open_file: no pawns of `side` but at least one enemy pawn. side = the side that can use
it; data.occupants as above.
"""
from __future__ import annotations

import chess

from chesscoach.analysis.board_utils import cname, sq
from chesscoach.analysis.detectors.base import DetectorContext
from chesscoach.types import Feature

FEATURE_IDS = ("open_file", "half_open_file")
NEEDS_ENGINE = False
MOVE_BASED = False


def detect(board: chess.Board, ctx: DetectorContext) -> list[Feature]:
    out = []
    for f in range(8):
        mask = chess.BB_FILES[f]
        w = bool(board.pieces_mask(chess.PAWN, chess.WHITE) & mask)
        b = bool(board.pieces_mask(chess.PAWN, chess.BLACK) & mask)
        for color in (chess.WHITE, chess.BLACK):
            own, enemy = (w, b) if color == chess.WHITE else (b, w)
            if own:
                continue
            fid = "open_file" if not enemy else "half_open_file"
            heavy = (board.pieces(chess.ROOK, color) | board.pieces(chess.QUEEN, color)) & chess.SquareSet(mask)
            out.append(Feature(id=fid, side=cname(color), squares=[sq(chess.square(f, r)) for r in range(8)],
                               pieces=[sq(s) for s in heavy] or None,
                               data={"file": chess.FILE_NAMES[f], "occupants": [sq(s) for s in heavy]}))
    return out
