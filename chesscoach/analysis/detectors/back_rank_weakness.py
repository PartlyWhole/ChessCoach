"""back_rank_weakness (02 §6.1): king on its back rank, every escape square on its 2nd rank
is occupied by its own pieces or attacked, and an enemy rook/queen can reach the back rank
in one rook-move. side = the enemy (who can exploit it); data.owner = the weak side."""
from __future__ import annotations

import chess

from chesscoach.analysis.board_utils import cname, sq
from chesscoach.analysis.detectors.base import DetectorContext
from chesscoach.types import Feature

FEATURE_IDS = ("back_rank_weakness",)
NEEDS_ENGINE = False
MOVE_BASED = False


def detect(board: chess.Board, ctx: DetectorContext) -> list[Feature]:
    out = []
    for color in (chess.WHITE, chess.BLACK):
        k = board.king(color)
        if k is None:
            continue
        back = 0 if color == chess.WHITE else 7
        second = 1 if color == chess.WHITE else 6
        if chess.square_rank(k) != back:
            continue
        escapes = chess.SquareSet(board.attacks(k) & chess.BB_RANKS[second])
        if any(not board.color_at(e) == color and not board.is_attacked_by(not color, e) for e in escapes):
            continue
        entry = []
        for rq in board.pieces(chess.ROOK, not color) | board.pieces(chess.QUEEN, not color):
            straight = chess.BB_FILES[chess.square_file(rq)] | chess.BB_RANKS[chess.square_rank(rq)]
            entry += list(chess.SquareSet(board.attacks(rq) & chess.BB_RANKS[back] & straight))
            if entry:
                out.append(Feature(id="back_rank_weakness", side=cname(not color),
                                   squares=[sq(k)] + sorted({sq(e) for e in entry}),
                                   pieces=[sq(rq)], data={"owner": cname(color), "king": sq(k)}))
                break
    return out
