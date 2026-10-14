"""The torch-free Maia-2 preprocessing must match the maia2 package exactly."""
import random

import chess
import pytest

from chesscoach.sparring import maia_features as mf

maia_utils = pytest.importorskip("maia2.utils")


def test_vocabulary_matches_maia2():
    assert list(mf.all_moves()) == maia_utils.get_all_possible_moves()


def test_elo_categories_match_maia2():
    d = maia_utils.create_elo_dict()
    for elo in (500, 1099, 1100, 1150, 1199, 1200, 1555, 1999, 2000, 2600):
        assert mf.elo_category(elo) == maia_utils.map_to_category(elo, d), elo


def test_planes_match_maia2_on_random_positions():
    rng = random.Random(0)
    for _ in range(60):
        b = chess.Board()
        for _ in range(rng.randint(0, 50)):
            ms = list(b.legal_moves)
            if not ms:
                break
            b.push(rng.choice(ms))
        o, _ = mf.oriented(b)
        assert mf.planes(o) == maia_utils.board_to_tensor(o).flatten().tolist(), b.fen()


def test_mirroring_roundtrip_and_softmax():
    b = chess.Board("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 2")
    _, idx, legal, mirrored = mf.prepare(b)
    assert mirrored and len(idx) == b.legal_moves.count()
    probs = mf.probs_from_logits([0.0] * len(legal), legal, mirrored)
    assert set(probs) == {m.uci() for m in b.legal_moves}
    assert sum(probs.values()) == pytest.approx(1.0)
