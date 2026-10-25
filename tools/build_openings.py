"""Build the sparring bot's opening tree (docs/05 §2) from one month of the Lichess games database
(database.lichess.org, CC0).

    python tools/build_openings.py            # → models/opening_tree.json

Each rating band (03 band ids, by the players' average rating) gets its own tree: per position
(fen4) the count of each next move, for the first MAX_PLIES plies, keeping moves played in at
least MIN_GAMES games of that band (the same cut-off the bot uses to leave the tree). An "all"
tree over every band is the fallback when a band's node is too thin.

Two passes over the compressed file keep memory bounded: pass 1 counts every move sequence up to
SPLIT plies; pass 2 counts plies SPLIT+1..MAX_PLIES only below sequences that passed MIN_GAMES.
Sequences are then replayed once with python-chess to key them by position, so transpositions
merge.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import chess

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from chesscoach.analysis.engine import fen4               # noqa: E402
from chesscoach.learner.bands import band_for             # noqa: E402

MONTH = "2014-01"
URL = f"https://database.lichess.org/standard/lichess_db_standard_rated_{MONTH}.pgn.zst"
SHA256 = "f4e9efea9aeb608211a1e1b62aff00b92679eab6b70f957e77a1d7c4d8bfbbc8"
CACHE = ROOT / "models" / "lichess" / f"lichess_db_standard_rated_{MONTH}.pgn.zst"
OUT = ROOT / "models" / "opening_tree.json"
MAX_PLIES = 12
SPLIT = 8
MIN_GAMES = 50

COMMENT = re.compile(r"\{[^}]*\}")
MOVE_NO = re.compile(r"^\d+\.(\.\.)?$")
RESULTS = {"1-0", "0-1", "1/2-1/2", "*"}


def download() -> Path:
    if not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {URL}")
        tmp = CACHE.with_suffix(".part")
        urllib.request.urlretrieve(URL, tmp)
        tmp.rename(CACHE)
    h = hashlib.sha256()
    with CACHE.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != SHA256:
        raise SystemExit(f"sha256 mismatch for {CACHE}")
    return CACHE


def games(path: Path):
    """(band, [SAN, ...]) for each rated standard game with both ratings."""
    import zstandard
    with path.open("rb") as raw:
        text = io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(raw), encoding="utf-8", errors="replace")
        elo: dict[str, int] = {}
        movetext: list[str] = []
        for line in text:
            if line.startswith("["):
                if movetext:
                    yield from _emit(elo, movetext)
                    elo, movetext = {}, []
                if line.startswith("[WhiteElo ") or line.startswith("[BlackElo "):
                    v = line.split('"')[1]
                    if v.isdigit():
                        elo[line[1:6]] = int(v)
            elif line.strip():
                movetext.append(line)
        if movetext:
            yield from _emit(elo, movetext)


def _emit(elo, movetext):
    if len(elo) != 2:
        return
    toks = [t for t in COMMENT.sub(" ", " ".join(movetext)).split()
            if not MOVE_NO.match(t) and t not in RESULTS and not t.startswith("$")]
    toks = [re.sub(r"^\d+\.+", "", t) for t in toks if re.sub(r"^\d+\.+", "", t)]
    if len(toks) >= 2:
        yield band_for((elo["White"] + elo["Black"]) / 2), toks[:MAX_PLIES]


def count(path: Path):
    """counts[band][prefix] = Counter(next SAN); prefix = SAN moves joined by spaces."""
    counts: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    n = 0
    for band, toks in games(path):                          # pass 1: plies 1..SPLIT
        n += 1
        for b in (band, "all"):
            for i in range(min(SPLIT, len(toks))):
                counts[b][" ".join(toks[:i])][toks[i]] += 1
    print(f"pass 1: {n} games")
    keep = {b: {p + (" " if p else "") + m for p, c in nodes.items() for m, k in c.items()
                if k >= MIN_GAMES and p.count(" ") + (1 if p else 0) == SPLIT - 1}
            for b, nodes in counts.items()}
    for band, toks in games(path):                          # pass 2: deeper, below popular nodes
        for b in (band, "all"):
            if len(toks) > SPLIT and " ".join(toks[:SPLIT]) in keep[b]:
                for i in range(SPLIT, len(toks)):
                    counts[b][" ".join(toks[:i])][toks[i]] += 1
    return counts, n


def to_tree(nodes: dict[str, Counter]) -> dict[str, dict[str, int]]:
    """Replay popular sequences from the start position; merge by fen4 (transpositions)."""
    tree: dict[str, dict[str, int]] = defaultdict(dict)
    stack = [("", chess.Board())]
    while stack:
        prefix, board = stack.pop()
        children = nodes.get(prefix)
        if not children or sum(children.values()) < MIN_GAMES:
            continue
        k = fen4(board)
        for san, n in children.items():
            if n < MIN_GAMES:
                continue
            try:
                mv = board.parse_san(san)
            except ValueError:
                continue
            tree[k][mv.uci()] = tree[k].get(mv.uci(), 0) + n
            nb = board.copy(stack=False)
            nb.push(mv)
            stack.append(((prefix + " " if prefix else "") + san, nb))
    return dict(tree)


def main() -> None:
    counts, n = count(download())
    bands = {b: to_tree(nodes) for b, nodes in sorted(counts.items())}
    out = {"source": URL, "license": "CC0-1.0 (Lichess database)", "games": n, "min_games": MIN_GAMES,
           "max_plies": MAX_PLIES, "bands": bands}
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    for b, t in bands.items():
        print(f"{b}: {len(t)} positions, {sum(t.get(fen4(chess.Board()), {}).values())} games at the root")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
