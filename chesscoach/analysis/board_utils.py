"""Shared chess helpers for detectors: piece values, colours, static exchange evaluation."""
from __future__ import annotations

from typing import Optional

import chess

from chesscoach.types import Color

# 02 §6.1: P=1, N=3, B=3, R=5, Q=9, K=∞.
VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 1000}
PIECE_NAME = {chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop",
              chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king"}
SLIDERS = (chess.BISHOP, chess.ROOK, chess.QUEEN)


def cname(color: chess.Color) -> Color:
    return "white" if color == chess.WHITE else "black"


def ccolor(color: Color) -> chess.Color:
    return chess.WHITE if color == "white" else chess.BLACK


def sq(square: chess.Square) -> str:
    return chess.square_name(square)


def material(board: chess.Board, color: chess.Color) -> int:
    return sum(VALUE[pt] * len(board.pieces(pt, color)) for pt in VALUE if pt != chess.KING)


def balance(board: chess.Board, color: chess.Color) -> int:
    return material(board, color) - material(board, not color)


def non_pawn_material(board: chess.Board, color: Optional[chess.Color] = None) -> int:
    colors = [chess.WHITE, chess.BLACK] if color is None else [color]
    return sum(VALUE[pt] * len(board.pieces(pt, c))
               for c in colors for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN))


def with_turn(board: chess.Board, color: chess.Color) -> chess.Board:
    """Copy of `board` with `color` to move (en passant cleared if the turn changes)."""
    b = board.copy(stack=False)
    if b.turn != color:
        b.turn = color
        b.ep_square = None
    return b


def join_names(names: list[str]) -> str:
    """["queen", "rook"] → "queen and rook"; three → "a, b and c"."""
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


# ---------- Static exchange evaluation ----------
# Implemented over *legal* captures on a copied board, so pins, x-rays and king
# safety are handled by the move generator rather than by special cases.

def _captured_value(board: chess.Board, move: chess.Move) -> int:
    if board.is_en_passant(move):
        return VALUE[chess.PAWN]
    p = board.piece_at(move.to_square)
    return VALUE[p.piece_type] if p else 0


def _least_valuable_capture(board: chess.Board, target: chess.Square) -> Optional[chess.Move]:
    best, best_val = None, None
    for m in board.generate_legal_captures(to_mask=chess.BB_SQUARES[target]):
        if m.promotion not in (None, chess.QUEEN):
            continue
        v = VALUE[board.piece_type_at(m.from_square)]
        if best_val is None or v < best_val:
            best, best_val = m, v
    return best


def see_move(board: chess.Board, move: chess.Move) -> int:
    """Net material gain (pawn units) for the side making `move`, assuming both sides then
    keep recapturing on the target square with their least valuable piece and may stop."""
    gain = _captured_value(board, move)
    if move.promotion:
        gain += VALUE[move.promotion] - VALUE[chess.PAWN]
    b = board.copy(stack=False)
    b.push(move)
    reply = _least_valuable_capture(b, move.to_square)
    if reply is None:
        return gain
    return gain - max(0, see_move(b, reply))


def see_target(board: chess.Board, target: chess.Square, by: chess.Color) -> Optional[int]:
    """Best SEE for `by` capturing on `target` (as if `by` were to move); None if `by` has no
    legal capture there."""
    b = with_turn(board, by)
    best = None
    for m in b.generate_legal_captures(to_mask=chess.BB_SQUARES[target]):
        if m.promotion not in (None, chess.QUEEN):
            continue
        v = see_move(b, m)
        if best is None or v > best:
            best = v
    return best


def is_hanging(board: chess.Board, square: chess.Square) -> bool:
    """02 §6.1 hanging_piece: attacked and SEE for the attacker > 0."""
    p = board.piece_at(square)
    if p is None or p.piece_type == chess.KING:
        return False
    v = see_target(board, square, not p.color)
    return v is not None and v > 0


def valuable_target(board: chess.Board, square: chess.Square, by: chess.Color) -> bool:
    """A fork/double-attack target: the enemy king, or an enemy piece with SEE > 0 for `by`."""
    p = board.piece_at(square)
    if p is None or p.color == by:
        return False
    if p.piece_type == chess.KING:
        return True
    v = see_target(board, square, by)
    return v is not None and v > 0


def pv_material_gain(board: chess.Board, pv: list[chess.Move], color: chess.Color, plies: int) -> int:
    """Change in material balance for `color` over the first `plies` moves of `pv`, extended by
    one ply if the last counted move was a capture by `color` (so a recapture is included)."""
    start = balance(board, color)
    b = board.copy(stack=False)
    n = 0
    for m in pv:
        if not b.is_legal(m):
            break
        mover = b.turn
        was_capture = b.is_capture(m)
        b.push(m)
        n += 1
        if n >= plies and not (was_capture and mover == color):
            break
        if n >= plies + 1:
            break
    return balance(b, color) - start
