"""Browser bridge (ADR 0002) exercised natively: a Python `rpc` stands in for the page, answering
"engine" with real Stockfish (side-to-move POV, as the page's UCI parser does) and "maia" with
the PyTorch Maia-2 model. Everything except the JavaScript itself runs."""
import json
import shutil

import chess
import chess.engine
import pytest

from chesscoach.analysis.engine import EnginePool
from chesscoach.sparring import maia_features as mf
from chesscoach.web.app import WebApp
from chesscoach.web.bridge import RpcEnginePool, RpcMaiaModel

pytestmark = pytest.mark.skipif(shutil.which("stockfish") is None, reason="stockfish missing")


@pytest.fixture(scope="module")
def native():
    eng = chess.engine.SimpleEngine.popen_uci("stockfish")
    eng.configure({"Threads": 1})
    yield eng
    eng.quit()


def make_rpc(eng, maia=None):
    def rpc(kind, payload):
        req = json.loads(payload)
        if kind == "engine":
            b = chess.Board(req["fen"])
            limit = chess.engine.Limit(depth=req["depth"],
                                       time=req["movetime_ms"] / 1000 if req["movetime_ms"] else None)
            infos = eng.analyse(b, limit, multipv=req["multipv"], game=object())
            lines = []
            for i in infos:
                sc = i["score"].relative          # side-to-move POV, like raw UCI
                lines.append({"pv": [m.uci() for m in i.get("pv", [])], "cp": sc.score(), "mate": sc.mate(),
                              "depth": i.get("depth", 0)})
            return json.dumps({"lines": lines})
        if kind == "maia":
            import torch
            model, _ = maia
            x = torch.tensor(req["planes"], dtype=torch.float32).reshape(1, 18, 8, 8)
            with torch.no_grad():
                logits = model(x, torch.tensor([req["elo_self"]]), torch.tensor([req["elo_oppo"]]))[0][0]
            return json.dumps({"logits": [float(logits[i]) for i in req["legal"]]})
        raise ValueError(kind)
    return rpc


def test_rpc_engine_matches_native_pool(native):
    """White-POV conversion: the RPC pool and the native pool agree on sign and best move."""
    rpc_pool = RpcEnginePool(make_rpc(native))
    nat = EnginePool(size=1, threads=1, clear_hash=True)
    for fen in ("r3kbnr/ppp2ppp/8/1N1q4/8/8/PPPP1PPP/R1BQKB1R w KQkq - 0 8",
                "r3kbnr/ppp2ppp/8/1N1q4/8/8/PPPP1PPP/R1BQKB1R b KQkq - 0 8",
                "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1"):
        b = chess.Board(fen)
        a, n = rpc_pool.analyse(b, depth=12), nat.analyse(b, depth=12)
        assert a.lines[0].moves[0] == n.lines[0].moves[0]
        assert (a.lines[0].win_prob > 0.5) == (n.lines[0].win_prob > 0.5)
        assert len(a.lines) == len(n.lines)
    nat.close()


@pytest.mark.maia
def test_rpc_maia_matches_maia2(native):
    pytest.importorskip("maia2")
    from maia2 import inference, model
    m = model.from_pretrained(type="rapid", device="cpu", save_root="models/maia2").eval()
    prep = inference.prepare()
    rpc_model = RpcMaiaModel(make_rpc(native, (m, prep)))
    for fen in ("r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3",
                "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 2"):
        ours = rpc_model.move_probs(chess.Board(fen), 1500, 1400)
        ref, _ = inference.inference_each(m, prep, fen, 1500, 1400)
        assert max(ours, key=ours.get) == next(iter(ref))
        for mv, p in list(ref.items())[:5]:
            assert ours[mv] == pytest.approx(p, abs=1e-3)


def test_webapp_game_flow(native):
    """A short game through the JSON API with a stub Maia (uniform over legal moves)."""
    def rpc(kind, payload):
        if kind == "maia":
            req = json.loads(payload)
            return json.dumps({"logits": [0.0] * len(req["legal"])})
        return make_rpc(native)(kind, payload)

    app = WebApp(rpc, seed=1)
    st = json.loads(app.new_game("white", 1000, "standard", show_drafts=True))
    assert st["turn"] == "white" and "e2e4" in st["legal"] and st["concepts_loaded"] == 43
    st = json.loads(app.move("e2e4"))
    assert st["bot_move"] and st["turn"] == "white" and st["assessment"]["move_class"]
    assert st["assessment"]["san"] == "e4" and st["assessment"]["best_san"]
    assert 0 < st["eval_white"] < 1 and isinstance(st["queued"], list)
    assert json.loads(WebApp(rpc).new_game(show_drafts=False))["concepts_loaded"] == 0   # rule 2 gate


