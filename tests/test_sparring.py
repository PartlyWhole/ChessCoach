"""Sparring partner (docs/05): sampling, sanity guard, steering rules, calibration, openings."""
import random
import shutil

import chess
import pytest

from chesscoach.sparring.bot import (BotConfig, SparringBot, allows_mate_in_one, bot_target, hangs_queen,
                                     sample, think_time, update_offset)
from chesscoach.sparring.openings import LESSON_LINES, lesson_line_move, line_move
from chesscoach.sparring.steering import structure_similarity


class FixedModel:
    name = "fixed"

    def __init__(self, probs):
        self.probs = probs

    def move_probs(self, board, elo_self, elo_oppo):
        return {m: p for m, p in self.probs.items() if board.is_legal(chess.Move.from_uci(m))}


def test_sample_drops_rare_moves_and_is_seedable():
    probs = {"a": 0.97, "b": 0.019, "c": 0.011}
    rng = random.Random(1)
    assert {sample(probs, 1.0, rng) for _ in range(300)} == {"a"}
    assert sample({"x": 0.5, "y": 0.5}, 1.0, random.Random(7)) == sample({"x": 0.5, "y": 0.5}, 1.0, random.Random(7))


def test_temperature_sharpens():
    probs = {"a": 0.6, "b": 0.4}
    rng = random.Random(3)
    cold = sum(sample(probs, 0.3, rng) == "a" for _ in range(2000)) / 2000
    warm = sum(sample(probs, 1.0, rng) == "a" for _ in range(2000)) / 2000
    assert cold > warm > 0.5


def test_hangs_queen_and_mate_in_one():
    b = chess.Board("4k3/8/8/3p4/8/8/8/3QK3 w - - 0 1")
    assert hangs_queen(b, chess.Move.from_uci("d1d4")) is False      # Qd4 is safe? d5 pawn attacks c4/e4 only
    b2 = chess.Board("4k3/8/8/8/2p5/8/8/3QK3 w - - 0 1")
    assert hangs_queen(b2, chess.Move.from_uci("d1d3"))             # c4xd3
    back = chess.Board("6k1/5ppp/8/8/8/8/r4PPP/3R2K1 w - - 0 1")
    assert allows_mate_in_one(back, chess.Move.from_uci("d1d7")) is False
    weak = chess.Board("3r2k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1")
    assert allows_mate_in_one(weak, chess.Move.from_uci("a1a7"))    # ...Rd1#


def test_guard_rejects_queen_hang_above_1200_only():
    b = chess.Board("4k3/8/8/8/2p5/8/8/3QK3 w - - 0 1")
    model = FixedModel({"d1d3": 0.9, "d1d2": 0.1})
    strong = SparringBot(model, None, BotConfig(bot_elo=1400, player_elo=1400), random.Random(0))
    picks = {strong.choose(b).move for _ in range(30)}
    assert "d1d3" not in picks and picks <= {"d1d2"}
    weak = SparringBot(model, None, BotConfig(bot_elo=900, player_elo=900), random.Random(0))
    assert "d1d3" in {weak.choose(b).move for _ in range(30)}


def test_all_samples_absurd_falls_back_to_top_move():
    b = chess.Board("4k3/8/8/8/2p5/8/8/3QK3 w - - 0 1")
    bot = SparringBot(FixedModel({"d1d3": 1.0}), None, BotConfig(bot_elo=1500, player_elo=1500), random.Random(0))
    bm = bot.choose(b)
    assert bm.move == "d1d3" and bm.source == "engine_safety"


def test_repertoire_line_is_book():
    bot = SparringBot(FixedModel({}), None, BotConfig(1500, 1500), random.Random(0),
                      repertoire_lines=[["e2e4", "e7e5", "g1f3"]])
    b = chess.Board()
    assert bot.choose(b).move == "e2e4" and bot.choose(b).source == "book"


def test_lesson_line_follows_and_leaves():
    rng = random.Random(0)
    assert lesson_line_move("french_advance", "white", [], rng) == "e2e4"
    assert lesson_line_move("french_advance", "white", ["e2e4", "e7e6", "d2d4", "d7d5"], rng) == "e4e5"
    assert lesson_line_move("french_advance", "white", ["e2e4", "c7c5"], rng) is None
    for sid, sides in LESSON_LINES.items():          # every line is legal
        for lines in sides.values():
            for ln in lines:
                b = chess.Board()
                for u in ln:
                    assert b.is_legal(chess.Move.from_uci(u)), (sid, ln, u)
                    b.push_uci(u)


def test_offset_calibration():
    assert update_offset(50, [1, 1, 1, 1, 1, 1, 0.5, 1]) == 75
    assert update_offset(50, [0, 0, 0, 0.5, 0, 0]) == 25
    assert update_offset(50, [1, 0, 1, 0, 0.5, 0.5]) == 50
    assert update_offset(50, [1, 1]) == 50            # not enough games yet
    assert bot_target(1234, 50) == 1284


