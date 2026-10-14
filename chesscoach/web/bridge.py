"""Browser adapters (ADR 0002): the same engine and human-model interfaces the native code uses,
backed by a synchronous RPC into JavaScript.

`rpc(kind, payload_json) -> response_json` is supplied by the host. In the browser it is the
Pyodide worker's `rpc_sync`, which posts the request to the page and blocks on a
SharedArrayBuffer until the page answers (Stockfish WASM / onnxruntime-web run in their own
workers). Tests pass a Python function instead.
"""
from __future__ import annotations

import json
from collections import OrderedDict
from typing import Callable, Optional

import chess

from chesscoach import config
from chesscoach.analysis.engine import fen4, sharpness, terminal_result
from chesscoach.analysis.winprob import win_prob_cp_or_mate
from chesscoach.sparring import maia_features as mf
from chesscoach.types import EngineLine, EngineResult

Rpc = Callable[[str, str], str]


class RpcEnginePool:
    """Drop-in for EnginePool.analyse(). The page runs Stockfish (UCI) and returns, per MultiPV
    line, the side-to-move score and PV; we convert to White POV here so all evaluation logic
    stays in Python."""

    def __init__(self, rpc: Rpc, version: str = "Stockfish 19 lite (wasm)", cache_size: int = 4000):
        self.rpc = rpc
        self.version = version
        self._cache: "OrderedDict[tuple, EngineResult]" = OrderedDict()
        self._cache_size = cache_size

    def analyse(self, board: chess.Board, depth: Optional[int] = None, multipv: Optional[int] = None,
                time: Optional[float] = None) -> EngineResult:
        depth = depth or int(config.get("engine.depth_live"))
        multipv = multipv or int(config.get("engine.multipv"))
        term = terminal_result(board)
        if term is not None:
            return term
        key = (fen4(board), depth, multipv, time)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        req = {"fen": board.fen(), "depth": depth, "multipv": min(multipv, board.legal_moves.count()),
               "movetime_ms": int(time * 1000) if time else None}
        resp = json.loads(self.rpc("engine", json.dumps(req)))
        sign = 1 if board.turn == chess.WHITE else -1
        lines = []
        for l in resp["lines"]:
            cp = None if l.get("cp") is None else sign * int(l["cp"])
            mate = None if l.get("mate") is None else sign * int(l["mate"])
            lines.append(EngineLine(moves=list(l["pv"]), cp=cp, mate=mate,
                                    win_prob=win_prob_cp_or_mate(cp, mate), depth=int(l["depth"])))
        result = EngineResult(fen=board.fen(), lines=lines, sharpness=sharpness(board, lines))
        self._cache[key] = result
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return result

    def close(self) -> None:
        pass


class RpcMaiaModel:
    """Maia-2 (fp16 ONNX) run by onnxruntime-web on the page; pre/post-processing in Python."""
    name = "maia2-onnx"

    def __init__(self, rpc: Rpc):
        self.rpc = rpc

    def move_probs(self, board: chess.Board, elo_self: int, elo_oppo: int) -> dict[str, float]:
        planes, idx, legal, mirrored = mf.prepare(board)
        if not idx:
            return {}
        req = {"planes": planes, "elo_self": mf.elo_category(elo_self), "elo_oppo": mf.elo_category(elo_oppo),
               "legal": idx}
        logits = json.loads(self.rpc("maia", json.dumps(req)))["logits"]
        return mf.probs_from_logits(logits, legal, mirrored)
