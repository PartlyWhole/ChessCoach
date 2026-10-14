"""Concept tests (docs/08 §1): tests/positions/concepts/<concept_id>.yaml.

    concept: tactic-fork-knight
    engine: {name: "Stockfish 19", depth: 16}
    cases:
      - id: ...
        fen: "..."            # position before the player's move (or the current position)
        move: "e2e4"          # present → roles missed/allowed/played; absent → available/plan
        band: B1              # optional, default: the concept's first band
        expect: {role: missed, present: true, slots: {square: d5}}

Every level of every matching hit must render (no unfillable slot), and rendered text is
checked for the template rules.
"""
from __future__ import annotations

import os

import chess
import pytest

os.environ.setdefault("CHESSCOACH_ALLOW_UNREVIEWED", "1")

from chesscoach.concepts.matcher import match, views_after_move, views_for_position  # noqa: E402
from chesscoach.concepts.registry import Registry  # noqa: E402
from chesscoach.concepts.render import levels, render  # noqa: E402
from positions_lib import load, valid_board  # noqa: E402

REGISTRY = Registry.load(allow_unreviewed=True)
CASES = load("concepts")


def hits_for(analyzer, case: dict, band: str):
    board = valid_board(case["fen"])
    if "move" in case:
        before, after, assessment, pf_b, pf_a = analyzer.analyze(case["fen"], case["move"])
        views = views_after_move(board, chess.Move.from_uci(case["move"]), assessment, before, pf_b, after, pf_a)
    else:
        eng = analyzer.engine(board)
        views = views_for_position(board, eng, analyzer.features(board, eng))
    return match(REGISTRY, views, band, review=True)


@pytest.mark.parametrize("stem,header,case", CASES, ids=[f"{s}:{c['id']}" for s, _, c in CASES])
def test_concept_case(stem, header, case, analyzer):
    cid = header["concept"]
    assert cid in REGISTRY.concepts, f"unknown concept {cid}"
    assert "engine" in header, "concept tests run the engine: pin name + depth in the header"
    concept = REGISTRY.get(cid)
    band = case.get("band", concept.bands[0])
    exp = case["expect"]
    hits = [h for h in hits_for(analyzer, case, band) if h.concept_id == cid and h.role == exp["role"]]
    if not exp.get("present", True):
        assert not hits, f"{case['id']}: unexpected {cid}/{exp['role']} hit {hits}"
        return
    assert hits, f"{case['id']}: expected {cid}/{exp['role']}"
    h = hits[0]
    for k, v in (exp.get("slots") or {}).items():
        assert h.slots.get(k) == str(v), f"{case['id']}: slot {k}={h.slots.get(k)!r}, expected {v!r}"
    for lv in levels(concept, h.role):
        assert render(concept, h, lv) is not None, f"{case['id']}: level {lv} cannot render; slots={h.slots}"


def test_every_concept_has_tests():
    """08 §1: every concept has >= 3 positive and >= 2 negative cases, and covers each role."""
    by: dict[str, dict] = {}
    for _, header, case in CASES:
        d = by.setdefault(header["concept"], {"pos": 0, "neg": 0, "roles": set()})
        if case["expect"].get("present", True):
            d["pos"] += 1
            d["roles"].add(case["expect"]["role"])
        else:
            d["neg"] += 1
    problems = {}
    for c in REGISTRY:
        d = by.get(c.id)
        if d is None:
            problems[c.id] = "no test file"
        elif d["pos"] < 3 or d["neg"] < 2 or set(c.roles) - d["roles"]:
            problems[c.id] = f"pos={d['pos']} neg={d['neg']} missing roles={sorted(set(c.roles) - d['roles'])}"
    assert not problems, problems
