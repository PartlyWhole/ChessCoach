"""pin_absolute / pin_relative (02 §6.1).

pin_absolute: enemy piece on a line between our slider and their king that cannot legally
leave the line (`board.is_pinned`).
pin_relative: our slider attacks enemy piece X; the first piece behind X on that line is an
enemy non-king Y worth more than X, and with X gone we would win material on Y (SEE > 0).
Not reported when X can itself take the slider without losing material.
"""
from __future__ import annotations

import chess

from chesscoach.analysis.board_utils import (PIECE_NAME, SLIDERS, VALUE, cname, see_move,
                                             see_target, sq, with_turn)
from chesscoach.analysis.detectors.base import DetectorContext
from chesscoach.types import Feature

FEATURE_IDS = ("pin_absolute", "pin_relative")
NEEDS_ENGINE = False
MOVE_BASED = False


def first_behind(board: chess.Board, slider: chess.Square, front: chess.Square):
    """First occupied square beyond `front` on the line slider→front, or None."""
    line = chess.ray(slider, front)
    df = chess.square_file(front) - chess.square_file(slider)
    dr = chess.square_rank(front) - chess.square_rank(slider)
    step_f = (df > 0) - (df < 0)
    step_r = (dr > 0) - (dr < 0)
    f, r = chess.square_file(front) + step_f, chess.square_rank(front) + step_r
    while 0 <= f < 8 and 0 <= r < 8:
        s = chess.square(f, r)
        if not line & chess.BB_SQUARES[s]:
            return None
        if board.piece_at(s):
            return s
        f, r = f + step_f, r + step_r
    return None


def can_take_safely(board: chess.Board, frm: chess.Square, to: chess.Square) -> bool:
    p = board.piece_at(frm)
    b = with_turn(board, p.color)
    m = chess.Move(frm, to)
    if p.piece_type == chess.PAWN and chess.square_rank(to) in (0, 7):
        m = chess.Move(frm, to, chess.QUEEN)
    return b.is_legal(m) and see_move(b, m) >= 0


def win_behind(board: chess.Board, slider: chess.Square, front: chess.Square, behind: chess.Square,
               us: chess.Color) -> bool:
    b = board.copy(stack=False)
    b.remove_piece_at(front)
    v = see_target(b, behind, us)
    return v is not None and v > 0


def detect(board: chess.Board, ctx: DetectorContext) -> list[Feature]:
    out = []
    for color in (chess.WHITE, chess.BLACK):
        enemy = not color
        king = board.king(color)
        for s, p in board.piece_map().items():
            if p.color != color or p.piece_type == chess.KING or not board.is_pinned(color, s):
                continue
            ray = board.pin(color, s)
            pinners = [x for x in chess.SquareSet(ray)
                       if board.piece_at(x) and board.piece_at(x).color == enemy
                       and board.piece_type_at(x) in SLIDERS and board.attacks(x) & chess.BB_SQUARES[s]]
            if not pinners:
                continue
            pinner = pinners[0]
            out.append(Feature(
                id="pin_absolute", side=cname(enemy), squares=[sq(s), sq(pinner), sq(king)],
                pieces=[sq(pinner), sq(s)],
                data={"pinned": sq(s), "pinned_piece": PIECE_NAME[p.piece_type],
                      "pinner": sq(pinner), "pinner_piece": PIECE_NAME[board.piece_type_at(pinner)],
                      "behind": sq(king), "behind_piece": "king"}))

    for us in (chess.WHITE, chess.BLACK):
        for s in board.pieces(chess.BISHOP, us) | board.pieces(chess.ROOK, us) | board.pieces(chess.QUEEN, us):
            for x in board.attacks(s):
                px = board.piece_at(x)
                if px is None or px.color == us or px.piece_type == chess.KING:
                    continue
                y = first_behind(board, s, x)
                if y is None:
                    continue
                py = board.piece_at(y)
                if py.color == us or py.piece_type == chess.KING or VALUE[py.piece_type] <= VALUE[px.piece_type]:
                    continue
                if can_take_safely(board, x, s) or not win_behind(board, s, x, y, us):
                    continue
                out.append(Feature(
                    id="pin_relative", side=cname(us), squares=[sq(x), sq(s), sq(y)], pieces=[sq(s), sq(x)],
                    data={"pinned": sq(x), "pinned_piece": PIECE_NAME[px.piece_type],
                          "pinner": sq(s), "pinner_piece": PIECE_NAME[board.piece_type_at(s)],
                          "behind": sq(y), "behind_piece": PIECE_NAME[py.piece_type]}))
    return out