def test_webapp_review(native):
    """Post-game review for both sides of a finished game (p2p page, ADR 0003)."""
    app = WebApp(make_rpc(native))
    moves = ["f2f3", "e7e5", "g2g4", "d8h4"]                     # fool's mate
    r = json.loads(app.review(json.dumps(moves), depth=10))
    assert [p["san"] for p in r["plies"]] == ["f3", "e5", "g4", "Qh4#"]
    assert [p["mover"] for p in r["plies"]] == ["white", "black", "white", "black"]
    g4 = r["plies"][2]
    assert g4["move_class"] == "blunder" and g4["best_san"] and g4["best_san"] != "g4"
    assert g4["best_line_san"][0] == g4["best_san"]
    # Why? (02 §6.6): the punishing line after g4 is ...Qh4 mate; the best line keeps material.
    why = g4["why"]
    assert why["played"]["steps"][0]["move"] == "g2g4" and why["played"]["outcome"] == "mate"
    assert why["played"]["mate_for"] == "black" and why["played"]["decisive_ply"] == 1
    assert why["best"]["steps"][0]["move"] == g4["best_move"] and why["best"]["outcome"] != "mate"
    assert r["plies"][1]["why"] is None                            # only for inaccuracy or worse
    assert r["plies"][3]["move_class"] in ("best", "forced")
    assert r["plies"][3]["wp_white_after"] == 0.0                  # mated: White POV
    assert 0.4 < r["wp_white_start"] < 0.6
    w, b = r["sides"]["white"], r["sides"]["black"]
    assert w["counts"]["blunder"] == 1 and b["counts"]["blunder"] == 0
    assert b["accuracy"] > w["accuracy"]
    assert [m["ply"] for m in w["moments"]] == [2]
    # Rule 2: without the developer preview no unreviewed text reaches the page.
    assert w["moments"][0]["summary"] == "" and w["moments"][0]["concept_id"] is None
    assert r["depth"] == 10 and r["engine"]


def test_webapp_learning_loop(native):
    """Coach page loop (ADR 0004): profile from the first game's rating, resign, review, rating
    update, and the second game uses the stored profile."""
    def rpc(kind, payload):
        if kind == "maia":
            req = json.loads(payload)
            return json.dumps({"logits": [0.0] * len(req["legal"])})
        return make_rpc(native)(kind, payload)

    app = WebApp(rpc, seed=2, store_path=":memory:")
    assert json.loads(app.learner_state())["has_profile"] is False
    st = json.loads(app.new_game("white", 1100, "standard", show_drafts=True))
    assert st["band"] == "B1" and st["bot_elo"] == 1150 and st["moves"] == [st["bot_move"]] * 0
    for uci in ("e2e4", "d2d4"):
        if uci in st["legal"]:
            st = json.loads(app.move(uci))
    assert len(st["moves"]) == 4 and not st["game_over"]
    st = json.loads(app.resign())
    assert st["game_over"] and st["result"] == "0-1" and st["legal"] == []
    out = json.loads(app.finish_game())
    assert out["score"] == 0.0 and out["result"] == "0-1"
    assert out["summary"]["rating_after"] < out["summary"]["rating_before"] == 1100
    assert len(out["review"]["plies"]) == 4 and set(out["review"]["sides"]) == {"white", "black"}
    assert json.loads(app.finish_game()) == out                    # idempotent
    ls = json.loads(app.learner_state(True))
    assert ls["games"] == 1 and ls["rating"] == out["summary"]["rating_after"]
    st2 = json.loads(app.new_game("black", 2000, "standard", show_drafts=True))
    assert st2["band"] == "B1" and st2["bot_elo"] == ls["bot_elo"]   # stored profile, not the new input
    assert json.loads(app.reset_progress())["has_profile"] is False


def test_webapp_drills(native):
    """Drill API (06 §5): queue from saved cards, solve, grade recorded once, card scheduled."""
    from chesscoach.learner.srs import ReviewCard
    app = WebApp(make_rpc(native), store_path=":memory:")
    app.learner.ensure(1200)
    c = ReviewCard.new("local", "find_move", "r3k2r/pp3ppp/8/3N4/8/8/PPP2PPP/R3K2R w KQkq - 0 1",
                       ["d5c7", "e8d8", "c7a8"], [], {"game_id": "g", "ply": 20})
    app.learner.store.save_card(c)
    q = json.loads(app.drill_queue())
    assert q["cards"][0]["card_id"] == c.card_id and q["cards"][0]["side"] == "white"
    assert all(x["source"].get("puzzle_id") for x in q["cards"][1:])     # puzzles fill the rest (06 §5)
    st = json.loads(app.drill_start(c.card_id))
    assert st["player_moves"] == 2 and "d5c7" in st["legal"]
    st = json.loads(app.drill_move("d5c7"))
    assert st["result"] == "correct" and st["reply_san"] == "Kd8" and "graded" not in st
    st = json.loads(app.drill_move("c7a8"))
    assert st["solved"] and st["graded"]["grade"] in ("Easy", "Good")
    assert st["graded"]["counts"] == {"total": 1, "new": 0, "due": 0}
    assert json.loads(app.drill_hint())["graded"] == st["graded"]      # recorded once
