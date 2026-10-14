"""removing_defender (02 §6.1), engine-confirmed.

v1 covers the capturing form: move m captures enemy piece D, which was the sole defender of
an enemy piece T that we attack and that was safe before (SEE <= 0); the engine's line then
captures on T with one of our next two moves (within 4 plies; engine lines often insert a
quiet move first) and the sequence (m included, plus the reply to that capture) wins >= 1 pawn.
Deflection by a non-capturing move is not detected yet.
"""
from __future__ import annotations

import chess

from chesscoach.analysis.board_utils import PIECE_NAME, balance, cname, see_target, sq
from chesscoach.analysis.detectors.base import DetectorContext
from chesscoach.types import Feature

FEATURE_IDS = ("removing_defender",)
NEEDS_ENGINE = True
MOVE_BASED = True


def detect(board: chess.Board, ctx: DetectorContext) -> list[Feature]:
    m, before = ctx.move, ctx.board_before
    if m is None or before is None or not before.is_capture(m) or before.is_en_passant(m):
        return []
    us, them = before.turn, not before.turn
    d = m.to_square
    out = []
    for t in before.attacks(d):
        pt = before.piece_at(t)
        if pt is None or pt.color != them or pt.piece_type == chess.KING:
            continue
        if not before.is_attacked_by(us, t) or list(before.attackers(them, t)) != [d]:
            continue
        safe = see_target(before, t, us)
        if safe is not None and safe > 0:
            continue
        # Engine line: we capture on t within 4 plies; count material through the reply.
        b = board.copy(stack=False)
        captured_at = None
        for i, mv in enumerate(ctx.pv[:5]):
            if not b.is_legal(mv) or (captured_at is not None and i > captured_at + 1):
                break
            if captured_at is None and i < 4 and b.turn == us and mv.to_square == t and b.is_capture(mv):
                captured_at = i
            b.push(mv)
        if captured_at is not None and balance(b, us) - balance(before, us) >= 1:
            out.append(Feature(
                id="removing_defender", side=cname(us), squares=[sq(d), sq(t)], pieces=[sq(d)],
                data={"defender": sq(d), "defender_piece": PIECE_NAME[before.piece_type_at(d)],
                      "target": sq(t), "target_piece": PIECE_NAME[pt.piece_type]}))
    return out
