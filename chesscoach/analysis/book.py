"""Opening book lookups for `book` classification (02 §3) and the opening phase (02 §5).

Doc 02 leaves the data source open. Two implementations:
- TreeBook: counts per (fen4, uci move), e.g. built from the Lichess games database filtered by
  rating band (05 §2). A move is "book" when its game count >= min_games.
- PolyglotBook: a Polyglot .bin file via python-chess.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Optional, Protocol

import chess
import chess.polyglot

from chesscoach.analysis.engine import fen4

MIN_GAMES = 50   # same cut-off as leaving the opening tree in 05 §2


class OpeningBook(Protocol):
    def has_position(self, board: chess.Board) -> bool: ...
    def has_move(self, board: chess.Board, move: chess.Move) -> bool: ...
    def moves(self, board: chess.Board) -> dict[str, int]: ...


class TreeBook:
    def __init__(self, counts: Optional[dict[str, dict[str, int]]] = None, min_games: int = MIN_GAMES):
        self.counts: dict[str, dict[str, int]] = defaultdict(dict, counts or {})
        self.min_games = min_games

    @classmethod
    def from_games(cls, games: list[list[str]], max_plies: int = 24, min_games: int = MIN_GAMES) -> "TreeBook":
        """`games`: lists of UCI moves from the start position."""
        tb = cls(min_games=min_games)
        for moves in games:
            b = chess.Board()
            for uci in moves[:max_plies]:
                k = fen4(b)
                tb.counts[k][uci] = tb.counts[k].get(uci, 0) + 1
                b.push_uci(uci)
        return tb

    @classmethod
    def load(cls, path: str | Path, min_games: int = MIN_GAMES) -> "TreeBook":
        return cls(json.loads(Path(path).read_text()), min_games)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.counts))

    def moves(self, board: chess.Board) -> dict[str, int]:
        return {m: n for m, n in self.counts.get(fen4(board), {}).items() if n >= self.min_games}

    def has_position(self, board: chess.Board) -> bool:
        return sum(self.counts.get(fen4(board), {}).values()) >= self.min_games

    def has_move(self, board: chess.Board, move: chess.Move) -> bool:
        return self.counts.get(fen4(board), {}).get(move.uci(), 0) >= self.min_games


class PolyglotBook:
    def __init__(self, path: str | Path):
        self.reader = chess.polyglot.open_reader(path)

    def moves(self, board: chess.Board) -> dict[str, int]:
        return {e.move.uci(): e.weight for e in self.reader.find_all(board)}

    def has_position(self, board: chess.Board) -> bool:
        return bool(self.moves(board))

    def has_move(self, board: chess.Board, move: chess.Move) -> bool:
        return move.uci() in self.moves(board)
