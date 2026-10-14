"""Syzygy probing (02 §6.5). Optional: enabled when CHESSCOACH_SYZYGY points at tablebases."""
from __future__ import annotations

from typing import Optional

import chess
import chess.syzygy

from chesscoach import config
from chesscoach.analysis.engine import sharpness
from chesscoach.types import EngineLine, EngineResult

MAX_PIECES = 7


class Tablebase:
    def __init__(self, path: Optional[str] = config.SYZYGY_PATH):
        self._tb = chess.syzygy.open_tablebase(path) if path else None

    def probe(self, board: chess.Board) -> Optional[EngineResult]:
        """Exact result for ≤ 7 pieces: win → win_prob 1, draw → 0.5, loss → 0 (White POV).
        Lines list legal moves ranked by tablebase outcome (best first, up to 3)."""
        if self._tb is None or chess.popcount(board.occupied) > MAX_PIECES or board.castling_rights:
            return None
        try:
            scored = []
            for m in board.legal_moves:
                board.push(m)
                try:
                    wdl = -self._tb.probe_wdl(board)      # from the mover's POV
                    dtz = -self._tb.probe_dtz(board)
                finally:
                    board.pop()
                scored.append((wdl, -abs(dtz) if wdl > 0 else abs(dtz), m))
        except (KeyError, chess.syzygy.MissingTableError):
            return None
        if not scored:
            return None
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        lines = []
        mover_white = board.turn == chess.WHITE
        for wdl, _, m in scored[:3]:
            # ±1 = cursed win / blessed loss: a draw under the 50-move rule.
            p_mover = 1.0 if wdl == 2 else 0.0 if wdl == -2 else 0.5
            p_white = p_mover if mover_white else 1 - p_mover
            # Tablebase wins carry no mate distance here; use the cp ceiling (±1000) so the
            # line still reads as decisive. Draws are cp 0.
            cp = 0 if p_white == 0.5 else (1000 if p_white == 1.0 else -1000)
            lines.append(EngineLine(moves=[m.uci()], cp=cp, mate=None, win_prob=p_white, depth=0))
        return EngineResult(fen=board.fen(), lines=lines, sharpness=sharpness(board, lines), tablebase=True)

    def close(self) -> None:
        if self._tb is not None:
            self._tb.close()
