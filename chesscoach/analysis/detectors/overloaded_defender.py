"""overloaded_defender (02 §6.1): an enemy piece is the sole defender of >= 2 of its pieces
that we attack, each currently safe (SEE <= 0 for us) but lost without that defender
(SEE > 0 with the defender removed)."""
from __future__ import annotations

import chess

from chesscoach.analysis.board_utils import PIECE_NAME, cname, see_target, sq
from chesscoach.analysis.detectors.base import DetectorContext
from chesscoach.types import Feature

FEATURE_IDS = ("overloaded_defender",)
NEEDS_ENGINE = False
MOVE_BASED = False


def detect(board: chess.Board, ctx: DetectorContext) -> list[Feature]:
    out = []
    for us in (chess.WHITE, chess.BLACK):
        them = not us
        duties: dict[int, list[int]] = {}
        for t, pt in board.piece_map().items():
            if pt.color != them or pt.piece_type == chess.KING or not board.is_attacked_by(us, t):
                continue
            defenders = list(board.attackers(them, t))
            if len(defenders) != 1:
                continue
            now = see_target(board, t, us)
            if now is not None and now > 0:
                continue  # already hanging, not an overload
            b = board.copy(stack=False)
            b.remove_piece_at(defenders[0])
            without = see_target(b, t, us)
            if without is not None and without > 0:
                duties.setdefault(defenders[0], []).append(t)
        for d, targets in duties.items():
            if len(targets) >= 2:
                out.append(Feature(
                    id="overloaded_defender", side=cname(us), squares=[sq(d)] + [sq(t) for t in targets],
                    pieces=[sq(d)],
                    data={"defender": sq(d), "defender_piece": PIECE_NAME[board.piece_type_at(d)],
                          "targets": [sq(t) for t in targets]}))
    return out
