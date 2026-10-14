"""Spaced repetition (docs/06 §5): ReviewCard, FSRS scheduling (py-fsrs), Chessable-style
fallback, drill grading, daily queue."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Literal, Optional

import fsrs

CardKind = Literal["find_move", "avoid_mistake", "opening_line", "endgame_technique"]
DUE_CAP = 20
NEW_CAP = 5
FAST_S_PER_MOVE = 15


@dataclass
class ReviewCard:
    card_id: str
    player_id: str
    kind: CardKind
    fen: str
    solution: list[str]             # player's moves with expected replies interleaved (UCI)
    concept_ids: list[str]
    source: dict                    # {game_id?, ply?, puzzle_id?}
    srs: dict = field(default_factory=dict)   # FsrsState: fsrs.Card.to_dict(), stored as the library defines it
    created_at: str = ""

    @staticmethod
    def new(player_id: str, kind: CardKind, fen: str, solution: list[str], concept_ids: list[str],
            source: dict, now: Optional[datetime] = None) -> "ReviewCard":
        now = now or datetime.now(timezone.utc)
        return ReviewCard(card_id=uuid.uuid4().hex, player_id=player_id, kind=kind, fen=fen, solution=solution,
                          concept_ids=concept_ids, source=source,
                          srs=fsrs.Card(due=now).to_dict(), created_at=now.isoformat())

    @property
    def due(self) -> datetime:
        return fsrs.Card.from_dict(self.srs).due

    @property
    def is_new(self) -> bool:
        return self.srs.get("last_review") is None


def grade(solved: bool, max_hint_level: int, seconds_per_move: float) -> fsrs.Rating:
    """06 §5 grading table."""
    if not solved or max_hint_level >= 3:
        return fsrs.Rating.Again
    if max_hint_level >= 1:
        return fsrs.Rating.Hard
    if seconds_per_move < FAST_S_PER_MOVE:
        return fsrs.Rating.Easy
    return fsrs.Rating.Good


class FsrsScheduler:
    def __init__(self, fuzz: bool = True):
        self.scheduler = fsrs.Scheduler(enable_fuzzing=fuzz)

    def review(self, card: ReviewCard, rating: fsrs.Rating, when: Optional[datetime] = None) -> ReviewCard:
        c, _ = self.scheduler.review_card(fsrs.Card.from_dict(card.srs), rating, review_datetime=when)
        card.srs = c.to_dict()
        return card


class ChessableScheduler:
    """Fallback (06 §5): fixed levels 4h, 1d, 3d, 1w, 2w, 1m, 3m, 6m; a mistake resets to level 1.
    State kept in card.srs as {"level": n, "due": iso, "last_review": iso}."""
    LEVELS = [timedelta(hours=4), timedelta(days=1), timedelta(days=3), timedelta(weeks=1), timedelta(weeks=2),
              timedelta(days=30), timedelta(days=90), timedelta(days=180)]

    def review(self, card: ReviewCard, rating: fsrs.Rating, when: Optional[datetime] = None) -> ReviewCard:
        when = when or datetime.now(timezone.utc)
        level = card.srs.get("level", 0)
        level = 1 if rating == fsrs.Rating.Again else min(level + 1, len(self.LEVELS))
        card.srs = {**card.srs, "level": level, "due": (when + self.LEVELS[level - 1]).isoformat(),
                    "last_review": when.isoformat()}
        return card


def daily_queue(cards: Iterable[ReviewCard], recent_new: Iterable[ReviewCard],
                puzzles_for_focus: Callable[[int], list[ReviewCard]], now: Optional[datetime] = None,
                size: int = 30) -> list[ReviewCard]:
    """Due cards first (cap 20, most overdue first), then new cards from recent games (cap 5),
    then rating-matched puzzles tagged with the lesson focus."""
    now = now or datetime.now(timezone.utc)
    due = sorted((c for c in cards if not c.is_new and c.due <= now), key=lambda c: c.due)[:DUE_CAP]
    new = [c for c in recent_new if c.is_new][:NEW_CAP]
    q = due + new
    if len(q) < size:
        q += puzzles_for_focus(size - len(q))
    return q
