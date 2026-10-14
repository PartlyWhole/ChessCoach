"""Unit tests for L1 core math: win probability, classification, sharpness, phase, SEE."""
import chess
import chess.engine
import pytest

from chesscoach.analysis.board_utils import see_move, see_target
from chesscoach.analysis.classify import classify
from chesscoach.analysis.engine import sharpness
from chesscoach.analysis.phase import game_phase
from chesscoach.analysis.winprob import for_color, win_prob, win_prob_cp
from chesscoach.types import EngineLine, EngineResult


def line(moves, cp=None, mate=None):
    from chesscoach.analysis.winprob import win_prob_cp_or_mate
    return EngineLine(moves=moves, cp=cp, mate=mate, win_prob=win_prob_cp_or_mate(cp, mate), depth=16)


# ---------- win probability ----------
def test_win_prob_symmetry_and_midpoint():
    assert win_prob_cp(0) == pytest.approx(0.5)
    assert win_prob_cp(150) + win_prob_cp(-150) == pytest.approx(1.0)


def test_win_prob_lichess_value():
    # scalachess: 50 + 50 * (2 / (1 + exp(-0.00368208 * 100)) - 1) = 59.10 %
    assert win_prob_cp(100) == pytest.approx(0.5910, abs=1e-4)


def test_win_prob_ceiling():
    assert win_prob_cp(5000) == win_prob_cp(1000)


def test_mate_scores():
    assert win_prob(chess.engine.Mate(3)) == 1.0
    assert win_prob(chess.engine.Mate(-2)) == 0.0
    assert win_prob(chess.engine.Mate(-0)) == 0.0


def test_mover_pov():
    assert for_color(0.7, "black") == pytest.approx(0.3)


def test_rule4_same_cp_drop_different_meaning():
    """AGENTS rule 4: 300 cp at +8 is not a blunder; at 0.0 it is."""
    at_won = win_prob_cp(800) - win_prob_cp(500)
    at_equal = win_prob_cp(0) - win_prob_cp(-300)
    assert at_won < 0.15 <= at_equal


# ---------- classification ----------
START = chess.Board()


def er(lines):
    return EngineResult(fen="", lines=lines, sharpness=0.0)


def test_best_move():
    m = chess.Move.from_uci("e2e4")
    a = classify(START, m, er([line(["e2e4"], cp=30), line(["d2d4"], cp=25)]), er([line(["c7c5"], cp=30)]))
    assert a.move_class == "best" and a.loss == 0


def test_thresholds_from_same_search():
    m = chess.Move.from_uci("g2g4")
    before = er([line(["e2e4"], cp=30), line(["d2d4"], cp=25), line(["g2g4"], cp=-120)])
    a = classify(START, m, before, er([line(["d7d5"], cp=0)]))
    assert a.win_prob_after == pytest.approx(win_prob_cp(-120))   # taken from the MultiPV line
    assert a.move_class == "mistake"


@pytest.mark.parametrize("cp_after,cls", [(25, "excellent"), (-20, "good"), (-60, "inaccuracy"),
                                          (-110, "mistake"), (-400, "blunder")])
def test_class_ladder(cp_after, cls):
    m = chess.Move.from_uci("a2a3")
    a = classify(START, m, er([line(["e2e4"], cp=30)]), er([line(["e7e5"], cp=cp_after)]))
    assert a.move_class == cls


def test_won_game_capped_at_inaccuracy():
    m = chess.Move.from_uci("a2a3")
    a = classify(START, m, er([line(["e2e4"], cp=1000)]), er([line(["e7e5"], cp=600)]))
    assert a.loss > 0 and a.move_class == "inaccuracy"


def test_throwing_away_forced_mate_into_equality_is_blunder():
    m = chess.Move.from_uci("a2a3")
    a = classify(START, m, er([line(["e2e4"], mate=2)]), er([line(["e7e5"], cp=0)]))
    assert a.move_class == "blunder"


def test_mate_to_big_advantage_is_minor():
    # Like lila's MateAdvice "mate lost" at > +7: an inaccuracy, not a blunder.
    m = chess.Move.from_uci("a2a3")
    a = classify(START, m, er([line(["e2e4"], mate=2)]), er([line(["e7e5"], cp=700)]))
    assert a.move_class == "inaccuracy"


def test_forced():
    b = chess.Board("k7/8/8/8/8/8/1r6/K7 w - - 0 1")   # a2 and b1 covered by the rook: only Kxb2
    moves = list(b.legal_moves)
    assert [m.uci() for m in moves] == ["a1b2"]
    a = classify(b, moves[0], er([line([moves[0].uci()], cp=-500)]), er([line([], cp=-500)]))
    assert a.move_class == "forced"


def test_black_mover_pov():
    b = chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")
    m = chess.Move.from_uci("f7f6")
    a = classify(b, m, er([line(["c7c5"], cp=30)]), er([line(["d2d4"], cp=120)]))
    assert a.mover == "black"
    assert a.win_prob_before == pytest.approx(1 - win_prob_cp(30))
    assert a.move_class == "inaccuracy"


# ---------- sharpness ----------
def test_sharpness_only_move():
    lines = [line(["a"], cp=0), line(["b"], cp=-500)]
    assert sharpness(START, lines) == 1.0


def test_sharpness_quiet():
    lines = [line(["a"], cp=20), line(["b"], cp=15)]
    assert sharpness(START, lines) < 0.1


def test_sharpness_black_pov():
    b = chess.Board("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1")
    lines = [line(["a"], cp=-50), line(["b"], cp=300)]   # White POV: black's best is -50
    assert sharpness(b, lines) == 1.0


# ---------- phase ----------
def test_phase_opening_middlegame_endgame():
    assert game_phase(chess.Board()) == "opening"
    mid = chess.Board("r1bq1rk1/pp2bppp/2n1pn2/3p4/3P4/2NBPN2/PP3PPP/R2QK2R w KQ - 0 13")
    assert game_phase(mid) == "middlegame"
    assert game_phase(chess.Board("8/5pk1/6p1/8/3R4/6P1/5PK1/3r4 w - - 0 40")) == "endgame"
    assert game_phase(mid, in_book=True) == "opening"


# ---------- SEE ----------
def test_see_free_piece():
    b = chess.Board("4k3/8/8/3n4/8/8/8/3RK3 w - - 0 1")
    assert see_target(b, chess.D5, chess.WHITE) == 3


def test_see_defended_pawn_by_queen_loses():
    b = chess.Board("4k3/8/4p3/3p4/8/8/8/3QK3 w - - 0 1")
    assert see_target(b, chess.D5, chess.WHITE) == 1 - 9


def test_see_xray_rooks():
    # Rd1 + Rd2 (battery) vs pawn d5 defended by Rd8: RxP, RxR, RxR → +1 for White.
    b = chess.Board("3rk3/8/8/3p4/8/8/3R4/3RK3 w - - 0 1")
    assert see_move(b, chess.Move.from_uci("d2d5")) == 1


def test_see_pinned_defender_does_not_count():
    # Black knight e6 pinned to the king by Re1; it cannot recapture on d4? use f-pawn defender
    b = chess.Board("4k3/8/4n3/8/3p4/8/8/3QR1K1 w - - 0 1")
    # Ne6 defends d4 but is pinned on the e-file by Re1 → Qxd4 wins a clean pawn.
    assert see_target(b, chess.D4, chess.WHITE) == 1
