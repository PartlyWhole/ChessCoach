"""Runs every case in tests/positions/detectors/*.yaml (docs/08 §1)."""
from __future__ import annotations

import time

import chess
import pytest

from chesscoach.analysis import analyzer as an
from chesscoach.analysis.phase import game_phase
from chesscoach.analysis.structure import classify_structure
from chesscoach.types import Feature
from positions_lib import check, load, valid_board

CASES = load("detectors")
ENGINE_FEATURES = {"fork", "removing_defender", "mate_threat"}
_OWNER = {fid: d for d in an.DETECTORS for fid in d.FEATURE_IDS}


def _features(board: chess.Board, case: dict, feature_id: str, request) -> list:
    if feature_id == "structure":
        sid, owner = classify_structure(board)
        return [Feature(id="structure", side=owner or "white", squares=[],
                        data={"structure_id": sid, "owner": owner})] if sid else []
    if feature_id == "mate_threat":
        a = request.getfixturevalue("analyzer")
        return a.features(board, a.engine(board)).features
    if "move" not in case:
        return an.static_features(board, game_phase(board))
    move = chess.Move.from_uci(case["move"])
    assert board.is_legal(move), f"illegal move {case['move']}"
    after = board.copy()
    after.push(move)
    pv, eng = [], None
    if feature_id in ENGINE_FEATURES:
        pool = request.getfixturevalue("pool")
        eng = pool.analyse(after, depth=case.get("depth", 16))
        pv = [chess.Move.from_uci(m) for m in eng.lines[0].moves] if eng.lines else []
    phase = game_phase(after)
    return an.static_features(after, phase) + an.move_features(board, move, pv, eng, phase)


@pytest.mark.parametrize("stem,header,case", CASES, ids=[f"{s}:{c['id']}" for s, _, c in CASES])
def test_detector_case(stem, header, case, request):
    fid = header["detector"]
    assert fid in _OWNER or fid in ("mate_threat", "structure"), f"unknown detector {fid}"
    if fid in ENGINE_FEATURES:
        assert "engine" in header, "engine-dependent file must pin engine name + depth in its header"
    board = valid_board(case["fen"])
    err = check(_features(board, case, fid, request), fid, case["expect"])
    assert err is None, f"{case['id']}: {err}  ({case.get('note', '')})"


def test_case_counts():
    """08 §1: every detector has >= 5 positive and >= 5 negative cases."""
    counts: dict[str, list[int]] = {}
    for _, header, case in CASES:
        c = counts.setdefault(header["detector"], [0, 0])
        c[0 if case["expect"].get("present", True) else 1] += 1
    all_ids = {fid for d in an.DETECTORS for fid in d.FEATURE_IDS} | {"mate_threat", "structure"}
    missing = sorted(all_ids - set(counts))
    short = {k: v for k, v in counts.items() if v[0] < 5 or v[1] < 5}
    assert not missing, f"detectors without test files: {missing}"
    assert not short, f"detectors with < 5 positive / < 5 negative cases: {short}"


def test_static_suite_speed():
    """08 §8: all detectors, one position, no engine, < 20 ms (median over a few positions)."""
    fens = [c["fen"] for _, _, c in CASES[:40]] or [chess.STARTING_FEN]
    times = []
    for fen in fens:
        b = chess.Board(fen)
        t = time.perf_counter()
        an.static_features(b, game_phase(b))
        times.append(time.perf_counter() - t)
    times.sort()
    assert times[len(times) // 2] < 0.020, f"median {times[len(times)//2]*1000:.1f} ms"
