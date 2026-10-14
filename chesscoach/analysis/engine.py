"""Stockfish wrapper: pooled long-lived UCI processes, MultiPV analysis, caching (docs/01, 02 §1)."""
from __future__ import annotations

import atexit
import queue
import threading
from collections import OrderedDict
from contextlib import contextmanager
from typing import Iterator, Optional

import chess
import chess.engine

from chesscoach import config
from chesscoach.analysis.winprob import line_wp, win_prob
from chesscoach.types import EngineLine, EngineResult


def fen4(board_or_fen) -> str:
    fen = board_or_fen.fen() if isinstance(board_or_fen, chess.Board) else board_or_fen
    return " ".join(fen.split()[:4])


def sharpness(board: chess.Board, lines: list[EngineLine]) -> float:
    """02 §4: clamp((wp(line1) - wp(line2)) / 0.15, 0, 1), mover POV; 0 with < 2 legal moves."""
    if board.legal_moves.count() < 2 or len(lines) < 2:
        return 0.0
    mover = "white" if board.turn == chess.WHITE else "black"
    d = line_wp(lines[0], mover) - line_wp(lines[1], mover)
    return max(0.0, min(1.0, d / 0.15))


def terminal_result(board: chess.Board) -> Optional[EngineResult]:
    """Game-over positions are scored without the engine."""
    outcome = board.outcome(claim_draw=False)
    if outcome is None:
        return None
    if outcome.winner is None:
        line = EngineLine(moves=[], cp=0, mate=None, win_prob=0.5, depth=0)
    else:
        white_won = outcome.winner == chess.WHITE
        line = EngineLine(moves=[], cp=None, mate=0, win_prob=1.0 if white_won else 0.0, depth=0)
    return EngineResult(fen=board.fen(), lines=[line], sharpness=0.0)


class EnginePool:
    """A fixed pool of Stockfish processes. Each analyse() borrows one process; never share a
    SimpleEngine across threads (02 §1)."""

    def __init__(self, path: str = config.ENGINE_PATH, size: Optional[int] = None,
                 threads: Optional[int] = None, hash_mb: Optional[int] = None,
                 cache_size: int = 20000, clear_hash: bool = False):
        self.path = path
        size = size or int(config.get("engine.pool_size"))
        self._free: "queue.Queue[chess.engine.SimpleEngine]" = queue.Queue()
        self._all: list[chess.engine.SimpleEngine] = []
        for _ in range(size):
            eng = chess.engine.SimpleEngine.popen_uci(path)
            eng.configure({"Threads": threads or int(config.get("engine.threads")),
                           "Hash": hash_mb or int(config.get("engine.hash_mb"))})
            self._all.append(eng)
            self._free.put(eng)
        self.version = self._all[0].id.get("name", "unknown")
        atexit.register(self.close)   # an unclosed pool would keep the interpreter from exiting
        self._cache: "OrderedDict[tuple, EngineResult]" = OrderedDict()
        self._cache_size = cache_size
        self._lock = threading.Lock()
        self.clear_hash = clear_hash   # True: ucinewgame before every search (reproducible tests)

    @contextmanager
    def _engine(self) -> Iterator[chess.engine.SimpleEngine]:
        eng = self._free.get()
        try:
            yield eng
        finally:
            self._free.put(eng)

    def analyse(self, board: chess.Board, depth: Optional[int] = None,
                multipv: Optional[int] = None, time: Optional[float] = None) -> EngineResult:
        """Search to `depth`, or stop after `time` seconds if given (whichever comes first).
        Time-capped results record the depth actually reached in EngineLine.depth."""
        depth = depth or int(config.get("engine.depth_live"))
        multipv = multipv or int(config.get("engine.multipv"))
        term = terminal_result(board)
        if term is not None:
            return term
        # Key: fen4 + engine_version + depth + multipv (01 "Caching").
        key = (fen4(board), self.version, depth, multipv, time)
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
                return hit
        with self._engine() as eng:
            infos = eng.analyse(board, chess.engine.Limit(depth=depth, time=time), multipv=multipv,
                                game=key if self.clear_hash else None)
        lines = []
        for info in infos:
            if "score" not in info:
                continue
            score = info["score"].white()
            lines.append(EngineLine(
                moves=[m.uci() for m in info.get("pv", [])],
                cp=score.score(),
                mate=score.mate(),
                win_prob=win_prob(score),
                depth=info.get("depth", depth),
            ))
        result = EngineResult(fen=board.fen(), lines=lines, sharpness=sharpness(board, lines))
        with self._lock:
            self._cache[key] = result
            if len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return result

    def close(self) -> None:
        all_, self._all = self._all, []
        for eng in all_:
            try:
                eng.quit()
            except chess.engine.EngineError:
                pass

    def __enter__(self) -> "EnginePool":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


_default: Optional[EnginePool] = None


def default_pool() -> EnginePool:
    global _default
    if _default is None:
        _default = EnginePool()
    return _default
