"""Template rendering (docs/03 "Templates"). Never invents text: if a slot a template needs is
missing, that level cannot be shown (returns None) and the caller falls back (04)."""
from __future__ import annotations

import string
from typing import Optional

from chesscoach.concepts.registry import Concept
from chesscoach.types import ConceptHit


def levels(concept: Concept, role: str) -> list[int]:
    return sorted(concept.templates.get(role, {}))


def render(concept: Concept, hit: ConceptHit, level: int) -> Optional[str]:
    text = concept.templates.get(hit.role, {}).get(level)
    if text is None:
        return None
    needed = {name for _, name, _, _ in string.Formatter().parse(text) if name}
    if not needed <= set(hit.slots):
        return None
    return text.format(**{k: hit.slots[k] for k in needed})


def renderable_levels(concept: Concept, hit: ConceptHit) -> list[int]:
    return [lv for lv in levels(concept, hit.role) if render(concept, hit, lv) is not None]
