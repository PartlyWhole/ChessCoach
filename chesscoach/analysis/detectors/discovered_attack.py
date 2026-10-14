"""discovered_attack / discovered_check (02 §6.1): move m uncovers a line from one of our
sliders to an enemy target — the king (also emits discovered_check) or a piece we would win
(SEE > 0)."""
from __future__ import annotations

import chess

from chesscoach.analysis.board_utils import PIECE_NAME, cname, see_target, sq
from chesscoach.analysis.detectors.base import DetectorContext
from chesscoach.types import Feature

FEATURE_IDS = ("discovered_attack", "discovered_check")
NEEDS_ENGINE = False
MOVE_BASED = True


def detect(board: chess.Board, ctx: DetectorContext) -> list[Feature]:
    m, before = ctx.move, ctx.board_before
    if m is None or before is None:
        return []
    us = before.turn
    out = []
    for s in board.pieces(chess.BISHOP, us) | board.pieces(chess.ROOK, us) | board.pieces(chess.QUEEN, us):
        if s == m.to_square:
            continue
        for t in board.attacks(s) & ~before.attacks(s):
            if not chess.BB_SQUARES[m.from_square] & chess.between(s, t):
                continue
            pt = board.piece_at(t)
            if pt is None or pt.color == us:
                continue
            is_king = pt.piece_type == chess.KING
            if not is_king:
                v = see_target(board, t, us)
                if v is None or v <= 0:
                    continue
            data = {"slider": sq(s), "slider_piece": PIECE_NAME[board.piece_type_at(s)],
                    "moved": sq(m.to_square), "moved_piece": PIECE_NAME[board.piece_type_at(m.to_square)],
                    "target": sq(t), "target_piece": PIECE_NAME[pt.piece_type]}
            f = dict(side=cname(us), squares=[sq(s), sq(t), sq(m.to_square)], pieces=[sq(s), sq(m.to_square)])
            out.append(Feature(id="discovered_attack", data=data, **f))
            if is_king:
                out.append(Feature(id="discovered_check", data=dict(data), **f))
    return out
