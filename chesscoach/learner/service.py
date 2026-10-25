"""Learner service (docs/06): runs the learning loop on top of the store.

Before a game: profile (created on first use from the rating the player gives), band, bot
strength, and the lesson focus from the weakness profile (06 §3, 05 §3).
After a game: Glicko-2 update against the bot's target Elo (06 §1), band hysteresis, bot offset
(05 §1), concept mastery (via GameSession.finish), and review cards (06 §4 step 6).
Drills: the daily queue (06 §5) and grading of an attempt (FSRS, drill mastery, drill rating).

Pure Python over `Store`, so the same code runs natively and in the browser (ADR 0002/0004).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

import chess

from chesscoach.learner.bands import BandTracker, band_for
from chesscoach.learner.glicko2 import Glicko, update
from chesscoach.learner.mastery import DRILL_WEIGHT, Opportunity
from chesscoach.learner.srs import FsrsScheduler, ReviewCard, daily_queue, grade
from chesscoach.learner.store import Store
from chesscoach.learner.weakness import GameRecord, MoveRecord, choose_lesson_focus, profile, worst_metric
from chesscoach.sparring.bot import OFFSET_START, bot_target, update_offset

BOT_RD = 50.0              # the bot's rating is its target Elo (06 §1): treated as well known
NEW_RD = 350.0
TACTIC_SHARPNESS = 0.6     # 06 §3 "tactics found"


@dataclass
class Profile:
    player_id: str
    game_rating: Glicko
    drill_rating: Glicko
    band: str
    bot_offset: float
    settings: dict = field(default_factory=dict)
    tracker: BandTracker = field(default_factory=BandTracker)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LearnerService:
    def __init__(self, store: Store, player_id: str = "local", clock: Callable[[], datetime] = _now):
        self.store, self.player_id, self.clock = store, player_id, clock

    # ------------------------------------------------------------------ profile
    def load(self) -> Optional[Profile]:
        d = self.store.load_profile(self.player_id)
        if d is None:
            return None
        bt = d.get("band_tracker") or {}
        return Profile(self.player_id, d["game_rating"], d["drill_rating"], d["band"], d["bot_offset"],
                       d["settings"], BandTracker(d["band"], bt.get("above", 0), bt.get("below", 0)))

    def save(self, p: Profile) -> None:
        p.band = p.tracker.band
        self.store.save_profile(p.player_id, p.game_rating, p.drill_rating, p.band, p.bot_offset, p.settings,
                                band_tracker={"above": p.tracker.above, "below": p.tracker.below})

    def ensure(self, rating: float) -> Profile:
        """The stored profile, or a new one seeded from the rating the player gave."""
        p = self.load()
        if p is None:
            band = band_for(rating)
            p = Profile(self.player_id, Glicko(float(rating), NEW_RD), Glicko(float(rating), NEW_RD), band,
                        OFFSET_START, {}, BandTracker(band))
            self.save(p)
        return p

    def bot_elo(self, p: Profile) -> int:
        return bot_target(p.game_rating.rating, p.bot_offset)

    # ------------------------------------------------------------------ weakness and lesson focus
    def game_records(self, registry, n: int = 50) -> list[GameRecord]:
        """GameRecords (06 §3) from the stored game log, player's moves only."""
        out = []
        for g in self.store.games(self.player_id, n):
            if g["result"] is None:
                continue
            moves = []
            for row in self.store.game_log(g["game_id"]):
                a = row["assessment"]
                if a.get("mover") != g["player_color"]:
                    continue
                roles: dict[str, list[str]] = {}
                sharp_available, found = False, False
                for h in row["hits"]:
                    c = registry.concepts.get(h["concept_id"])
                    if c is None:
                        continue
                    roles.setdefault(h["role"], []).append(c.category)
                    if h["role"] == "available" and c.category == "tactic" \
                            and (row.get("sharpness") or 0) >= TACTIC_SHARPNESS:
                        sharp_available = True
                        via = next((e.split("via:")[1] for e in h.get("evidence", []) if "via:" in e), None)
                        found = found or via == a["move"]
                moves.append(MoveRecord(ply=row["ply"], phase=row.get("phase") or "middlegame",
                                        win_before=a["win_prob_before"], win_after=a["win_prob_after"],
                                        move_class=a["move_class"], roles=roles,
                                        available_tactic_sharp=sharp_available, found_available=found))
            out.append(GameRecord(moves, g["result"]))
        return out

    def weakness(self, registry) -> dict:
        prof = profile(self.game_records(registry))
        return {"metrics": prof, "worst": worst_metric(prof)}

    def lesson_focus(self, registry, band: str) -> Optional[str]:
        prof = profile(self.game_records(registry))
        recent = {c for g in self.store.games(self.player_id, 2) for c in g["concepts_mentioned"]}
        return choose_lesson_focus(prof, registry, band, self.store.load_mastery(self.player_id), recent)

    # ------------------------------------------------------------------ after a game
    def finish_game(self, session, score: float, bot_elo: int, review=None) -> dict:
        """`session` is the finished GameSession (it logged its moves to this store); `score` the
        player's result; `review` an optional GameReview whose cards are saved."""
        p = self.load()
        mastery = self.store.load_mastery(self.player_id)
        before = {k: m.state for k, m in mastery.items()}
        session.finish(mastery, result=score)
        after = self.store.load_mastery(self.player_id)
        changes = [{"concept_id": k, "from": before.get(k, "new"), "to": m.state}
                   for k, m in sorted(after.items()) if before.get(k, "new") != m.state]
        old_rating, old_band = p.game_rating, p.band
        p.game_rating = update(p.game_rating, [(Glicko(float(bot_elo), BOT_RD), score)])
        p.tracker.after_game(p.game_rating.rating)
        scores = [g["result"] for g in reversed(self.store.games(self.player_id, 10)) if g["result"] is not None]
        p.bot_offset = update_offset(p.bot_offset, scores)
        self.save(p)
        cards = 0
        for c in (review.cards if review is not None else []):
            self.store.save_card(c)
            cards += 1
        return {"rating_before": round(old_rating.rating), "rating_after": round(p.game_rating.rating),
                "rd": round(p.game_rating.rd), "band_before": old_band, "band_after": p.band,
                "bot_offset": p.bot_offset, "next_bot_elo": self.bot_elo(p), "mastery_changes": changes,
                "cards_saved": cards}

    # ------------------------------------------------------------------ drills
    def queue(self, puzzles_for_focus: Callable[[int], list[ReviewCard]] = lambda n: []) -> list[ReviewCard]:
        cards = self.store.load_cards(self.player_id)
        recent_new = sorted((c for c in cards if c.is_new), key=lambda c: c.created_at, reverse=True)
        return daily_queue(cards, recent_new, puzzles_for_focus, now=self.clock())

    def card_counts(self) -> dict:
        cards = self.store.load_cards(self.player_id)
        now = self.clock()
        return {"total": len(cards), "new": sum(c.is_new for c in cards),
                "due": sum(1 for c in cards if not c.is_new and c.due <= now)}

    def record_drill(self, card: ReviewCard, solved: bool, max_hint_level: int, seconds_per_move: float,
                     puzzle_rating: Optional[float] = None) -> dict:
        """Grade one attempt (06 §5): FSRS review, mastery opportunities for the card's concepts
        (drill weights, 06 §2), and the drill rating against a rated puzzle (06 §1)."""
        now = self.clock()
        rating = grade(solved, max_hint_level, seconds_per_move)
        FsrsScheduler().review(card, rating, when=now)
        self.store.save_card(card)
        mastery = self.store.load_mastery(self.player_id)
        success = DRILL_WEIGHT.get(max_hint_level, 0.0) if solved else 0.0
        for cid in card.concept_ids:
            from chesscoach.learner.mastery import ConceptMastery
            m = mastery.setdefault(cid, ConceptMastery(self.player_id, cid))
            m.record(Opportunity(success=success, source="drill", hint_level=max_hint_level, at=now.isoformat()))
            self.store.save_mastery(m)
        p = self.load()
        if p is not None and puzzle_rating is not None:
            # Lichess's model: a failed puzzle is a win for the puzzle.
            p.drill_rating = update(p.drill_rating, [(Glicko(float(puzzle_rating), BOT_RD), 1.0 if solved else 0.0)])
            self.save(p)
        return {"grade": rating.name, "due": card.due.isoformat(),
                "drill_rating": round(p.drill_rating.rating) if p else None}

    # ------------------------------------------------------------------ summary for the client
    def summary(self, registry) -> dict:
        p = self.load()
        if p is None:
            return {"has_profile": False}
        mastery = self.store.load_mastery(self.player_id)
        games = self.store.games(self.player_id, 10)
        counts = {s: 0 for s in ("new", "learning", "practised", "mastered")}
        concepts = []
        for cid, m in sorted(mastery.items()):
            counts[m.state] += 1
            c = registry.concepts.get(cid)
            concepts.append({"id": cid, "title": c.title if c else cid, "state": m.state,
                             "opportunities": m.opportunities})
        w = self.weakness(registry)
        return {
            "has_profile": True, "rating": round(p.game_rating.rating), "rd": round(p.game_rating.rd),
            "band": p.band, "bot_elo": self.bot_elo(p), "drill_rating": round(p.drill_rating.rating),
            "games": len(self.store.games(self.player_id, 10000)),
            "recent_results": [g["result"] for g in games if g["result"] is not None],
            "mastery": {"counts": counts, "concepts": concepts},
            "weakness": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in w["metrics"].items()},
            "worst_metric": w["worst"], "lesson_focus": self.lesson_focus(registry, p.band),
            "cards": self.card_counts(),
        }


def card_dict(c: ReviewCard, registry=None) -> dict:
    d = asdict(c)
    d["due"] = c.due.isoformat()
    d["is_new"] = c.is_new
    d["side"] = "white" if chess.Board(c.fen).turn == chess.WHITE else "black"
    if registry is not None:
        d["concept_titles"] = [registry.concepts[i].title for i in c.concept_ids if i in registry.concepts]
    return d
