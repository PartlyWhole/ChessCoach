"""One drill attempt (docs/06 §5, hint ladder from docs/04).

The player is shown a card's position and plays the solution's moves; the expected replies are
played for them. A move counts if it is the solution move, or the engine's own best move in the
position, or it gives mate; such an alternative ends the drill as solved, because the stored
solution no longer applies after it. (Win probability is deliberately not used here: in a won
position almost every move loses under 2%, and "find the best move" would accept anything.)

Wrong moves: up to MAX_WRONG retries; the next wrong move reveals the solution. A solve after a
wrong try is graded at least Hard (06 §5 grading, a wrong try counts like a level-1 hint).

Hints follow the ladder with facts only: level 1 names the piece type that moves, level 2
highlights its square, level 3 shows the move. When the card's concept has renderable template
text for this position (approved, or with the developer preview), that text comes with the hint.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import chess

from chesscoach.analysis.board_utils import PIECE_NAME
from chesscoach.learner.srs import ReviewCard
from chesscoach.types import EngineResult

MAX_WRONG = 2

EngineFn = Callable[[chess.Board], EngineResult]
HintTextFn = Callable[[chess.Board, list[str], int], Optional[str]]   # (board, concept_ids, level) → text


@dataclass
class DrillAttempt:
    card: ReviewCard
    engine: EngineFn
    hint_text: Optional[HintTextFn] = None
    clock: Callable[[], float] = time.monotonic
    board: chess.Board = field(init=False)
    index: int = field(init=False, default=0)        # next solution move to play (player's)
    wrong: int = field(init=False, default=0)
    hint_level: int = field(init=False, default=0)
    done: bool = field(init=False, default=False)
    solved: bool = field(init=False, default=False)
    played: list[str] = field(init=False, default_factory=list)
    t0: float = field(init=False, default=0.0)

    def __post_init__(self):
        self.board = chess.Board(self.card.fen)
        self.t0 = self.clock()

    @property
    def side(self) -> str:
        return "white" if chess.Board(self.card.fen).turn == chess.WHITE else "black"

    @property
    def player_moves(self) -> int:
        return (len(self.card.solution) + 1) // 2

    def expected(self) -> Optional[chess.Move]:
        if self.index >= len(self.card.solution):
            return None
        return chess.Move.from_uci(self.card.solution[self.index])

    def max_hint_level(self) -> int:
        return max(self.hint_level, 1 if self.wrong else 0)

    def seconds_per_move(self) -> float:
        return (self.clock() - self.t0) / max(1, self.player_moves)

    def state(self, **extra) -> dict:
        out = {"fen": self.board.fen(), "side": self.side, "done": self.done, "solved": self.solved,
               "wrong": self.wrong, "hint_level": self.hint_level, "played": list(self.played),
               "moves_left": max(0, (len(self.card.solution) - self.index + 1) // 2),
               "legal": [] if self.done else [m.uci() for m in self.board.legal_moves]}
        out.update(extra)
        return out

    # ---------------------------------------------------------------- moves
    def move(self, uci: str) -> dict:
        if self.done:
            return self.state(result="done")
        mv = chess.Move.from_uci(uci)
        if not self.board.is_legal(mv):
            return self.state(result="illegal")
        exp = self.expected()
        if exp is not None and mv == exp:
            return self._accept(mv, alternative=False)
        if exp is not None and self._as_good(mv):
            return self._accept(mv, alternative=True)
        self.wrong += 1
        if self.wrong > MAX_WRONG:
            return self.reveal(result="wrong")
        return self.state(result="wrong", tries_left=MAX_WRONG - self.wrong + 1)

    def _as_good(self, mv: chess.Move) -> bool:
        after_board = self.board.copy()
        after_board.push(mv)
        if after_board.is_checkmate():
            return True
        res = self.engine(self.board)
        return bool(res.lines and res.lines[0].moves and res.lines[0].moves[0] == mv.uci())

    def _accept(self, mv: chess.Move, alternative: bool) -> dict:
        san = self.board.san(mv)
        self.board.push(mv)
        self.played.append(san)
        self.index += 1
        reply_san = None
        if alternative or self.board.is_game_over():
            return self._finish(True, result="alternative" if alternative else "correct")
        if self.index < len(self.card.solution):
            reply = chess.Move.from_uci(self.card.solution[self.index])
            if self.board.is_legal(reply):
                reply_san = self.board.san(reply)
                self.board.push(reply)
                self.played.append(reply_san)
                self.index += 1
        if self.index >= len(self.card.solution):
            return self._finish(True, result="correct", reply_san=reply_san)
        return self.state(result="correct", reply_san=reply_san, reply=self.card.solution[self.index - 1])

    def _finish(self, solved: bool, **extra) -> dict:
        self.done, self.solved = True, solved
        return self.state(**extra)

    # ---------------------------------------------------------------- hints and reveal
    def hint(self) -> dict:
        if self.done:
            return self.state(result="done")
        exp = self.expected()
        if exp is None:
            return self.state(result="none")
        self.hint_level = min(3, self.hint_level + 1)
        if self.hint_level >= 3:
            return self.reveal(result="hint")
        hint = {"level": self.hint_level, "piece": PIECE_NAME[self.board.piece_type_at(exp.from_square)]}
        if self.hint_level >= 2:
            hint["square"] = chess.square_name(exp.from_square)
        if self.hint_text is not None:
            text = self.hint_text(self.board, self.card.concept_ids, self.hint_level)
            if text:
                hint["text"] = text
        return self.state(result="hint", hint=hint)

    def reveal(self, result: str = "revealed") -> dict:
        """Show the rest of the solution (counts as level 3: the card is failed)."""
        self.hint_level = 3
        b = self.board.copy()
        sans = []
        for u in self.card.solution[self.index:]:
            m = chess.Move.from_uci(u)
            if not b.is_legal(m):
                break
            sans.append(b.san(m))
            b.push(m)
        first = self.expected()
        out = self._finish(False, result=result, solution_san=sans,
                           solution=self.card.solution[self.index:],
                           hint={"level": 3, "move": first.uci() if first else None})
        return out
