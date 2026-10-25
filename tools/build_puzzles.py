"""Build the drill puzzle bank (docs/06 §6) from the Lichess puzzle database (CC0).

    python tools/build_puzzles.py             # → models/puzzle_bank.json

Streams lichess_db_puzzle.csv.zst and keeps well-established puzzles (rating deviation <= 100,
popularity >= 80, >= 300 plays, solution <= 6 plies) whose primary mapped theme our own detectors
confirm (chesscoach.learner.puzzles.retag), up to QUOTA per (theme, rating band). Lichess replaces
the file monthly, so its sha256 and date are recorded in the output instead of pinned.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from chesscoach.learner.bands import band_for                                 # noqa: E402
from chesscoach.learner.puzzles import Puzzle, load_theme_map, retag            # noqa: E402

URL = "https://database.lichess.org/lichess_db_puzzle.csv.zst"
CACHE = ROOT / "models" / "lichess" / "lichess_db_puzzle.csv.zst"
OUT = ROOT / "models" / "puzzle_bank.json"
QUOTA = 40
MAX_RD, MIN_POPULARITY, MIN_PLAYS, MAX_SOLUTION_PLIES = 100, 80, 300, 6


def download() -> Path:
    if not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {URL}")
        tmp = CACHE.with_suffix(".part")
        urllib.request.urlretrieve(URL, tmp)
        tmp.rename(CACHE)
    return CACHE


def rows(path: Path):
    import zstandard
    with path.open("rb") as raw:
        yield from csv.DictReader(io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(raw), encoding="utf-8"))


def main() -> None:
    import chess
    path = download()
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    sha = h.hexdigest()
    theme_map = load_theme_map()
    filled: Counter = Counter()
    bands = ["B0", "B1", "B2", "B3", "B4"]
    target = len(theme_map) * len(bands) * QUOTA
    out, seen, t0 = [], 0, time.time()
    for row in rows(path):
        seen += 1
        if int(row["RatingDeviation"]) > MAX_RD or int(row["Popularity"]) < MIN_POPULARITY \
                or int(row["NbPlays"]) < MIN_PLAYS:
            continue
        moves = row["Moves"].split()
        if len(moves) - 1 > MAX_SOLUTION_PLIES:
            continue
        themes = row["Themes"].split()
        mapped = [t for t in themes if t in theme_map]
        if not mapped:
            continue
        band = band_for(int(row["Rating"]))
        key = (mapped[0], band)
        if filled[key] >= QUOTA:
            continue
        b = chess.Board(row["FEN"])
        b.push_uci(moves[0])
        p = retag(Puzzle(row["PuzzleId"], b.fen(), moves[1:], int(row["Rating"]), themes, moves[0]), theme_map)
        if p is None:
            continue
        filled[key] += 1
        out.append({"id": p.puzzle_id, "fen": p.fen, "solution": p.solution, "rating": p.rating,
                    "themes": [t for t in themes if t in theme_map], "concepts": p.concept_ids})
        if seen % 200000 == 0:
            print(f"{seen} rows, {len(out)} kept")
        if len(out) >= target:
            break
    OUT.write_text(json.dumps({"source": URL, "license": "CC0-1.0 (Lichess puzzle database)", "sha256": sha,
                               "built": time.strftime("%Y-%m-%d"), "rows_read": seen, "puzzles": out},
                              separators=(",", ":")))
    print(f"read {seen} rows in {time.time() - t0:.0f} s; kept {len(out)}")
    for theme in theme_map:
        print(f"  {theme:18s} " + " ".join(f"{b}:{filled[(theme, b)]:>2}" for b in bands))
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
