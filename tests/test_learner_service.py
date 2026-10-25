"""Learner service (docs/06): the learning loop over the store, engine-free."""
from __future__ import annotations

import sqlite3
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import chess
import pytest

from chesscoach.concepts.registry import Registry
from chesscoach.learner.mastery import ConceptMastery, Opportunity
from chesscoach.learner.service import LearnerService, card_dict
from chesscoach.learner.srs import ReviewCard
from chesscoach.learner.store import Store
from chesscoach.sparring.bot import OFFSET_START, OFFSET_STEP
from chesscoach.types import ConceptHit, Highlight, MoveAssessment

REG = Registry.load(allow_unreviewed=True)
T0 = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.t = T0

    def __call__(self):
        return self.t


class StubSession:
    """What finish_game needs from a GameSession: it logs moves to the store as it plays and
    saves the game (and mastery) in finish()."""
    n = 0

    def __init__(self, store: Store, color="white", log=(), concepts=()):
        StubSession.n += 1
        self.store, self.color, self.game_id = store, color, f"g{StubSession.n}"
        self.concepts = list(concepts)
        for ply, a, hits, phase, sharp in log:
            store.log_move(self.game_id, ply, asdict(a), [asdict(h) for h in hits], None, phase=phase, sharpness=sharp)

    def finish(self, mastery, result=None):
        for cid in self.concepts:
            m = mastery.setdefault(cid, ConceptMastery("local", cid))
            m.record(Opportunity(success=0.0, source="game"))
            self.store.save_mastery(m)
        self.store.save_game(self.game_id, "local", self.color, chess.STARTING_FEN, [], result, None, self.concepts)
        return mastery


def assess(ply, cls="good", before=0.5, after=0.5, mover="white", move="e2e4"):
    return MoveAssessment(move=move, mover=mover, win_prob_before=before, win_prob_after=after,
                          loss=max(0, before - after), move_class=cls, best_move=move, best_line=[move])


def hit(cid, role, evidence=()):
    return ConceptHit(concept_id=cid, role=role, importance=0.5, slots={}, highlight=Highlight(), evidence=list(evidence))


@pytest.fixture
def svc():
    return LearnerService(Store(), clock=Clock())


def test_profile_created_once_from_given_rating(svc):
    p = svc.ensure(1250)
    assert (round(p.game_rating.rating), p.band, p.bot_offset) == (1250, "B2", OFFSET_START)
    assert svc.ensure(900).game_rating.rating == 1250          # existing profile is kept
    assert svc.bot_elo(p) == 1250 + OFFSET_START


def test_finish_game_updates_rating_mastery_and_cards(svc):
    svc.ensure(1000)
    card = ReviewCard.new("local", "find_move", chess.STARTING_FEN, ["e2e4"], [], {"game_id": "x"}, now=T0)
    review = type("R", (), {"cards": [card]})()
    s = svc.finish_game(StubSession(svc.store, concepts=["tactic-fork-knight"]), 1.0, 1050, review)
    assert s["rating_after"] > s["rating_before"] == 1000
    assert s["cards_saved"] == 1 and svc.card_counts()["total"] == 1
    assert s["mastery_changes"] == [{"concept_id": "tactic-fork-knight", "from": "new", "to": "learning"}]
    assert svc.store.games("local", 5)[0]["result"] == 1.0
    lost = svc.finish_game(StubSession(svc.store), 0.0, 1050)
    assert lost["rating_after"] < s["rating_after"]


def test_bot_offset_follows_results(svc):
    svc.ensure(1000)
    for _ in range(5):
        out = svc.finish_game(StubSession(svc.store), 1.0, 1050)
    assert out["bot_offset"] == OFFSET_START + OFFSET_STEP     # 5 wins out of 5 → stronger bot


def test_band_counters_persist(svc):
    p = svc.ensure(1150)
    p.tracker.after_game(1300)
    p.tracker.after_game(1300)
    svc.save(p)
    q = svc.load()
    assert (q.band, q.tracker.above) == ("B1", 2)


