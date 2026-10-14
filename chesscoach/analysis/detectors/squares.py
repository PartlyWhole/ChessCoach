"""Square detectors (02 §6.2): outpost, weak_square.

outpost: square on ranks 4–6 (from our side) that no enemy pawn can ever attack (no enemy
pawn on an adjacent file ahead of it) and that one of our pawns defends. side = us (it
favours us). data.occupant names our piece on it, if any.

weak_square: square on ranks 3–4 of our camp, not holding our pawn, that none of our pawns
can ever defend again (no own pawn on an adjacent file behind it) and that an enemy knight,
bishop, rook or queen attacks now. side = owner of the weakness. Ranks 1–2 are excluded:
pawns can never defend rank 1 and only rarely matter for rank 2, so including them makes
the feature fire in almost every position.
"""
from __future__ import annotations

import chess

from chesscoach.analysis.board_utils import PIECE_NAME, cname, sq
from chesscoach.analysis.detectors.base import DetectorContext
from chesscoach.types import Feature

FEATURE_IDS = ("outpost", "weak_square")
NEEDS_ENGINE = False
MOVE_BASED = False


def _rel_rank(color: chess.Color, square: chess.Square) -> int:
    """1..8 from `color`'s side."""
    r = chess.square_rank(square)
    return r + 1 if color == chess.WHITE else 8 - r


def can_ever_be_attacked_by_pawn(board: chess.Board, square: chess.Square, pawn_color: chess.Color) -> bool:
    """Is there a `pawn_color` pawn on an adjacent file that has not yet passed `square`?"""
    f = chess.square_file(square)
    target = _rel_rank(pawn_color, square)
    for p in board.pieces(chess.PAWN, pawn_color):
        if abs(chess.square_file(p) - f) == 1 and _rel_rank(pawn_color, p) < target:
            return True
    return False


def detect(board: chess.Board, ctx: DetectorContext) -> list[Feature]:
    out = []
    for color in (chess.WHITE, chess.BLACK):
        own_pawns = board.pieces(chess.PAWN, color)
        for s in chess.SQUARES:
            rr = _rel_rank(color, s)
            if 4 <= rr <= 6 and not can_ever_be_attacked_by_pawn(board, s, not color) \
                    and board.attackers(color, s) & own_pawns:
                p = board.piece_at(s)
                occ = PIECE_NAME[p.piece_type] if p and p.color == color else None
                out.append(Feature(id="outpost", side=cname(color), squares=[sq(s)],
                                   pieces=[sq(s)] if occ else None, data={"occupant": occ}))
            if 3 <= rr <= 4:
                p = board.piece_at(s)
                if p and p.color == color and p.piece_type == chess.PAWN:
                    continue
                if can_ever_be_attacked_by_pawn(board, s, color):
                    continue
                attackers = [a for a in board.attackers(not color, s)
                             if board.piece_type_at(a) in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)]
                if attackers:
                    out.append(Feature(id="weak_square", side=cname(color), squares=[sq(s)],
                                       pieces=[sq(a) for a in attackers],
                                       data={"owner": cname(color),
                                             "attackers": [PIECE_NAME[board.piece_type_at(a)] for a in attackers]}))
    return out
