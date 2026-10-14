"""Rating → band with hysteresis (docs/06 §1, bands in 03)."""
from __future__ import annotations

from dataclasses import dataclass, field

BAND_FLOORS = [("B0", float("-inf")), ("B1", 800), ("B2", 1200), ("B3", 1600), ("B4", 2000)]
UP_AFTER = 5
DOWN_AFTER = 10


def band_for(rating: float) -> str:
    band = "B0"
    for b, floor in BAND_FLOORS:
        if rating >= floor:
            band = b
    return band


@dataclass
class BandTracker:
    band: str = "B0"
    above: int = 0
    below: int = 0

    def after_game(self, rating: float) -> str:
        """Move up only after 5 consecutive games above the current band, down after 10 below."""
        order = [b for b, _ in BAND_FLOORS]
        raw = band_for(rating)
        i, j = order.index(self.band), order.index(raw)
        if j > i:
            self.above, self.below = self.above + 1, 0
            if self.above >= UP_AFTER:
                self.band, self.above = order[i + 1], 0
        elif j < i:
            self.below, self.above = self.below + 1, 0
            if self.below >= DOWN_AFTER:
                self.band, self.below = order[i - 1], 0
        else:
            self.above = self.below = 0
        return self.band
