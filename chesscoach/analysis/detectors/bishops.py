"""bishop_pair / bad_bishop (02 §6.2).

bishop_pair: side has bishops on both colours, opponent does not. side = owner.
bad_bishop: >= 2 of the owner's c/d/e/f pawns stand on the bishop's colour and are fixed
(blocked by an enemy pawn directly in front). side = owner.
"""
from __future__ import annotations

import chess

from chesscoach.analysis.board_utils import cname, sq
from chesscoach.analysis.detectors.base import DetectorContext
from chesscoach.types import Feature

FEATURE_IDS = ("bishop_pair", "bad_bishop")
NEEDS_ENGINE = False
MOVE_BASED = False


def _has_pair(board: chess.Board, color: chess.Color) -> bool:
    bs = board.pieces(chess.BISHOP, color)
    return bool(bs & chess.BB_LIGHT_SQUARES) and bool(bs & chess.BB_DARK_SQUARES)


def detect(board: chess.Board, ctx: DetectorContext) -> list[Feature]:
    out = []
    for color in (chess.WHITE, chess.BLACK):
        if _has_pair(board, color) and not _has_pair(board, not color):
            out.append(Feature(id="bishop_pair", side=cname(color),
                               squares=[sq(s) for s in board.pieces(chess.BISHOP, color)]))
        fwd = 8 if color == chess.WHITE else -8
        for bsq in board.pieces(chess.BISHOP, color):
            colour_mask = chess.BB_LIGHT_SQUARES if chess.BB_SQUARES[bsq] & chess.BB_LIGHT_SQUARES else chess.BB_DARK_SQUARES
            fixed = []
            for p in board.pieces(chess.PAWN, color):
                if chess.square_file(p) not in (2, 3, 4, 5) or not chess.BB_SQUARES[p] & colour_mask:
                    continue
                front = p + fwd
                if 0 <= front < 64 and board.piece_at(front) == chess.Piece(chess.PAWN, not color):
                    fixed.append(p)
            if len(fixed) >= 2:
                out.append(Feature(id="bad_bishop", side=cname(color), squares=[sq(bsq)] + [sq(p) for p in fixed],
                                   pieces=[sq(bsq)], data={"fixed_pawns": [sq(p) for p in fixed]}))
    return out
