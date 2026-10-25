"""Concept registry: loads concepts/<category>/<id>.yaml and validates them (docs/03).

Validation is the "build": a concept that breaks a rule raises ConceptError at load time.

Review gate (AGENTS rule 2): concept text drafted with AI help ships only after a human
approves it. Each record carries `review: {status: draft|approved, by, date}`. The registry
refuses drafts unless loaded with allow_unreviewed=True (or CHESSCOACH_ALLOW_UNREVIEWED=1),
which is for development and tests only.
"""
from __future__ import annotations

import os
import re
import string
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from chesscoach.concepts.predicates import PREDICATE_SLOTS, PREDICATES

CONCEPT_ROOT = Path(__file__).resolve().parent.parent.parent / "concepts"
TEMPLATE_ROOT = Path(__file__).resolve().parent.parent.parent / "templates"

BANDS = ["B0", "B1", "B2", "B3", "B4"]
CATEGORIES = {"tactic", "positional", "structure", "endgame", "opening", "safety", "defence"}
ROLES = ("missed", "allowed", "played", "available", "plan")
ROLE_WEIGHT = {"allowed": 1.0, "missed": 0.9, "available": 0.7, "plan": 0.5, "played": 0.4}
ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
HEDGES = re.compile(r"\b(probably|might|maybe|perhaps|possibly|seems|likely|could be|i think)\b", re.I)
REVEALING = {"move_san", "best_san", "pv_san"}           # level 3 only (03 "Templates")
BUILTIN_SLOTS = {"move_san", "best_san", "pv_san", "threat_move_san", "plan", "user_color", "other_color"}
TRIGGER_KEYS = {"roles", "all", "any", "none", "phase", "structure", "move_class", "engine",
                "sharpness_gte", "predicate", "tablebase", "idea_targets_feature", "moved_piece"}
COND_RESERVED = {"feature", "side", "piece"}
OPS = {"eq", "gte", "lte", "in", "len_gte", "len_lte"}


class ConceptError(ValueError):
    pass


@dataclass
class Concept:
    id: str
    title: str
    category: str
    bands: list[str]
    base_importance: float
    trigger: dict[str, Any]
    templates: dict[str, dict[int, str]]
    slots: dict[str, str] = field(default_factory=dict)
    prerequisites: list[str] = field(default_factory=list)
    parent: Optional[str] = None
    plans: dict[str, list[str]] = field(default_factory=dict)
    drill: dict[str, Any] = field(default_factory=dict)
    tests: Optional[str] = None
    review: dict[str, Any] = field(default_factory=dict)
    path: Optional[Path] = None

    @property
    def roles(self) -> list[str]:
        return list(self.trigger.get("roles", []))

    @property
    def approved(self) -> bool:
        return self.review.get("status") == "approved"


def _placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def _sentences(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s])


def _known_feature_ids() -> set[str]:
    from chesscoach.analysis.analyzer import DETECTORS
    return {fid for d in DETECTORS for fid in d.FEATURE_IDS} | {"mate_threat", "structure"}


