"""Centipawn → win probability (docs/02 §2)."""
from __future__ import annotations

import math
from typing import Optional

import chess
import chess.engine

from chesscoach.types import Color, EngineLine

# Verified 2026-10-13 against scalachess core/src/main/scala/eval.scala:
# WinPercent.fromCentiPawns(cp) = 50 + 50 * (2 / (1 + exp(-0.00368208 * cp.ceiled)) - 1),
# with cp.ceiled clamping to ±1000. On a 0..1 scale that is 1 / (1 + exp(-K * cp)).
K = 0.00368208
CP_CEILING = 1000


def win_prob_cp(cp: int) -> float:
    cp = max(-CP_CEILING, min(CP_CEILING, cp))
    return 1 / (1 + math.exp(-K * cp))


def win_prob(score: chess.engine.Score) -> float:
    """`score` is White POV. Mate → 1.0 / 0.0."""
    if score.is_mate():
        # Mate(0) / Mate(-0): side to move is mated; python-chess orders -0 < 0.
        return 1.0 if score > chess.engine.Cp(0) else 0.0
    return win_prob_cp(score.score())


def win_prob_cp_or_mate(cp: Optional[int], mate: Optional[int]) -> float:
    if mate is not None:
        return 1.0 if mate > 0 else 0.0
    return win_prob_cp(cp or 0)


def for_color(p_white: float, color: Color) -> float:
    """Mover-POV conversion: p_mover = p_white if white else 1 - p_white."""
    return p_white if color == "white" else 1 - p_white


def line_wp(line: EngineLine, color: Color) -> float:
    return for_color(line.win_prob, color)
