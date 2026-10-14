"""Weakness profile (docs/06 §3) and lesson-focus selection."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from chesscoach.learner.accuracy import game_accuracy

# Which concept categories each metric points at (lesson focus selection).
METRIC_CATEGORIES = {
    "tactics_found": ["tactic"],
    "tactics_allowed": ["safety", "tactic", "defence"],
    "opening": ["opening"],
    "conversion": ["positional", "structure"],
    "resourcefulness": ["defence"],
    "endgame": ["endgame"],
    "time_trouble": [],
}
# Direction: True if higher is better.
HIGHER_IS_BETTER = {"tactics_found": True, "tactics_allowed": False, "opening": False, "conversion": True,
                    "resourcefulness": True, "endgame": False, "time_trouble": False}
# Fixed coach-set targets used until enough peers exist per band (06 §3). Draft values.
DEFAULT_TARGETS = {"tactics_found": 0.5, "tactics_allowed": 1.5, "opening": 0.03, "conversion": 0.8,
                   "resourcefulness": 0.15, "endgame": 0.04, "time_trouble": 0.2}


@dataclass
class MoveRecord:
    """Slice of a GameLogMove the profile needs (player's moves only)."""
    ply: int
    phase: str
    win_before: float               # player POV
    win_after: float
    move_class: str
    roles: dict[str, list[str]] = field(default_factory=dict)  # role -> concept categories hit
    available_tactic_sharp: bool = False   # an `available` tactical hit with sharpness >= 0.6 existed
    found_available: bool = False          # ... and the player played it
    clock_fraction: Optional[float] = None # remaining / starting clock


@dataclass
class GameRecord:
    moves: list[MoveRecord]
    result: float                   # player score: 1 / 0.5 / 0


def profile(games: Iterable[GameRecord]) -> dict[str, Optional[float]]:
    games = list(games)
    moves = [m for g in games for m in g.moves]
    out: dict[str, Optional[float]] = {}
    sharp = [m for m in moves if m.available_tactic_sharp]
    out["tactics_found"] = sum(m.found_available for m in sharp) / len(sharp) if sharp else None
    allowed = sum(1 for m in moves if m.move_class == "blunder" and "tactic" in m.roles.get("allowed", []))
    out["tactics_allowed"] = 100 * allowed / len(moves) if moves else None
    op = [m.win_before - m.win_after for m in moves if m.ply <= 24]
    out["opening"] = sum(max(0, x) for x in op) / len(op) if op else None
    won_pos = [g for g in games if any(m.win_before >= 0.85 for m in g.moves)]
    out["conversion"] = sum(g.result == 1 for g in won_pos) / len(won_pos) if won_pos else None
    lost_pos = [g for g in games if any(m.win_before <= 0.15 for m in g.moves)]
    out["resourcefulness"] = sum(g.result >= 0.5 for g in lost_pos) / len(lost_pos) if lost_pos else None
    eg = [m.win_before - m.win_after for m in moves if m.phase == "endgame"]
    out["endgame"] = sum(max(0, x) for x in eg) / len(eg) if eg else None
    mistakes = [m for m in moves if m.move_class in ("mistake", "blunder") and m.clock_fraction is not None]
    out["time_trouble"] = sum(m.clock_fraction < 0.10 for m in mistakes) / len(mistakes) if mistakes else None
    for phase in ("opening", "middlegame", "endgame"):
        pm = [m for m in moves if m.phase == phase]
        out[f"accuracy_{phase}"] = game_accuracy([m.win_before for m in pm], [m.win_after for m in pm])
    return out


def worst_metric(prof: dict[str, Optional[float]], targets: Optional[dict[str, float]] = None) -> Optional[str]:
    """Metric furthest on the wrong side of its target (relative), among measured ones."""
    targets = targets or DEFAULT_TARGETS
    worst, worst_gap = None, 0.0
    for k, target in targets.items():
        v = prof.get(k)
        if v is None or not METRIC_CATEGORIES.get(k):
            continue
        gap = (target - v) if HIGHER_IS_BETTER[k] else (v - target)
        rel = gap / max(abs(target), 1e-6)
        if rel > worst_gap:
            worst, worst_gap = k, rel
    return worst


STATE_ORDER = {"new": 0, "learning": 1, "practised": 2, "mastered": 3}


def choose_lesson_focus(prof: dict, registry, band: str, mastery: dict[str, "object"],
                        recent_two_games: set[str], targets: Optional[dict[str, float]] = None) -> Optional[str]:
    """06 §3: lowest ConceptMastery among concepts in the player's band whose category maps to the
    worst metric, excluding concepts mentioned in the last 2 games. Ties: lower success rate, then id."""
    metric = worst_metric(prof, targets)
    if metric is None:
        return None
    cats = set(METRIC_CATEGORIES[metric])
    cands = [c for c in registry if band in c.bands and c.category in cats and c.id not in recent_two_games]
    if not cands:
        return None

    def key(c):
        m = mastery.get(c.id)
        state = STATE_ORDER[getattr(m, "state", "new")]
        rate = (m.successes / m.opportunities) if m is not None and m.opportunities else 0.0
        return (state, rate, c.id)

    return min(cands, key=key).id
