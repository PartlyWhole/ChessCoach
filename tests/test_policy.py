"""Coaching policy (docs/04) — decision procedure, budget, hint ladder, fallback, modes."""
import chess
import pytest

from chesscoach.concepts.registry import Registry
from chesscoach.policy.policy import (CoachingPolicy, CoachSessionState, CoachSettings, LearnerView,
                                      is_fast_time_control, load_fallback)
from chesscoach.types import ConceptHit, EngineLine, EngineResult, Highlight, MoveAssessment

REG = Registry.load(allow_unreviewed=True)
FALLBACK = load_fallback(allow_unreviewed=True)
BOARD = chess.Board("r3kbnr/ppp2ppp/8/1N1q4/8/8/PPPP1PPP/R1BQKB1R w KQkq - 0 8")


def hit(cid="tactic-fork-knight", role="missed", imp=0.8, slots=None):
    slots = slots if slots is not None else {"square": "c7", "targets": "king and rook", "move_san": "Nc7+",
                                             "best_san": "Nc7+", "user_color": "White", "other_color": "Black"}
    return ConceptHit(cid, role, imp, slots, Highlight(["c7", "a8"], [("b5", "c7")]), ["fork@c7"])


def assess(cls="mistake", move="h2h3", loss=0.12):
    return MoveAssessment(move=move, mover="white", win_prob_before=0.8, win_prob_after=0.8 - loss, loss=loss,
                          move_class=cls, best_move="b5c7", best_line=["b5c7", "e8d8", "c7d5"])


def eng_after():
    return EngineResult(fen="", lines=[EngineLine(["d5d2"], cp=-100, mate=None, win_prob=0.36, depth=16)], sharpness=0)


def policy(**kw):
    learner = kw.pop("learner", LearnerView(band="B1", mastery={"tactic-fork-knight": "learning"}))
    return CoachingPolicy(REG, CoachSettings(**kw), learner, fallback=FALLBACK)


def state():
    return CoachSessionState(game_id="g1")


def test_silent_mode_only_queues():
    out = policy(mode="silent").after_player_move(state(), 15, assess("blunder", loss=0.3), [hit()], BOARD, eng_after())
    assert out.event is None and [q.kind for q in out.queued] == ["queued_for_review"]


def test_blunder_interrupt_level1_with_takeback():
    st = state()
    out = policy().after_player_move(st, 15, assess("blunder", loss=0.3), [hit()], BOARD, eng_after())
    assert out.event.kind == "interrupt" and out.event.hint_level == 1 and out.event.allow_takeback
    assert "Nc7" not in out.event.text            # level 1 never names the move
    assert out.event.highlight.squares == []      # nor points at squares
    assert st.concepts_mentioned == ["tactic-fork-knight"]


def test_blunder_without_hits_uses_threat_fallback():
    out = policy().after_player_move(state(), 15, assess("blunder", loss=0.3), [], BOARD, eng_after())
    assert out.event.kind == "interrupt" and out.event.concept_id is None
    assert out.event.text == FALLBACK["threat"][1]


def test_quiet_inaccuracy_without_hits_stays_silent():
    out = policy().after_player_move(state(), 15, assess("inaccuracy", loss=0.06), [], BOARD, eng_after())
    assert out.event is None


def test_comment_above_threshold():
    out = policy().after_player_move(state(), 15, assess("mistake"), [hit(imp=0.5)], BOARD, eng_after())
    assert out.event.kind == "comment" and out.event.hint_level == 1


def test_below_threshold_queues():
    out = policy().after_player_move(state(), 15, assess("good", loss=0.03), [hit(imp=0.5)], BOARD, eng_after())
    assert out.event is None and len(out.queued) == 1


def test_budget_exhausted_queues():
    st = state()
    st.player_move_plies = list(range(1, 20, 2))
    st.comment_ply_history = [13, 15, 17]
    out = policy().after_player_move(st, 21, assess("mistake"), [hit()], BOARD, eng_after())
    assert out.event is None and out.queued


def test_low_verbosity_budget_is_two():
    st = state()
    st.player_move_plies = list(range(1, 20, 2))
    st.comment_ply_history = [15, 17]
    out = policy(verbosity="low").after_player_move(st, 21, assess("mistake"), [hit()], BOARD, eng_after())
    assert out.event is None


