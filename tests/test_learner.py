"""Learner model, review and SRS (docs/06)."""
from datetime import datetime, timedelta, timezone

import fsrs
import pytest

from chesscoach.concepts.registry import Registry
from chesscoach.learner.accuracy import game_accuracy, move_accuracy
from chesscoach.learner.bands import BandTracker, band_for
from chesscoach.learner.glicko2 import Glicko, expected, update, update_pair
from chesscoach.learner.mastery import ConceptMastery, Opportunity, game_success
from chesscoach.learner.srs import ChessableScheduler, FsrsScheduler, ReviewCard, daily_queue, grade
from chesscoach.learner.store import Store
from chesscoach.learner.weakness import GameRecord, MoveRecord, choose_lesson_focus, profile, worst_metric


# ---------- Glicko-2 ----------
def test_glickman_paper_example():
    """Glickman (2013) worked example: 1500/200/0.06 vs 1400/30 (W), 1550/100 (L), 1700/300 (L)."""
    p = update(Glicko(1500, 200, 0.06), [(Glicko(1400, 30), 1), (Glicko(1550, 100), 0), (Glicko(1700, 300), 0)])
    assert p.rating == pytest.approx(1464.06, abs=0.05)
    assert p.rd == pytest.approx(151.52, abs=0.05)
    assert p.vol == pytest.approx(0.05999, abs=1e-5)


def test_no_games_increases_rd():
    assert update(Glicko(1500, 50, 0.06), []).rd > 50


def test_failed_drill_is_win_for_drill():
    player, drill = update_pair(Glicko(1500, 100), Glicko(1500, 100), 0.0)
    assert player.rating < 1500 < drill.rating
    assert expected(Glicko(1700, 50), Glicko(1500, 50)) > 0.7


# ---------- bands ----------
def test_band_thresholds():
    assert [band_for(r) for r in (500, 800, 1199, 1200, 1650, 2100)] == ["B0", "B1", "B1", "B2", "B3", "B4"]


def test_band_hysteresis():
    t = BandTracker("B1")
    for _ in range(4):
        assert t.after_game(1250) == "B1"
    assert t.after_game(1250) == "B2"
    for _ in range(9):
        assert t.after_game(1150) == "B2"
    assert t.after_game(1150) == "B1"
    t2 = BandTracker("B1")
    for r in (1250, 1250, 1100, 1250, 1250, 1250, 1250):
        t2.after_game(r)
    assert t2.band == "B1"                 # streak broken → needs 5 consecutive


# ---------- mastery ----------
def m():
    return ConceptMastery("p", "tactic-fork-knight")


def test_mastery_transitions():
    x = m()
    x.record(Opportunity(0.0, "game"))
    assert x.state == "learning"
    for _ in range(7):
        x.record(Opportunity(1.0, "drill"))
    assert x.state == "practised"                      # 7/8 = 87.5% ≥ 60%
    for _ in range(12):
        x.record(Opportunity(1.0, "drill"))
    assert x.state == "practised"                      # needs 2 real-game successes
    x.record(Opportunity(1.0, "game"))
    x.record(Opportunity(1.0, "game"))
    assert x.state == "mastered"
    for _ in range(3):
        x.record(Opportunity(0.0, "game"))
    assert x.state == "learning"                       # 3 failures in last 5


def test_game_success_rules():
    assert game_success("played") == 1.0
    assert game_success("available", 0) == 1.0 and game_success("available", 1) == 0.6
    assert game_success("missed") == 0.0 and game_success("allowed", threat_parried=True) == 1.0
    assert game_success("plan") is None


# ---------- accuracy ----------
def test_move_accuracy_lichess_curve():
    assert move_accuracy(0.6, 0.6) == 100.0
    assert move_accuracy(0.6, 0.5) == pytest.approx(103.1668100711649 * 2.718281828 ** (-0.4354415386753951) - 3.166924740191411 + 1, abs=1e-6)
    assert move_accuracy(0.9, 0.1) < 5
    assert game_accuracy([], []) is None
    assert 90 < game_accuracy([0.5] * 10, [0.49] * 10) <= 100


