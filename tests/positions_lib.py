"""Loader and checker for the shared test-position format (docs/08 §1).

Detector file header:

    detector: fork                 # feature id under test
    engine: {name: "Stockfish 19", depth: 16}   # required when any case needs the engine
    cases:
      - id: ...
        fen: "..."
        move: "e2e4"               # optional: check features created by this move
        expect:
          present: true
          side: white              # optional
          squares_include: [...]   # optional
          data: {piece: knight}    # optional subset match
        note: "..."
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import chess
import yaml

ROOT = Path(__file__).parent / "positions"


def load(kind: str) -> list[tuple[str, dict, dict]]:
    """[(file stem, header, case)] for every case under positions/<kind>/."""
    out = []
    for p in sorted((ROOT / kind).glob("*.yaml")):
        doc = yaml.safe_load(p.read_text())
        for case in doc.get("cases", []):
            out.append((p.stem, doc, case))
    return out


def valid_board(fen: str) -> chess.Board:
    board = chess.Board(fen)
    assert board.is_valid(), f"invalid FEN {fen}: {board.status()!r}"
    return board


def _data_matches(actual: dict, expected: dict) -> bool:
    for k, v in expected.items():
        a = actual.get(k)
        if isinstance(v, list) and isinstance(a, list):
            if not set(v) <= set(a):
                return False
        elif a != v:
            return False
    return True


def matching(features: list, feature_id: str, expect: dict) -> list:
    out = []
    for f in features:
        if f.id != feature_id:
            continue
        if "side" in expect and f.side != expect["side"]:
            continue
        if "squares_include" in expect and not set(expect["squares_include"]) <= set(f.squares):
            continue
        if "data" in expect and not _data_matches(f.data, expect["data"]):
            continue
        out.append(f)
    return out


def check(features: list, feature_id: str, expect: dict) -> Optional[str]:
    """None if the expectation holds, else a message."""
    hits = matching(features, feature_id, expect)
    if expect.get("present", True) and not hits:
        got = [(f.id, f.side, f.squares, f.data) for f in features if f.id == feature_id]
        return f"expected {feature_id} {expect}, got {got}"
    if not expect.get("present", True) and hits:
        return f"expected no {feature_id} matching {expect}, got {[(f.side, f.squares, f.data) for f in hits]}"
    return None
