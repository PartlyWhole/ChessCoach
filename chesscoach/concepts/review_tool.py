"""Expert review of coaching text (AGENTS rule 2, docs/03 "Authoring workflow").

Feeds the /review/ page: every concept (drafts included) with its templates, and each of its test
positions run through the matcher, so the reviewer sees the exact sentences the coach would say at
each hint level, where, and with which highlights. Edited templates are checked with the same
rules the registry enforces at load time (`registry.validate`).

Nothing here approves anything: the page exports the reviewer's decisions as a file, and
`tools/apply_review.py` writes them into the YAML, which ships through a normal commit.
"""
from __future__ import annotations

import copy
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import chess
import yaml

from chesscoach.concepts.matcher import match, views_after_move, views_for_position
from chesscoach.concepts.registry import Concept, ConceptError, Registry, _known_feature_ids, validate
from chesscoach.concepts.render import levels, render
from chesscoach.policy.policy import FALLBACK_FILE

ROOT = Path(__file__).resolve().parent.parent.parent


def concept_list(registry: Registry) -> list[dict]:
    out = []
    for c in sorted(registry, key=lambda c: (c.category, c.id)):
        out.append({"id": c.id, "title": c.title, "category": c.category, "bands": c.bands,
                    "status": c.review.get("status", "draft"), "reviewed_by": c.review.get("by", ""),
                    "roles": sorted(c.templates)})
    return out


def _templates_json(templates: dict) -> dict:
    return {role: {str(lv): text for lv, text in sorted(lvs.items())} for role, lvs in templates.items()}


def with_templates(c: Concept, templates: Optional[dict]) -> Concept:
    """A copy of `c` with edits ({role: {level: text}}, levels as str or int) merged over its
    templates; roles and levels not mentioned keep their text."""
    if not templates:
        return c
    d = copy.copy(c)
    d.templates = {role: dict(lvs) for role, lvs in c.templates.items()}
    for role, lvs in templates.items():
        d.templates.setdefault(role, {}).update({int(lv): text for lv, text in lvs.items()})
    return d


def check_templates(c: Concept) -> list[str]:
    try:
        validate(c, _known_feature_ids())
    except ConceptError as e:
        return [str(e)]
    return []


def load_cases(c: Concept) -> list[dict]:
    if not c.tests:
        return []
    p = ROOT / c.tests
    if not p.exists():
        return []
    return yaml.safe_load(p.read_text()).get("cases", [])


def evaluate_case(c: Concept, registry: Registry, analyzer, case: dict, depth: Optional[int] = None) -> dict:
    """Run one test position like tests/test_concepts.py; return the hit and its texts per level."""
    board = chess.Board(case["fen"])
    band = case.get("band", c.bands[0])
    exp = case["expect"]
    if "move" in case:
        before, after, assessment, pf_b, pf_a = analyzer.analyze(case["fen"], case["move"], depth=depth)
        views = views_after_move(board, chess.Move.from_uci(case["move"]), assessment, before, pf_b, after, pf_a)
    else:
        eng = analyzer.engine(board, depth=depth)
        views = views_for_position(board, eng, analyzer.features(board, eng))
    hits = [h for h in match(registry, views, band, review=True) if h.concept_id == c.id and h.role == exp["role"]]
    present = exp.get("present", True)
    out = {"id": case["id"], "fen": case["fen"], "move": case.get("move"), "role": exp["role"],
           "expect_present": present, "note": case.get("note", ""), "band": band, "hit": None, "texts": {},
           "ok": bool(hits) == present}
    if hits:
        h = hits[0]
        out["hit"] = {"slots": h.slots, "highlight": asdict(h.highlight), "evidence": h.evidence}
        out["texts"] = {str(lv): render(c, h, lv) for lv in levels(c, h.role)}
        if "move" in case:
            out["move_san"] = board.san(chess.Move.from_uci(case["move"]))
    return out


def concept_detail(c: Concept, registry: Registry, analyzer, templates: Optional[dict] = None,
                   depth: Optional[int] = None) -> dict:
    edited = with_templates(c, templates)
    errors = check_templates(edited)
    cases = [] if errors else [evaluate_case(edited, registry, analyzer, case, depth) for case in load_cases(edited)]
    return {"id": c.id, "title": c.title, "category": c.category, "bands": c.bands, "review": c.review,
            "slots": c.slots, "templates": _templates_json(edited.templates), "errors": errors, "cases": cases,
            "rules": ["Second person, present tense, at most 2 sentences per level.",
                      "Level 1 asks or points at an area and never names the move; level 2 names a square or "
                      "piece; level 3 gives the move and the reason.",
                      "{move_san} only at level 3. No hedging words (probably, might, maybe…).",
                      "Every {slot} must come from the concept's slots."]}


def fallback_detail() -> dict:
    doc = yaml.safe_load(FALLBACK_FILE.read_text())
    return {"id": "_fallback", "title": "Fallback texts (no concept explains the move)",
            "review": doc.get("review", {}), "templates": _templates_json(
                {k: {int(lv): t for lv, t in v.items()} for k, v in doc["templates"].items()})}