# ---------- weakness profile & lesson focus ----------
def test_profile_and_focus():
    REG = Registry.load(allow_unreviewed=True)
    moves = [MoveRecord(ply=i, phase="middlegame", win_before=0.5, win_after=0.5, move_class="good") for i in range(30, 60, 2)]
    moves += [MoveRecord(ply=40, phase="middlegame", win_before=0.5, win_after=0.2, move_class="blunder",
                         roles={"allowed": ["tactic"]}) for _ in range(3)]
    moves += [MoveRecord(ply=20, phase="middlegame", win_before=0.5, win_after=0.5, move_class="good",
                         available_tactic_sharp=True, found_available=False) for _ in range(4)]
    prof = profile([GameRecord(moves, 0.0)])
    assert prof["tactics_found"] == 0.0
    assert worst_metric(prof) in ("tactics_found", "tactics_allowed")
    focus = choose_lesson_focus(prof, REG, "B1", {}, recent_two_games={"tactic-double-attack"})
    assert focus is not None and REG.get(focus).category in ("tactic", "safety", "defence")
    assert focus != "tactic-double-attack"


# ---------- SRS ----------
def test_grading_table():
    assert grade(True, 0, 10) == fsrs.Rating.Easy
    assert grade(True, 0, 40) == fsrs.Rating.Good
    assert grade(True, 2, 10) == fsrs.Rating.Hard
    assert grade(True, 3, 10) == fsrs.Rating.Again and grade(False, 0, 5) == fsrs.Rating.Again


def test_fsrs_schedules_and_roundtrips():
    now = datetime(2026, 10, 13, tzinfo=timezone.utc)
    c = ReviewCard.new("p", "find_move", "8/8/8/8/8/8/8/K6k w - - 0 1", ["a1a2"], [], {}, now)
    assert c.is_new
    s = FsrsScheduler(fuzz=False)
    s.review(c, fsrs.Rating.Good, now)
    assert not c.is_new and c.due > now
    due_good = c.due
    c2 = ReviewCard.new("p", "find_move", c.fen, c.solution, [], {}, now)
    s.review(c2, fsrs.Rating.Again, now)
    assert c2.due <= due_good


def test_chessable_fallback_levels():
    now = datetime(2026, 10, 13, tzinfo=timezone.utc)
    c = ReviewCard.new("p", "opening_line", "8/8/8/8/8/8/8/K6k w - - 0 1", [], [], {}, now)
    s = ChessableScheduler()
    s.review(c, fsrs.Rating.Good, now)
    assert c.srs["level"] == 1 and c.srs["due"] == (now + timedelta(hours=4)).isoformat()
    s.review(c, fsrs.Rating.Good, now)
    assert c.srs["level"] == 2
    s.review(c, fsrs.Rating.Again, now)
    assert c.srs["level"] == 1


def test_daily_queue_order_and_caps():
    now = datetime(2026, 10, 13, tzinfo=timezone.utc)
    s = FsrsScheduler(fuzz=False)
    old = []
    for i in range(25):
        c = ReviewCard.new("p", "find_move", "8/8/8/8/8/8/8/K6k w - - 0 1", [], [], {"i": i}, now - timedelta(days=60))
        s.review(c, fsrs.Rating.Again, now - timedelta(days=60 - i))
        old.append(c)
    new = [ReviewCard.new("p", "find_move", "8/8/8/8/8/8/8/K6k w - - 0 1", [], [], {"new": i}, now) for i in range(8)]
    q = daily_queue(old, new, lambda n: [], now=now)
    assert len(q) == 25 and all(not c.is_new for c in q[:20]) and all(c.is_new for c in q[20:])
    assert [c.due for c in q[:20]] == sorted(c.due for c in q[:20])


# ---------- store ----------
def test_store_roundtrip():
    st = Store()
    st.save_profile("p", Glicko(1300, 80), Glicko(1400, 90), "B2", 50, {"mode": "standard"})
    prof = st.load_profile("p")
    assert prof["band"] == "B2" and prof["game_rating"].rating == 1300
    x = m()
    x.record(Opportunity(1.0, "game", at="2026-10-13"))
    st.save_mastery(x)
    assert st.load_mastery("p")["tactic-fork-knight"].history[0].success == 1.0
    c = ReviewCard.new("p", "find_move", "8/8/8/8/8/8/8/K6k w - - 0 1", ["a1a2"], ["safety-hanging-piece"], {"game_id": "g"})
    st.save_card(c)
    assert st.load_cards("p")[0].solution == ["a1a2"]
