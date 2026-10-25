"""Line explanations (docs/02 §6.6): every case in tests/positions/lines/*.yaml, engine-free."""
from __future__ import annotations

import pytest

from chesscoach.analysis.lines import explain_line
from positions_lib import load, valid_board

CASES = load("lines")
STEP_FIELDS = ("check", "mate", "captured", "promotion", "material")


@pytest.mark.parametrize("stem,header,case", CASES, ids=[c["id"] for _, _, c in CASES])
def test_line_case(stem, header, case):
    board = valid_board(case["fen"])
    ex = explain_line(board, case["line"], case["perspective"])
    e = case["expect"]
    assert ex.outcome == e["outcome"], (ex.outcome, ex.material_change, case.get("note"))
    for k in ("material_change", "decisive_ply", "mate_for"):
        if k in e:
            assert getattr(ex, k) == e[k], (k, getattr(ex, k), e[k], case.get("note"))
    if "steps_count" in e:
        assert len(ex.steps) == e["steps_count"]
    for ply, exp in (e.get("steps") or {}).items():
        st = ex.steps[int(ply)]
        for k in STEP_FIELDS:
            if k in exp:
                assert getattr(st, k) == exp[k], (ply, k, getattr(st, k), exp[k])
        for fid in exp.get("features_include", []):
            assert fid in st.feature_ids, (ply, fid, st.feature_ids)
        for fid in exp.get("features_absent", []):
            assert fid not in st.feature_ids, (ply, fid, st.feature_ids)


def test_case_counts():
    """08 §1: >= 5 cases with an outcome and >= 5 that must report none."""
    pos = sum(1 for _, _, c in CASES if c["expect"]["outcome"] != "none")
    neg = sum(1 for _, _, c in CASES if c["expect"]["outcome"] == "none")
    assert pos >= 5 and neg >= 5, (pos, neg)


def test_perspective_flips_signs():
    board = valid_board("r3k2r/pp3ppp/8/3N4/8/8/PPP2PPP/R3K2R w KQkq - 0 1")
    w = explain_line(board, ["d5c7", "e8d8", "c7a8"], "white")
    b = explain_line(board, ["d5c7", "e8d8", "c7a8"], "black")
    assert w.material_change == -b.material_change == 5
    assert [s.material for s in w.steps] == [-s.material for s in b.steps]