def test_novelty_zero_when_said_this_game():
    st = state()
    st.concepts_mentioned = ["tactic-fork-knight"]
    out = policy().after_player_move(st, 15, assess("mistake"), [hit()], BOARD, eng_after())
    assert out.event is None or out.event.concept_id != "tactic-fork-knight"


def test_band_fit_two_above_dropped():
    p = policy(learner=LearnerView(band="B0"))
    assert p.band_fit("tactic-remove-defender") == 0.0      # B2 concept for a B0 player
    assert p.band_fit("tactic-fork-knight") == 0.5          # one band above
    assert p.band_fit("safety-hanging-piece") == 1.0


def test_start_level_2_for_new_concept_beginner():
    p = policy(learner=LearnerView(band="B1", mastery={}))
    out = p.after_player_move(state(), 15, assess("mistake"), [hit()], BOARD, eng_after())
    assert out.event.hint_level == 2 and "c7" in out.event.text


def test_hint_ladder_advances_to_answer():
    st = state()
    p = policy()
    p.after_player_move(st, 15, assess("mistake"), [hit()], BOARD, eng_after())
    e2 = p.request_hint(st, 15)
    e3 = p.request_hint(st, 15)
    assert (e2.hint_level, e3.hint_level) == (2, 3)
    assert "Nc7+" in e3.text and e3.highlight.arrows == [("b5", "c7")]
    assert p.request_hint(st, 15) is None
    assert [h["level"] for h in st.hints_requested] == [2, 3]


def test_two_failed_retries_reveal_level3():
    st = state()
    p = policy()
    p.after_player_move(st, 15, assess("blunder", loss=0.3), [hit()], BOARD, eng_after())
    p.on_takeback(st)
    assert p.after_retry(st, 15, assess("mistake")) is None
    ev = p.after_retry(st, 15, assess("blunder", loss=0.3))
    assert ev.hint_level == 3 and "Nc7+" in ev.text


def test_good_retry_closes_hint():
    st = state()
    p = policy()
    p.after_player_move(st, 15, assess("blunder", loss=0.3), [hit()], BOARD, eng_after())
    assert p.after_retry(st, 15, assess("best", move="b5c7", loss=0.0)) is None
    assert st.active_hint is None


def test_praise_once_per_game():
    st = state()
    p = policy()
    ph = hit(role="played", imp=0.9)
    a = assess("best", move="b5c7", loss=0.0)
    first = p.after_player_move(st, 15, a, [ph], BOARD, eng_after())
    assert first.event.kind == "praise" and first.event.hint_level == 0
    st.concepts_mentioned.clear()
    second = p.after_player_move(st, 17, a, [ph], BOARD, eng_after())
    assert second.event is None


def test_no_praise_for_forced_or_recapture():
    p = policy()
    ph = hit(role="played", imp=0.9)
    out = p.after_player_move(state(), 15, assess("forced", move="b5c7", loss=0.0), [ph], BOARD, eng_after())
    assert out.event is None
    b = chess.Board("4k3/8/8/3p4/4P3/8/8/4K3 w - - 0 1")
    out = p.after_player_move(state(), 15, assess("best", move="e4d5", loss=0.0), [ph], b, eng_after(),
                              last_opponent_move=chess.Move.from_uci("e6d5"))
    assert out.event is None


def test_fast_time_control_forces_silent():
    assert is_fast_time_control(180, 2) and not is_fast_time_control(600, 0) and not is_fast_time_control(None)
    p = CoachingPolicy(REG, CoachSettings(mode="guided"), LearnerView(), time_control=(300, 3), fallback=FALLBACK)
    assert p.settings.mode == "silent"


def test_pre_move_prompt_guided_only_and_spaced():
    sharp = EngineResult(fen="", lines=[], sharpness=0.9)
    avail = [hit(role="available")]
    st = state()
    assert policy().pre_move_prompt(st, 15, sharp, avail) is None             # standard mode
    g = policy(mode="guided")
    assert g.pre_move_prompt(st, 15, sharp, avail).text == FALLBACK["pre_move"][1]
    st.player_move_plies += [15, 17]
    assert g.pre_move_prompt(st, 19, sharp, avail) is None                     # within 5 moves
    assert g.pre_move_prompt(state(), 15, EngineResult("", [], 0.5), avail) is None


def test_unreviewed_text_blocked_by_default(monkeypatch):
    monkeypatch.delenv("CHESSCOACH_ALLOW_UNREVIEWED", raising=False)
    assert load_fallback() == {}
    assert len(Registry.load()) == 0
