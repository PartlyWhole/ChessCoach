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
    assert json.loads(WebApp(rpc).new_game(show_drafts=False))["concepts_loaded"] == 0   # rule 2 gate
