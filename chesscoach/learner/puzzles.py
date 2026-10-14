"""Puzzle bank (docs/06 §6): import the Lichess puzzle database (CC0), map theme tags to concept
ids, re-tag with our detectors, and drop puzzles where our tags and Lichess's disagree on the
primary theme."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Optional

import chess
import yaml

from chesscoach.analysis.analyzer import move_features, static_features, static_opportunities
from chesscoach.analysis.phase import game_phase

THEME_MAP_FILE = Path(__file__).resolve().parent.parent.parent / "concepts" / "lichess_theme_map.yaml"

# Our feature id(s) that confirm each Lichess theme.
THEME_FEATURES = {
    "fork": {"fork", "double_attack"}, "doubleCheck": {"double_check"},
    "discoveredAttack": {"discovered_attack", "discovered_check"}, "pin": {"pin_absolute", "pin_relative"},
    "skewer": {"skewer"}, "backRankMate": {"back_rank_weakness"}, "trappedPiece": {"trapped_piece"},
    "hangingPiece": {"hanging_piece"}, "capturingDefender": {"removing_defender"},
    "overloading": {"overloaded_defender"},
}
FEATURE_CONCEPT = {"fork": None, "double_attack": "tactic-double-attack", "double_check": "tactic-double-check",
                   "discovered_attack": "tactic-discovered-attack", "discovered_check": "tactic-discovered-check",
                   "pin_absolute": "tactic-pin-absolute", "pin_relative": "tactic-pin-relative",
                   "skewer": "tactic-skewer", "back_rank_weakness": "tactic-back-rank-mate",
                   "trapped_piece": "tactic-trapped-piece", "hanging_piece": "safety-hanging-piece",
                   "removing_defender": "tactic-remove-defender", "overloaded_defender": "tactic-overloaded-defender"}
FORK_PIECE = {"knight": "tactic-fork-knight", "pawn": "tactic-fork-pawn", "queen": "tactic-fork-queen"}


@dataclass
class Puzzle:
    puzzle_id: str
    fen: str                     # position the player solves (after the opponent's lead-in move)
    solution: list[str]          # player's moves with replies interleaved
    rating: int
    themes: list[str]
    lead_in: str                 # opponent's move from the Lichess FEN
    concept_ids: list[str] = field(default_factory=list)


def load_theme_map(path: Path = THEME_MAP_FILE) -> dict[str, list[str]]:
    return yaml.safe_load(path.read_text())


def read_lichess_csv(path: str | Path) -> Iterator[Puzzle]:
    """lichess_db_puzzle.csv columns: PuzzleId,FEN,Moves,Rating,RatingDeviation,Popularity,NbPlays,
    Themes,GameUrl,OpeningTags. FEN is before the opponent's move; Moves[0] is that move."""
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            moves = row["Moves"].split()
            b = chess.Board(row["FEN"])
            b.push_uci(moves[0])
            yield Puzzle(row["PuzzleId"], b.fen(), moves[1:], int(row["Rating"]), row["Themes"].split(), moves[0])


def our_features(p: Puzzle) -> list:
    """Features the first solution move creates (move-based + static tactics it sets up), plus
    static tactics already on the board for the solver."""
    b = chess.Board(p.fen)
    phase = game_phase(b)
    first = chess.Move.from_uci(p.solution[0])
    pv = [chess.Move.from_uci(m) for m in p.solution[1:]]
    solver = "white" if b.turn == chess.WHITE else "black"
    feats = move_features(b, first, pv, None, phase, tag="via")
    feats += static_opportunities(b, first, feats, phase)
    feats += [f for f in static_features(b, phase) if f.side == solver]
    return [f for f in feats if f.side == solver]


def retag(p: Puzzle, theme_map: dict[str, list[str]]) -> Optional[Puzzle]:
    """Primary theme = the first mapped Lichess theme. Keep the puzzle only if our detectors
    confirm it; concept ids come from our features (fork refined by piece)."""
    mapped = [t for t in p.themes if t in theme_map]
    if not mapped:
        return None
    primary = mapped[0]
    feats = our_features(p)
    confirming = [f for f in feats if f.id in THEME_FEATURES[primary]]
    if not confirming:
        return None
    ids = []
    for f in confirming:
        cid = FORK_PIECE.get(f.data.get("piece")) if f.id == "fork" else FEATURE_CONCEPT.get(f.id)
        if cid and cid in theme_map[primary] and cid not in ids:
            ids.append(cid)
    if not ids:
        return None
    p.concept_ids = ids
    return p


def build_bank(puzzles: Iterable[Puzzle], theme_map: Optional[dict] = None) -> list[Puzzle]:
    theme_map = theme_map or load_theme_map()
    return [q for p in puzzles if (q := retag(p, theme_map)) is not None]