def validate(c: Concept, known_features: set[str]) -> None:
    def fail(msg: str):
        raise ConceptError(f"{c.id}: {msg}")

    if not ID_RE.match(c.id):
        fail("id must be kebab-case")
    if c.path is not None and c.path.stem != c.id:
        fail(f"file name {c.path.name} must match id")
    if c.category not in CATEGORIES:
        fail(f"unknown category {c.category}")
    if not c.bands or any(b not in BANDS for b in c.bands):
        fail(f"bad bands {c.bands}")
    if not 0 <= c.base_importance <= 1:
        fail("base_importance must be in 0..1")
    if not c.tests:
        fail("tests: path is required (03, 08)")

    t = c.trigger
    unknown = set(t) - TRIGGER_KEYS
    if unknown:
        fail(f"unknown trigger keys {sorted(unknown)}")
    if not c.roles or any(r not in ROLES for r in c.roles):
        fail(f"bad roles {c.roles}")
    if "predicate" in t and t["predicate"] not in PREDICATES:
        fail(f"unknown predicate {t['predicate']}")
    for key in ("all", "any", "none"):
        for cond in t.get(key, []):
            if "feature" not in cond:
                fail(f"{key} condition without feature")
            if cond["feature"] not in known_features:
                fail(f"unknown feature {cond['feature']}")
            if cond.get("side", "user") not in ("user", "other", "any"):
                fail("side must be user | other | any")
            for k, v in cond.items():
                if k in COND_RESERVED:
                    continue
                if not k.startswith("data."):
                    fail(f"unknown condition key {k}")
                if isinstance(v, dict) and not set(v) <= OPS:
                    fail(f"unknown operator in {k}: {sorted(set(v) - OPS)}")
    if not any(k in t for k in ("all", "any", "predicate", "structure")):
        fail("trigger needs all/any/predicate/structure")

    allowed_slots = BUILTIN_SLOTS | set(c.slots) | PREDICATE_SLOTS.get(t.get("predicate"), set())
    for role, levels in c.templates.items():
        if role not in c.roles:
            fail(f"templates for undeclared role {role}")
        for level, text in levels.items():
            if level not in (0, 1, 2, 3):
                fail(f"bad level {level}")
            if role == "played" and level != 0:
                fail("played role uses level 0 only")
            if role != "played" and level == 0:
                fail("level 0 is only for played (praise)")
            names = _placeholders(text)
            bad = names - allowed_slots
            if bad:
                fail(f"unknown slots {sorted(bad)} in {role}.{level}")
            if names & REVEALING and level != 3:
                fail(f"{sorted(names & REVEALING)} allowed only at level 3 ({role}.{level})")
            if HEDGES.search(text):
                fail(f"hedging word in {role}.{level}: {HEDGES.search(text).group(0)!r}")
            if _sentences(text) > 2:
                fail(f"more than 2 sentences in {role}.{level}")
    for role in c.roles:
        if role not in c.templates:
            fail(f"role {role} has no templates")
    for side, lines in c.plans.items():
        if side not in ("owner", "opponent"):
            fail(f"plans key must be owner/opponent, got {side}")
        for text in lines:
            if HEDGES.search(text):
                fail(f"hedging word in plan: {text!r}")


def _concept_from_dict(d: dict[str, Any], path: Optional[Path] = None) -> Concept:
    templates = {role: {int(k): v for k, v in levels.items()} for role, levels in (d.get("templates") or {}).items()}
    return Concept(
        id=d["id"], title=d["title"], category=d["category"], bands=list(d["bands"]),
        base_importance=float(d["base_importance"]), trigger=d.get("trigger") or {},
        templates=templates, slots=d.get("slots") or {}, prerequisites=d.get("prerequisites") or [],
        parent=d.get("parent"), plans=d.get("plans") or {}, drill=d.get("drill") or {},
        tests=d.get("tests"), review=d.get("review") or {}, path=path)


class Registry:
    def __init__(self, concepts: list[Concept], all_ids: Optional[set[str]] = None):
        """`all_ids`: every concept id on disk, drafts included. A parent or prerequisite that
        exists but is not approved yet is allowed (experts approve in any order); one that does
        not exist at all is an error."""
        self.concepts = {c.id: c for c in concepts}
        known = self.concepts.keys() | (all_ids or set())
        for c in concepts:
            if c.parent and c.parent not in known:
                raise ConceptError(f"{c.id}: parent {c.parent} not found")
            for p in c.prerequisites:
                if p not in known:
                    raise ConceptError(f"{c.id}: prerequisite {p} not found")

    @classmethod
    def load(cls, root: Path = CONCEPT_ROOT, allow_unreviewed: Optional[bool] = None,
             lang: str = "en") -> "Registry":
        if allow_unreviewed is None:
            allow_unreviewed = os.environ.get("CHESSCOACH_ALLOW_UNREVIEWED") == "1"
        known = _known_feature_ids()
        concepts, all_ids = [], set()
        for path in sorted(root.glob("*/*.yaml")):
            c = _concept_from_dict(yaml.safe_load(path.read_text()), path)
            if path.parent.name != c.category:
                raise ConceptError(f"{c.id}: lives in {path.parent.name}/ but category is {c.category}")
            override = TEMPLATE_ROOT / lang / f"{c.id}.yaml"
            if lang != "en" and override.exists():
                tr = yaml.safe_load(override.read_text())
                c.templates = {r: {int(k): v for k, v in lv.items()} for r, lv in tr["templates"].items()}
                c.plans = tr.get("plans", c.plans)
            validate(c, known)
            all_ids.add(c.id)
            if not c.approved and not allow_unreviewed:
                continue
            concepts.append(c)
        return cls(concepts, all_ids)

    def get(self, concept_id: str) -> Concept:
        return self.concepts[concept_id]

    def __iter__(self):
        return iter(self.concepts.values())

    def __len__(self) -> int:
        return len(self.concepts)

    def ancestors(self, concept_id: str) -> set[str]:
        out, cur = set(), self.concepts[concept_id].parent
        while cur:
            out.add(cur)
            cur = self.concepts[cur].parent if cur in self.concepts else None
        return out
