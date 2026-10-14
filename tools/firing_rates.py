"""Firing rates per feature and per concept (docs/08 §3).

    python tools/firing_rates.py tests/regression/positions.jsonl [--previous rates.json] [--out rates.json]

positions.jsonl: one {"fen": ..., "band": "B1"} per line (sample 10k positions from the Lichess
games database, stratified by band and phase — not included in the repo yet). Features are
counted per 100 positions without the engine (static detectors); concepts use the `available`
and `plan` roles with a shallow engine search. Exits 1 if a concept's rate moved > 50% relative
vs --previous, and lists concepts firing in > 5% of middlegame positions.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

import chess

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("CHESSCOACH_ALLOW_UNREVIEWED", "1")

from chesscoach.analysis.analyzer import Analyzer, static_features  # noqa: E402
from chesscoach.analysis.engine import EnginePool  # noqa: E402
from chesscoach.analysis.phase import game_phase  # noqa: E402
from chesscoach.concepts.matcher import match, views_for_position  # noqa: E402
from chesscoach.concepts.registry import Registry  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("positions")
    ap.add_argument("--previous")
    ap.add_argument("--out")
    ap.add_argument("--depth", type=int, default=10)
    args = ap.parse_args()
    rows = [json.loads(l) for l in Path(args.positions).read_text().splitlines() if l.strip()]
    reg = Registry.load(allow_unreviewed=True)
    an = Analyzer(EnginePool(size=1), threats=False)
    feat, conc, mid_conc = Counter(), Counter(), Counter()
    n_mid = 0
    for r in rows:
        b = chess.Board(r["fen"])
        phase = game_phase(b)
        for fid in {f.id for f in static_features(b, phase)}:
            feat[fid] += 1
        eng = an.engine(b, depth=args.depth)
        ids = {h.concept_id for h in match(reg, views_for_position(b, eng, an.features(b, eng)), r.get("band", "B1"))}
        conc.update(ids)
        if phase == "middlegame":
            n_mid += 1
            mid_conc.update(ids)
    n = max(len(rows), 1)
    rates = {"features": {k: 100 * v / n for k, v in feat.items()}, "concepts": {k: 100 * v / n for k, v in conc.items()}}
    if args.out:
        Path(args.out).write_text(json.dumps(rates, indent=1, sort_keys=True))
    loose = {k: 100 * v / n_mid for k, v in mid_conc.items() if n_mid and v / n_mid > 0.05}
    for k, v in sorted(loose.items()):
        print(f"REVIEW (too loose?) {k}: {v:.1f}% of middlegame positions")
    status = 0
    if args.previous:
        prev = json.loads(Path(args.previous).read_text())["concepts"]
        for k in set(prev) | set(rates["concepts"]):
            a, b2 = prev.get(k, 0.0), rates["concepts"].get(k, 0.0)
            if (a == 0 and b2 > 0) or (a > 0 and abs(b2 - a) / a > 0.5):
                print(f"FIRING RATE CHANGE {k}: {a:.2f} -> {b2:.2f} per 100 (needs acknowledgement in the PR)")
                status = 1
    an.close()
    return status


if __name__ == "__main__":
    sys.exit(main())
