"""undeveloped_pieces (02 §6.2): in the opening phase, after move 8, minor pieces still on
their starting squares. side = owner; data.count."""
from __future__ import annotations

import chess

from chesscoach.analysis.board_utils import PIECE_NAME, cname, sq
from chesscoach.analysis.detectors.base import DetectorContext
from chesscoach.types import Feature

FEATURE_IDS = ("undeveloped_pieces",)
NEEDS_ENGINE = False
MOVE_BASED = False

START = {chess.WHITE: {chess.B1: chess.KNIGHT, chess.G1: chess.KNIGHT, chess.C1: chess.BISHOP, chess.F1: chess.BISHOP},
         chess.BLACK: {chess.B8: chess.KNIGHT, chess.G8: chess.KNIGHT, chess.C8: chess.BISHOP, chess.F8: chess.BISHOP}}


def detect(board: chess.Board, ctx: DetectorContext) -> list[Feature]:
    if ctx.phase != "opening" or board.fullmove_number <= 8:
        return []
    out = []
    for color in (chess.WHITE, chess.BLACK):
        home = [s for s, pt in START[color].items() if board.piece_at(s) == chess.Piece(pt, color)]
        if home:
            out.append(Feature(id="undeveloped_pieces", side=cname(color), squares=[sq(s) for s in home],
                               pieces=[sq(s) for s in home],
                               data={"count": len(home), "pieces": [PIECE_NAME[board.piece_type_at(s)] for s in home]}))
    return out
