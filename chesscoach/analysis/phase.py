"""Game phase (docs/02 §5)."""
from __future__ import annotations

import chess

from chesscoach.analysis.board_utils import non_pawn_material
from chesscoach.types import Phase

_MINOR_MAJOR = (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)


def _pieces(board: chess.Board, color: chess.Color) -> int:
    return sum(len(board.pieces(pt, color)) for pt in _MINOR_MAJOR)


def game_phase(board: chess.Board, in_book: bool = False) -> Phase:
    no_queens = not board.pieces(chess.QUEEN, chess.WHITE) and not board.pieces(chess.QUEEN, chess.BLACK)
    if non_pawn_material(board) <= 13 or (
            no_queens and _pieces(board, chess.WHITE) <= 2 and _pieces(board, chess.BLACK) <= 2):
        return "endgame"
    if in_book or (board.fullmove_number <= 12
                   and _pieces(board, chess.WHITE) + _pieces(board, chess.BLACK) >= 10):
        return "opening"
    return "middlegame"
