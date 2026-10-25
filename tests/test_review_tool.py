"""Expert review tool (AGENTS rule 2): page data and applying decisions to the YAML."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

from chesscoach.concepts.registry import CONCEPT_ROOT, Registry
from chesscoach.concepts.review_tool import (check_templates, concept_detail, concept_list, fallback_detail,
                                             with_templates)
from chesscoach.policy.policy import FALLBACK_FILE

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import apply_review  # noqa: E402

REG = Registry.load(allow_unreviewed=True)


def test_list_and_fallback():
    items = concept_list(REG)
    assert len(items) == len(REG) and {"id", "title", "status", "roles"} <= set(items[0])
    assert all(i["status"] in ("draft", "approved", "changes_requested") for i in items)
    fb = fallback_detail()
    assert {"engine", "threat"} <= set(fb["templates"]) and fb["templates"]["engine"]["3"]


def test_edited_templates_are_checked_with_the_registry_rules():
    c = REG.get("tactic-fork-knight")
    assert check_templates(c) == []
    bad = with_templates(c, {"available": {"1": "Play {move_san} now."}})
    assert any("move_san" in e for e in check_templates(bad))
    hedge = with_templates(c, {"available": {"1": "This might be a fork.", "2": "x", "3": "y"}})
    assert check_templates(hedge)


def test_concept_detail_runs_its_test_positions(analyzer):
    d = concept_detail(REG.get("tactic-fork-knight"), REG, analyzer)
    assert not d["errors"] and d["cases"]
    assert all(case["ok"] for case in d["cases"]), [(c["id"], c["hit"]) for c in d["cases"] if not c["ok"]]
    shown = [c for c in d["cases"] if c["hit"]]
    assert shown and all(t for c in shown for t in c["texts"].values())       # every level renders
    assert any("{" not in t and "c7" in t for c in shown for t in c["texts"].values())


@pytest.fixture
def copies(tmp_path):
    concepts = tmp_path / "concepts"
    shutil.copytree(CONCEPT_ROOT, concepts)
    fb = tmp_path / "_fallback.yaml"
    shutil.copy(FALLBACK_FILE, fb)
    return concepts, fb


def run(tmp_path, copies, decisions, *extra):
    p = tmp_path / "decisions.json"
    p.write_text(json.dumps(decisions))
    return apply_review.main([str(p), "--concepts", str(copies[0]), "--fallback", str(copies[1]), *extra])


def test_apply_approves_edits_and_keeps_the_rest(tmp_path, copies):
    rc = run(tmp_path, copies, {"reviewer": "A. Coach", "date": "2026-10-25", "concepts": {
        "tactic-fork-knight": {"decision": "approved", "note": "ok",
                               "templates": {"available": {"2": "Look at the square {square}."}}},
        "_fallback": {"decision": "changes_requested", "note": "level 1 too vague"}}})
    assert rc == 0
    doc = yaml.safe_load((copies[0] / "tactic" / "tactic-fork-knight.yaml").read_text())
    assert doc["review"]["status"] == "approved" and doc["review"]["by"] == "A. Coach"
    assert doc["review"]["drafted_by"].startswith("AI-assisted")                 # history kept
    assert doc["templates"]["available"][2] == "Look at the square {square}."
    assert doc["templates"]["available"][1] == REG.get("tactic-fork-knight").templates["available"][1]
    fb_text = copies[1].read_text()
    assert "changes_requested" in fb_text and fb_text.lstrip().startswith("#")   # comments preserved
    approved = Registry.load(copies[0], allow_unreviewed=False)
    assert [c.id for c in approved] == ["tactic-fork-knight"]                    # only approved ships


def test_apply_refuses_invalid_edits_and_writes_nothing(tmp_path, copies):
    before = (copies[0] / "tactic" / "tactic-fork-knight.yaml").read_text()
    rc = run(tmp_path, copies, {"reviewer": "A", "date": "2026-10-25", "concepts": {
        "tactic-fork-knight": {"decision": "approved", "templates": {"available": {"1": "Play {move_san}."}}}}})
    assert rc == 1
    assert (copies[0] / "tactic" / "tactic-fork-knight.yaml").read_text() == before
    assert run(tmp_path, copies, {"reviewer": "", "date": "x", "concepts": {}}) == 2


def test_dry_run_changes_nothing(tmp_path, copies):
    before = (copies[0] / "tactic" / "tactic-fork-knight.yaml").read_text()
    assert run(tmp_path, copies, {"reviewer": "A", "date": "d", "concepts": {
        "tactic-fork-knight": {"decision": "approved"}}}, "--dry-run") == 0
    assert (copies[0] / "tactic" / "tactic-fork-knight.yaml").read_text() == before