def test_think_time_ranges():
    b = chess.Board()
    assert 0.5 <= think_time(b, 0.0) <= 2.5
    assert 0.5 <= think_time(b, 1.0) <= 2.5
    t = think_time(b, 0.0, clock_s=400, rng=random.Random(1))
    assert 7 <= t <= 13


def test_structure_similarity():
    carlsbad = chess.Board("r1bq1rk1/pp2bppp/2p1pn2/3p4/3P4/2NBPN2/PP3PPP/R2QK2R w KQ - 0 10")
    assert structure_similarity(carlsbad, "iqp") < 1.0
    fr = chess.Board("rnbqkbnr/pp3ppp/4p3/2ppP3/3P4/8/PPP2PPP/RNBQKBNR w KQkq - 0 4")
    assert structure_similarity(fr, "french_advance") == 1.0


needs_engine = pytest.mark.skipif(shutil.which("stockfish") is None, reason="stockfish missing")


@needs_engine
def test_steering_picks_cheap_lesson_move_and_respects_spacing(pool):
    b = chess.Board()
    model = FixedModel({"e2e4": 0.5, "d2d4": 0.3, "g2g4": 0.2})
    calls = []

    def lesson(board, move, cid, cat):
        calls.append(move.uci())
        return 1.0 if move.uci() in ("d2d4", "g2g4") else 0.0

    bot = SparringBot(model, pool, BotConfig(1500, 1500), random.Random(0), lesson_score=lesson)
    bot.set_focus("structure-carlsbad", "structure")
    bot.steer.bot_moves = 10
    bm = bot.choose(b)
    assert bm.source == "steer" and bm.move == "d2d4"          # g4 costs too much win prob
    assert bot.steer.log and bot.steer.log[-1]["cost"] <= 0.05
    assert bot.choose(b).source != "steer"                     # < 4 bot moves since the last steer


@needs_engine
def test_focus_dropped_when_player_escapes(pool):
    bot = SparringBot(FixedModel({}), pool, BotConfig(1500, 1500))
    bot.set_focus("tactic-fork-knight", "tactic")
    bot.steer.pending = "tactic-fork-knight"
    bot.observe_player_move("best", lesson_hit=False)
    assert bot.steer.focus is None


@pytest.mark.maia
def test_maia_distribution_is_legal_and_skill_aware():
    pytest.importorskip("maia2")
    from chesscoach.sparring.human_model import MaiaModel
    m = MaiaModel()
    b = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3")
    probs = m.move_probs(b, 1500, 1500)
    assert set(probs) == {mv.uci() for mv in b.legal_moves}
    assert sum(probs.values()) == pytest.approx(1.0, abs=0.01)
    bk = chess.Board("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 2")
    assert set(m.move_probs(bk, 1100, 1100)) == {mv.uci() for mv in bk.legal_moves}


def test_opening_never_uses_raw_maia(pool):
    """Maia-2 is untrained before ply 10: out of book there, the bot plays one of the engine's
    near-best moves; from ply 10 on it samples Maia again."""
    model = FixedModel({"b1a3": 1.0, "h2h4": 1.0})          # what an untrained head might prefer
    bot = SparringBot(model, pool, BotConfig(bot_elo=1500, player_elo=1500), random.Random(0))
    b = chess.Board()
    mv = bot.choose(b)
    best = pool.analyse(b, multipv=3, time=0.35)
    assert mv.source == "engine_opening" and mv.move in {l.moves[0] for l in best.lines}
    late = chess.Board("r1bq1rk1/ppp2ppp/2np1n2/2b1p3/2B1P3/2PP1N2/PP3PPP/RNBQ1RK1 w - - 0 7")
    late_model = FixedModel({"h2h3": 1.0})
    assert SparringBot(late_model, pool, BotConfig(1500, 1500), random.Random(0)).choose(late).source == "maia"


def test_opening_tree_comes_first(pool):
    from chesscoach.analysis.book import TreeBook
    tree = TreeBook.from_games([["e2e4", "c7c5"]] * 60)
    bot = SparringBot(FixedModel({"b1a3": 1.0}), pool, BotConfig(1500, 1500), random.Random(0), opening_tree=tree)
    assert bot.choose(chess.Board()) .move == "e2e4"


def test_band_tree_falls_back_to_all_bands():
    from chesscoach.analysis.engine import fen4
    from chesscoach.sparring.openings import band_tree
    start = fen4(chess.Board())
    after = chess.Board(); after.push_uci("e2e4")
    data = {"min_games": 50, "bands": {
        "all": {start: {"e2e4": 900, "d2d4": 400}, fen4(after): {"e7e5": 500}},
        "B1": {start: {"e2e4": 30, "f2f3": 25}}}}                    # too thin: 55 games, moves < 50
    t = band_tree("B1", data)
    assert t.moves(chess.Board()) == {"e2e4": 900, "d2d4": 400}
    assert t.moves(after) == {"e7e5": 500}
    rich = {"min_games": 50, "bands": {"all": data["bands"]["all"], "B2": {start: {"d2d4": 300}}}}
    assert band_tree("B2", rich).moves(chess.Board()) == {"d2d4": 300}
    assert band_tree("B2", {}) is None
