"""Lichess-style accuracy from win-probability loss (docs/06 §3 "Phase accuracy").

Verified 2026-10-13 against lila modules/analyse/src/main/AccuracyPercent.scala:
per move: 103.1668100711649 * exp(-0.04354415386753951 * winDiff) - 3.166924740191411 (+1
uncertainty bonus), clamped 0..100, 100 when the move loses nothing (winDiff in percent points).
Game accuracy: mean of (volatility-weighted mean, harmonic mean) of per-move accuracies, with
weights = stdev of win% over a sliding window (size = moves/10 clamped 2..8), clamped 0.5..12.
"""
from __future__ import annotations

import math
import statistics


def move_accuracy(win_before: float, win_after: float) -> float:
    """Arguments are mover-POV win probabilities 0..1."""
    diff = (win_before - win_after) * 100
    if diff <= 0:
        return 100.0
    raw = 103.1668100711649 * math.exp(-0.04354415386753951 * diff) - 3.166924740191411 + 1
    return max(0.0, min(100.0, raw))


def game_accuracy(win_before: list[float], win_after: list[float]) -> float | None:
    """Per-colour accuracy over a list of the player's moves (mover-POV probabilities)."""
    accs = [move_accuracy(b, a) for b, a in zip(win_before, win_after)]
    if not accs:
        return None
    series = [p * 100 for p in win_before]
    window = max(2, min(8, len(series) // 10))
    weights = []
    for i in range(len(series)):
        lo = max(0, min(i - window // 2, len(series) - window))
        chunk = series[lo:lo + window]
        sd = statistics.pstdev(chunk) if len(chunk) > 1 else 0.0
        weights.append(max(0.5, min(12.0, sd)))
    weighted = sum(a * w for a, w in zip(accs, weights)) / sum(weights)
    harmonic = len(accs) / sum(1 / max(a, 1e-9) for a in accs)
    return (weighted + harmonic) / 2
