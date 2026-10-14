"""Move classification by win-probability loss (docs/02 §3)."""
from __future__ import annotations

from typing import Callable, Optional

import chess

from chesscoach.analysis.board_utils import cname
from chesscoach.analysis.winprob import line_wp
from chesscoach.types import EngineResult, MoveAssessment, MoveClass

# Starting thresholds on a 0..1 scale — tune with 08.
EXCELLENT = 0.02
GOOD = 0.05
INACCURACY = 0.10
MISTAKE = 0.15
WON_CAP = 0.95

BookLookup = Callable[[chess.Board, chess.Move], bool]


def _class_for_loss(loss: float) -> MoveClass:
    if loss < EXCELLENT:
        return "excellent"
    if loss < GOOD:
        return "good"
    if loss < INACCURACY:
        return "inaccuracy"
    if loss < MISTAKE:
        return "mistake"
    return "blunder"


_SEVERITY = ["best", "excellent", "good", "inaccuracy", "mistake", "blunder"]


def classify(board_before: chess.Board, move: chess.Move, before: EngineResult,
             after: EngineResult, book: Optional[BookLookup] = None) -> MoveAssessment:
    """`before` analyses board_before (mover to move); `after` analyses the position after `move`.

    The value after the move is taken from `before`'s MultiPV line starting with `move` when
    there is one (same search, so no depth noise between the two numbers); otherwise from
    `after`'s best line.
    """
    mover = cname(board_before.turn)
    best_line = before.lines[0]
    wp_before = line_wp(best_line, mover)
    same_search = next((l for l in before.lines if l.moves and l.moves[0] == move.uci()), None)
    after_line = same_search or after.lines[0]
    wp_after = line_wp(after_line, mover)
    loss = max(0.0, wp_before - wp_after)

    best_move = best_line.moves[0] if best_line.moves else move.uci()
    if board_before.legal_moves.count() == 1:
        cls: MoveClass = "forced"
    elif book is not None and book(board_before, move):
        cls = "book"
    elif move.uci() == best_move:
        cls = "best"
    else:
        cls = _class_for_loss(loss)
        # A won game stays "won": cap at inaccuracy unless a forced mate was thrown away.
        mover_had_mate = best_line.mate is not None and (best_line.mate > 0) == (mover == "white")
        still_mate = after_line.mate is not None and (after_line.mate > 0) == (mover == "white")
        if wp_after > WON_CAP and _SEVERITY.index(cls) > _SEVERITY.index("inaccuracy") \
                and not (mover_had_mate and not still_mate):
            cls = "inaccuracy"
    return MoveAssessment(
        move=move.uci(), mover=mover, win_prob_before=wp_before, win_prob_after=wp_after,
        loss=loss, move_class=cls, best_move=best_move, best_line=list(best_line.moves),
    )
