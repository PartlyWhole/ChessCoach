"""Opening selection (docs/05 §2).

- Repertoire / forced lines: the bot follows a named line move by move while the game matches it.
- Opening tree: weighted by frequency at the player's band (TreeBook from 02's book module);
  leave the tree when the node's game count drops below 50.
- Lesson structure → openings table. A chess expert must own and review this table (05); the
  lines below are a draft (review status recorded in LESSON_LINES_REVIEW).
"""
from __future__ import annotations

import random
from typing import Optional

import chess

from chesscoach.analysis.book import TreeBook

LESSON_LINES_REVIEW = {"status": "draft", "note": "needs chess-expert review (05 §2)"}

# structure_id → {"white": [lines], "black": [lines]}; a line is a list of UCI moves from the start.
LESSON_LINES: dict[str, dict[str, list[list[str]]]] = {
    "iqp": {
        # QGD Tarrasch: 1.d4 d5 2.c4 e6 3.Nc3 c5 4.cxd5 exd5 — Black gets the IQP after dxc5/…
        "white": [["d2d4", "d7d5", "c2c4", "e7e6", "b1c3", "c7c5", "c4d5", "e6d5"],
                  # Caro-Kann Panov: 1.e4 c6 2.d4 d5 3.exd5 cxd5 4.c4
                  ["e2e4", "c7c6", "d2d4", "d7d5", "e4d5", "c6d5", "c2c4"]],
        "black": [["d2d4", "d7d5", "c2c4", "e7e6", "b1c3", "c7c5"],          # Tarrasch Defence
                  ["d2d4", "d7d5", "c2c4", "e7e6", "b1c3", "g8f6", "g1f3", "c7c5"]],  # Semi-Tarrasch
    },
    "carlsbad": {
        "white": [["d2d4", "d7d5", "c2c4", "e7e6", "b1c3", "g8f6", "c4d5", "e6d5"]],   # QGD Exchange
        "black": [["d2d4", "d7d5", "c2c4", "e7e6", "b1c3", "g8f6", "c4d5", "e6d5"]],
    },
    "french_advance": {
        "white": [["e2e4", "e7e6", "d2d4", "d7d5", "e4e5"]],
        "black": [["e2e4", "e7e6"]],
    },
    "kings_indian_closed": {
        "white": [["d2d4", "g8f6", "c2c4", "g7g6", "b1c3", "f8g7", "e2e4", "d7d6", "g1f3", "e8g8",
                   "f1e2", "e7e5", "e1g1", "b8c6", "d4d5"]],
        "black": [["d2d4", "g8f6", "c2c4", "g7g6", "b1c3", "f8g7", "e2e4", "d7d6"]],
    },
    "maroczy_bind": {
        "white": [["e2e4", "c7c5", "g1f3", "b8c6", "d2d4", "c5d4", "f3d4", "g7g6", "c2c4"]],
        "black": [["e2e4", "c7c5", "g1f3", "b8c6", "d2d4", "c5d4", "f3d4", "g7g6"]],
    },
}


def line_move(lines: list[list[str]], played: list[str], rng: random.Random) -> Optional[str]:
    """Next move of a line whose prefix equals the game so far (random among matching lines)."""
    n = len(played)
    nxt = [ln[n] for ln in lines if len(ln) > n and ln[:n] == played]
    return rng.choice(nxt) if nxt else None


def lesson_line_move(structure_id: Optional[str], bot_color: str, played: list[str],
                     rng: random.Random) -> Optional[str]:
    if not structure_id or structure_id not in LESSON_LINES:
        return None
    return line_move(LESSON_LINES[structure_id].get(bot_color, []), played, rng)


def tree_move(tree: TreeBook, board: chess.Board, rng: random.Random) -> Optional[str]:
    """Frequency-weighted move from the band's opening tree; None once the node has < 50 games."""
    moves = tree.moves(board)            # already filtered to >= min_games per move
    if not moves or not tree.has_position(board):
        return None
    total = sum(moves.values())
    r = rng.uniform(0, total)
    acc = 0.0
    for m, n in sorted(moves.items()):
        acc += n
        if r <= acc:
            return m
    return max(moves, key=moves.get)
