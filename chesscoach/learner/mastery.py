"""Concept mastery (docs/06 §2 "Mastery update")."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from chesscoach.learner.glicko2 import Glicko

State = Literal["new", "learning", "practised", "mastered"]
DRILL_WEIGHT = {0: 1.0, 1: 0.6, 2: 0.3, 3: 0.0}     # by deepest hint level used


@dataclass
class Opportunity:
    success: float          # 0..1 (weighted for drills)
    source: Literal["game", "drill"]
    hint_level: int = 0
    at: str = ""


@dataclass
class ConceptMastery:
    player_id: str
    concept_id: str
    state: State = "new"
    opportunities: int = 0
    successes: int = 0                  # found / avoided without hints
    hint_depth_sum: int = 0
    last_seen_at: str = ""
    rating: Optional[Glicko] = None     # v2
    history: list[Opportunity] = field(default_factory=list)   # needed for the windowed rules below

    def record(self, opp: Opportunity) -> State:
        self.opportunities += 1
        self.hint_depth_sum += opp.hint_level
        if opp.success >= 1.0 and opp.hint_level == 0:
            self.successes += 1
        self.last_seen_at = opp.at or self.last_seen_at
        self.history.append(opp)
        self.state = next_state(self)
        return self.state


def _rate(hist: list[Opportunity]) -> float:
    return sum(o.success for o in hist) / len(hist) if hist else 0.0


def next_state(m: ConceptMastery) -> State:
    h = m.history
    last5 = h[-5:]
    if m.state != "new" and len(last5) >= 3 and sum(1 for o in last5 if o.success < 0.5) >= 3:
        return "learning"                                    # any → learning: 3 failures in last 5
    if m.state == "new":
        return "learning" if h else "new"
    if m.state == "learning":
        return "practised" if len(h) >= 8 and _rate(h[-8:]) >= 0.60 else "learning"
    if m.state == "practised":
        real = sum(1 for o in h if o.source == "game" and o.success >= 1.0)
        return "mastered" if len(h) >= 12 and _rate(h[-12:]) >= 0.85 and real >= 2 else "practised"
    return m.state


def game_success(role: str, hint_level: int = 0, threat_parried: bool = False) -> Optional[float]:
    """06: success = role played, or available found without hints, or a threat parried.
    missed / allowed are failures. Returns None for roles that are not opportunities (plan)."""
    if role == "played":
        return 1.0
    if role == "available":
        return 1.0 if hint_level == 0 else DRILL_WEIGHT.get(hint_level, 0.0)
    if role in ("missed", "allowed"):
        return 1.0 if threat_parried else 0.0
    return None
