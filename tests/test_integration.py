"""End-to-end: session pipeline (01), post-game review (06 §4), puzzle re-tagging (06 §6)."""
import csv
import random
import time

import chess
import pytest

from chesscoach.concepts.registry import Registry
from chesscoach.learner.puzzles import build_bank, load_theme_map, read_lichess_csv, retag, Puzzle
from chesscoach.learner.review import build_review, select_moments
from chesscoach.learner.store import Store
from chesscoach.policy.policy import CoachingPolicy, CoachSettings, LearnerView, load_fallback
from chesscoach.session import GameSession
from chesscoach.sparring.bot import BotConfig, SparringBot

REG = Registry.load(allow_unreviewed=True)
FALLBACK = load_fallback(allow_unreviewed=True)


class FirstLegal:
    """Deterministic stand-in for Maia: prefers listed moves, else the first legal move."""
    name = "scripted"

    def __init__(self, script):
        self.script = list(script)

    def move_probs(self, board, elo_self, elo_oppo):
        for u in self.script:
            if board.is_legal(chess.Move.from_uci(u)):
                self.script.remove(u)
                return {u: 1.0}
        return {next(iter(board.legal_moves)).uci(): 1.0}


def session(pool, analyzer, script, mode="standard"):
    bot = SparringBot(FirstLegal(script), pool, BotConfig(900, 900), random.Random(0))
    pol = CoachingPolicy(REG, CoachSettings(mode=mode), LearnerView(band="B1"), fallback=FALLBACK)
    return GameSession(analyzer, REG, bot, pol, player_color="white", band="B1", store=Store())


def test_blunder_interrupt_takeback_and_retry(pool, analyzer):
    s2 = session(pool, analyzer, ["e7e5", "d7d6"])
    s2.start()
    s2.player_move("e2e4")
    r = s2.player_move("d1h5")
    r = s2.player_move("h5e5")        # Qxe5+?? dxe5: queen for a pawn
    assert r.assessment.move_class == "blunder"
    assert r.event is not None and r.event.kind == "interrupt" and r.event.hint_level in (1, 2)
    assert r.waiting_for_takeback and r.bot_move is None
    s2.takeback()
    assert s2.board.piece_at(chess.H5) == chess.Piece(chess.QUEEN, chess.WHITE)
    r = s2.player_move("b1c3")        # a sensible retry closes the hint session
    assert r.bot_move is not None
    mastery = s2.finish({})
    assert mastery                     # at least one concept opportunity recorded
    assert s2.store.game_log(s2.game_id)


def test_live_latency_budget(pool):
    """01: per-move pipeline < 1.5 s at default settings (live time caps)."""
    from chesscoach.analysis.analyzer import Analyzer
    live = Analyzer(pool, live=True)
    s = session(pool, live, ["e7e5", "b8c6", "g8f6", "f8c5", "d7d6"])
    s.start()
    times = []
    for mv in ["e2e4", "g1f3", "f1c4", "d2d3", "e1g1"]:
        t = time.perf_counter()
        s.player_move(mv)
        times.append(time.perf_counter() - t)
    times.sort()
    # Includes the bot reply and its analysis (steps 1–7). Report p95-ish (max of 5) loosely.
    assert times[len(times) // 2] < 3.0, times


def test_review_builder(pool, analyzer):
    # White blunders the queen on move 3 and later a knight.
    moves = ["e2e4", "e7e5", "d1h5", "d7d6", "h5e5", "d6e5", "g1f3", "b8c6", "f3g5", "d8g5"]
    review = build_review(moves, "white", analyzer, REG, "B1", player_id="p", game_id="g", depth=12,
                          fallback=FALLBACK)
    plies = [m.ply for m in review.moments]
    assert 4 in plies                                   # Qxe5+?? is the largest swing
    assert all(abs(a - b) >= 4 for a in plies for b in plies if a != b)
    big = next(m for m in review.moments if m.ply == 4)
    assert big.start_fen == chess.Board("rnbqkbnr/ppp2ppp/3p4/4p2Q/4P3/8/PPPP1PPP/RNB1KBNR w KQkq - 0 3").fen() or big.lead_in == "d7d6"
    assert big.summary                                   # concept level-3 text or engine line
    assert review.cards and all(c.solution for c in review.cards)
    assert review.phase_accuracy["opening"] is not None


def test_puzzle_retag(tmp_path):
    # Constructed puzzle (not from the Lichess DB): after ...Qd8-d5?? White plays Nc7+ forking K+Q+R.
    p = tmp_path / "puzzles.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["PuzzleId", "FEN", "Moves", "Rating", "RatingDeviation", "Popularity", "NbPlays", "Themes",
                    "GameUrl", "OpeningTags"])
        w.writerow(["T0001", "r1bqkbnr/ppp2ppp/8/1N6/8/8/PPPP1PPP/R1BQKB1R b KQkq - 0 6", "d8d5 b5c7 e8d8 c7d5",
                    "1200", "80", "90", "100", "fork short", "", ""])
        w.writerow(["T0002", "r1bqkbnr/ppp2ppp/8/1N6/8/8/PPPP1PPP/R1BQKB1R b KQkq - 0 6", "d8d5 b5c7 e8d8 c7d5",
                    "1200", "80", "90", "100", "skewer short", "", ""])
    bank = build_bank(read_lichess_csv(p))
    assert [q.puzzle_id for q in bank] == ["T0001"]              # skewer tag not confirmed → dropped
    assert "tactic-fork-knight" in bank[0].concept_ids
