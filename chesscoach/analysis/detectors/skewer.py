"""skewer (02 §6.1): our slider attacks an enemy piece A (king allowed) and the first piece
behind A on that line is an enemy piece B worth less than A, which we win once A moves
(SEE > 0 with A removed). Not reported when A can take the slider without losing material."""
from __future__ import annotations

import chess

from chesscoach.analysis.board_utils import PIECE_NAME, VALUE, cname, sq
from chesscoach.analysis.detectors.base import DetectorContext
from chesscoach.analysis.detectors.pins import can_take_safely, first_behind, win_behind
from chesscoach.types import Feature

FEATURE_IDS = ("skewer",)
NEEDS_ENGINE = False
MOVE_BASED = False


def detect(board: chess.Board, ctx: DetectorContext) -> list[Feature]:
    out = []
    for us in (chess.WHITE, chess.BLACK):
        for s in board.pieces(chess.BISHOP, us) | board.pieces(chess.ROOK, us) | board.pieces(chess.QUEEN, us):
            for a in board.attacks(s):
                pa = board.piece_at(a)
                if pa is None or pa.color == us:
                    continue
                b = first_behind(board, s, a)
                if b is None:
                    continue
                pb = board.piece_at(b)
                if pb.color == us or pb.piece_type == chess.KING or VALUE[pb.piece_type] >= VALUE[pa.piece_type]:
                    continue
                if can_take_safely(board, a, s) or not win_behind(board, s, a, b, us):
                    continue
                out.append(Feature(
                    id="skewer", side=cname(us), squares=[sq(a), sq(b), sq(s)], pieces=[sq(s)],
                    data={"front": sq(a), "front_piece": PIECE_NAME[pa.piece_type],
                          "behind": sq(b), "behind_piece": PIECE_NAME[pb.piece_type],
                          "attacker": sq(s), "attacker_piece": PIECE_NAME[board.piece_type_at(s)]}))
    return out