def test_weakness_and_lesson_focus_from_the_logged_games(svc):
    """Blunders that allow a tactic make tactics_allowed the worst metric; the focus is then a
    tactic/safety/defence concept in the player's band."""
    svc.ensure(1000)
    log = [(i, assess(i), [], "middlegame", 0.2) for i in range(0, 40, 2)]
    log += [(41 + 2 * i, assess(41, "blunder", 0.5, 0.1), [hit("tactic-fork-knight", "allowed")], "middlegame", 0.3)
            for i in range(3)]
    svc.finish_game(StubSession(svc.store, log=log), 0.0, 1050)
    recs = svc.game_records(REG)
    assert len(recs) == 1 and len(recs[0].moves) == 23
    w = svc.weakness(REG)
    assert w["worst"] == "tactics_allowed" and w["metrics"]["tactics_allowed"] > 1.5
    focus = svc.lesson_focus(REG, "B1")
    assert focus and REG.get(focus).category in ("safety", "tactic", "defence") and "B1" in REG.get(focus).bands


def test_tactics_found_counts_sharp_available_hits(svc):
    svc.ensure(1000)
    log = [(0, assess(0, move="d5c7"), [hit("tactic-fork-knight", "available", ["via:d5c7"])], "middlegame", 0.9),
           (2, assess(2, move="a2a3"), [hit("tactic-fork-knight", "available", ["via:d5c7"])], "middlegame", 0.9),
           (4, assess(4, move="a2a3"), [hit("tactic-fork-knight", "available", ["via:d5c7"])], "middlegame", 0.1)]
    svc.finish_game(StubSession(svc.store, log=log), 1.0, 1050)
    assert svc.weakness(REG)["metrics"]["tactics_found"] == 0.5    # 1 of 2 sharp ones; the dull one excluded


def test_drill_queue_and_grading(svc):
    svc.ensure(1000)
    c = ReviewCard.new("local", "find_move", chess.STARTING_FEN, ["e2e4"], ["tactic-fork-knight"], {}, now=T0)
    svc.store.save_card(c)
    q = svc.queue()
    assert [x.card_id for x in q] == [c.card_id]
    out = svc.record_drill(q[0], solved=True, max_hint_level=0, seconds_per_move=5, puzzle_rating=1200)
    assert out["grade"] == "Easy" and out["drill_rating"] > 1000
    assert svc.card_counts() == {"total": 1, "new": 0, "due": 0}
    assert svc.store.load_mastery("local")["tactic-fork-knight"].opportunities == 1
    svc.clock.t = T0 + timedelta(days=400)
    assert svc.card_counts()["due"] == 1
    again = svc.record_drill(svc.queue()[0], solved=False, max_hint_level=3, seconds_per_move=60)
    assert again["grade"] == "Again"
    assert svc.store.load_mastery("local")["tactic-fork-knight"].history[-1].success == 0.0


def test_summary(svc):
    assert svc.summary(REG) == {"has_profile": False}
    svc.ensure(1000)
    s = svc.summary(REG)
    assert s["has_profile"] and s["rating"] == 1000 and s["cards"] == {"total": 0, "new": 0, "due": 0}
    d = card_dict(ReviewCard.new("local", "find_move", chess.STARTING_FEN, ["e2e4"], ["tactic-fork-knight"], {}), REG)
    assert d["side"] == "white" and d["concept_titles"] and d["is_new"]


def test_store_migrates_an_older_database(tmp_path):
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.executescript("""
      CREATE TABLE learner_profile (player_id TEXT PRIMARY KEY, game_rating TEXT NOT NULL, drill_rating TEXT NOT NULL,
        band TEXT NOT NULL, bot_offset REAL NOT NULL, settings TEXT NOT NULL, repertoire TEXT NOT NULL);
      CREATE TABLE game_log_move (game_id TEXT NOT NULL, ply INTEGER NOT NULL, assessment TEXT NOT NULL,
        hits TEXT NOT NULL, coach_event TEXT, bot_move TEXT, clock_ms INTEGER, PRIMARY KEY (game_id, ply));
      INSERT INTO learner_profile VALUES ('local', '{"rating": 1400, "rd": 80, "vol": 0.06}',
        '{"rating": 1400, "rd": 80, "vol": 0.06}', 'B2', 50, '{}', '{}');
    """)
    db.commit()
    db.close()
    svc = LearnerService(Store(str(path)))
    p = svc.load()
    assert p.game_rating.rating == 1400 and p.tracker.above == 0
    svc.store.log_move("g", 0, asdict(assess(0)), [], None, phase="opening", sharpness=0.4)
    assert svc.store.game_log("g")[0]["phase"] == "opening"
