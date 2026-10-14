"""trapped_piece (02 §6.1): an enemy N/B/R/Q that we win where it stands (SEE > 0) and every
legal move of which also loses material (SEE < 0 for its owner)."""
from __future__ import annotations

import chess

from chesscoach.analysis.board_utils import PIECE_NAME, cname, see_move, see_target, sq, with_turn
from chesscoach.analysis.detectors.base import DetectorContext
from chesscoach.types import Feature

FEATURE_IDS = ("trapped_piece",)
NEEDS_ENGINE = False
MOVE_BASED = False


def detect(board: chess.Board, ctx: DetectorContext) -> list[Feature]:
    out = []
    for s, p in board.piece_map().items():
        if p.piece_type in (chess.PAWN, chess.KING):
            continue
        us = not p.color
        here = see_target(board, s, us)
        if here is None or here <= 0:
            continue
        b = with_turn(board, p.color)
        moves = [m for m in b.legal_moves if m.from_square == s]
        if all(see_move(b, m) < 0 for m in moves):
            out.append(Feature(id="trapped_piece", side=cname(us), squares=[sq(s)], pieces=[sq(s)],
                               data={"piece": PIECE_NAME[p.piece_type], "owner": cname(p.color),
                                     "escapes": len(moves)}))
    return out
