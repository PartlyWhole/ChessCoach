"""Drill attempts (docs/06 §5) with Stockfish deciding alternative moves."""
from __future__ import annotations

import shutil

import chess
import pytest

from chesscoach.learner.drill import MAX_WRONG, DrillAttempt
from chesscoach.learner.srs import ReviewCard

pytestmark = pytest.mark.skipif(shutil.which("stockfish") is None, reason="stockfish missing")

# White to move: Nc7+ forks king and rook (from tests/positions/detectors/fork.yaml); the solution
# is Nc7+ Kd8 Nxa8.
FORK = "r3k2r/pp3ppp/8/3N4/8/8/PPP2PPP/R3K2R w KQkq - 0 1"
SOLUTION = ["d5c7", "e8d8", "c7a8"]


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def engine(pool):
    return lambda b: pool.analyse(b, depth=14)


def card(fen=FORK, solution=SOLUTION, concepts=()):
    return ReviewCard.new("local", "find_move", fen, list(solution), list(concepts), {})


def test_solve_with_expected_reply(engine):
    d = DrillAttempt(card(), engine, clock=Clock())
    s = d.move("d5c7")
    assert s["result"] == "correct" and s["reply_san"] == "Kd8" and not s["done"]
    s = d.move("c7a8")
    assert s["done"] and s["solved"] and d.max_hint_level() == 0 and d.played == ["Nc7+", "Kd8", "Nxa8"]


def test_alternatives_engine_best_or_mate_only(engine):
    """White is already winning here, so 2.a3 keeps a high win probability, but it is not the
    move to find: refused. Mate is always accepted; so is the engine's own best move when the
    stored solution differs."""
    d = DrillAttempt(card(), engine, clock=Clock())
    s = d.move("a2a3")
    assert s["result"] == "wrong" and s["tries_left"] == MAX_WRONG
    mate = DrillAttempt(card("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1", ["d1d7"]), engine, clock=Clock())
    s = mate.move("d1d8")
    assert s["solved"] and s["result"] == "alternative"
    stale = DrillAttempt(card(solution=["a2a3"]), engine, clock=Clock())   # a bad stored solution
    best = engine(chess.Board(FORK)).lines[0].moves[0]
    assert stale.move(best)["result"] == "alternative"


def test_wrong_tries_then_reveal(engine):
    d = DrillAttempt(card(), engine, clock=Clock())
    for _ in range(MAX_WRONG):
        assert d.move("a2a3")["result"] == "wrong"
    s = d.move("a2a3")
    assert s["done"] and not s["solved"] and s["solution_san"] == ["Nc7+", "Kd8", "Nxa8"]
    assert d.max_hint_level() == 3


def test_solve_after_a_wrong_try_counts_as_hint(engine):
    d = DrillAttempt(card(), engine, clock=Clock())
    d.move("a2a3")
    d.move("d5c7")
    d.move("c7a8")
    assert d.solved and d.max_hint_level() == 1


def test_hint_ladder_uses_solution_facts_and_optional_text(engine):
    texts = []
    d = DrillAttempt(card(concepts=["tactic-fork-knight"]), engine, clock=Clock(),
                     hint_text=lambda b, ids, lv: texts.append((ids, lv)) or (f"text {lv}" if lv == 2 else None))
    h1 = d.hint()["hint"]
    assert h1 == {"level": 1, "piece": "knight"}
    h2 = d.hint()["hint"]
    assert h2 == {"level": 2, "piece": "knight", "square": "d5", "text": "text 2"}
    s = d.hint()
    assert s["done"] and not s["solved"] and s["hint"] == {"level": 3, "move": "d5c7"}
    assert texts == [(["tactic-fork-knight"], 1), (["tactic-fork-knight"], 2)]


def test_illegal_move_is_ignored(engine):
    d = DrillAttempt(card(), engine, clock=Clock())
    assert d.move("a1a8")["result"] == "illegal" and d.wrong == 0
