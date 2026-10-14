"""Human-move models (docs/05 §1): Maia-2 by default, weakened Stockfish as fallback.

A model returns a probability distribution over legal moves (UCI → p) for a position, given
the bot's target rating and the opponent's rating.
"""
from __future__ import annotations

import math
from typing import Optional, Protocol

import chess

from chesscoach import config
from chesscoach.analysis.engine import EnginePool
from chesscoach.analysis.winprob import line_wp
from chesscoach.analysis.board_utils import cname


class HumanMoveModel(Protocol):
    name: str

    def move_probs(self, board: chess.Board, elo_self: int, elo_oppo: int) -> dict[str, float]: ...


class MaiaModel:
    """Maia-2 (MIT, `pip install maia2`). Elo buckets are <1100, 1100–1199 … 1900–1999, >=2000,
    so every target below 1100 plays like the <1100 bucket (see 05)."""
    name = "maia2"

    def __init__(self, kind: str = "rapid", model_dir: str = config.MAIA_MODEL_DIR, device: str = "cpu"):
        from maia2 import inference, model   # optional dependency
        self._inference = inference
        self._model = model.from_pretrained(type=kind, device=device, save_root=model_dir)
        self._prepared = inference.prepare()

    def move_probs(self, board: chess.Board, elo_self: int, elo_oppo: int) -> dict[str, float]:
        probs, _ = self._inference.inference_each(self._model, self._prepared, board.fen(), elo_self, elo_oppo)
        return dict(probs)


class EngineHumanModel:
    """Fallback (05 §1 "Weakened Stockfish"): softmax over MultiPV win-probability values with a
    rating-dependent sharpness. Plays less human-like mistakes than Maia; use only without Maia."""
    name = "engine"

    def __init__(self, pool: EnginePool, multipv: int = 8, depth: int = 10):
        self.pool, self.multipv, self.depth = pool, multipv, depth

    def move_probs(self, board: chess.Board, elo_self: int, elo_oppo: int) -> dict[str, float]:
        res = self.pool.analyse(board, depth=self.depth, multipv=self.multipv)
        me = cname(board.turn)
        # Stronger targets concentrate on the best lines: beta grows with rating.
        beta = 10 + max(0, elo_self - 600) / 40
        vals = {l.moves[0]: line_wp(l, me) for l in res.lines if l.moves}
        if not vals:
            return {}
        top = max(vals.values())
        w = {m: math.exp(beta * (v - top)) for m, v in vals.items()}
        z = sum(w.values())
        return {m: x / z for m, x in w.items()}


def load_default(pool: Optional[EnginePool] = None) -> HumanMoveModel:
    try:
        return MaiaModel()
    except Exception:  # noqa: BLE001 — maia2 missing or weights unavailable
        if pool is None:
            raise
        return EngineHumanModel(pool)
