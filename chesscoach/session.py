"""Game Session Orchestrator (docs/01): stateful per game, ties L1–L5 together.

Per player move: analyze (reusing the bot move's "after" as "before") → classify → match
concepts → policy → record → bot reply → analyze the bot's move. After a blunder interrupt
that allows a takeback, the bot waits until the player takes back or resumes.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import chess

from chesscoach.analysis.analyzer import Analyzer
from chesscoach.concepts.matcher import match, views_after_move, views_for_position
from chesscoach.concepts.registry import Registry
from chesscoach.learner.mastery import ConceptMastery, Opportunity, game_success
from chesscoach.policy.policy import CoachingPolicy, CoachSessionState
from chesscoach.sparring.bot import SparringBot
from chesscoach.types import BotMove, CoachingEvent, ConceptHit, EngineResult, MoveAssessment

if TYPE_CHECKING:   # the store needs sqlite3 + fsrs; the browser build runs without it
    from chesscoach.learner.store import Store


@dataclass
class TurnResult:
    assessment: MoveAssessment
    event: Optional[CoachingEvent]
    queued: list[CoachingEvent]
    bot_move: Optional[BotMove] = None
    bot_san: Optional[str] = None
    waiting_for_takeback: bool = False
    game_over: bool = False


@dataclass
class _Logged:
    ply: int
    assessment: MoveAssessment
    hits: list[ConceptHit]
    event: Optional[CoachingEvent]
    bot_move: Optional[BotMove] = None
    available: list[ConceptHit] = field(default_factory=list)   # hits available before this move


class GameSession:
    def __init__(self, analyzer: Analyzer, registry: Registry, bot: SparringBot, policy: CoachingPolicy,
                 player_color: str = "white", band: str = "B1", player_id: str = "local",
                 store: Optional["Store"] = None, start_fen: str = chess.STARTING_FEN,
                 lesson_focus: Optional[str] = None, game_id: Optional[str] = None):
        self.analyzer, self.registry, self.bot, self.policy = analyzer, registry, bot, policy
        self.player_color, self.band, self.player_id, self.store = player_color, band, player_id, store
        self.board = chess.Board(start_fen)
        self.start_fen = start_fen
        self.game_id = game_id or uuid.uuid4().hex
        self.state = CoachSessionState(game_id=self.game_id, lesson_focus=lesson_focus)
        if lesson_focus and lesson_focus in registry.concepts:
            self.bot.set_focus(lesson_focus, registry.get(lesson_focus).category)
        self._before: Optional[EngineResult] = None      # analysis of the current position
        self._available: list[ConceptHit] = []
        self._pending_bot = False
        self.log: list[_Logged] = []
        self._last_bot_move: Optional[chess.Move] = None
        self._last_bot_san: Optional[str] = None

    # ------------------------------------------------------------------ helpers
    @property
    def player_to_move(self) -> bool:
        return (self.board.turn == chess.WHITE) == (self.player_color == "white")

    def _refresh_available(self) -> None:
        """Analysis of the position with the player to move: hint material + pre-move prompts."""
        eng = self.analyzer.engine(self.board)
        pf = self.analyzer.features(self.board, eng)
        self._before = eng
        self._available = match(self.registry, views_for_position(self.board, eng, pf), self.band)

    def start(self) -> Optional[BotMove]:
        """Call once. If the bot has White, it moves first."""
        if not self.player_to_move:
            return self._bot_reply()
        self._refresh_available()
        return None

    def pre_move_prompt(self) -> Optional[CoachingEvent]:
        if self._before is None:
            return None
        return self.policy.pre_move_prompt(self.state, self.board.ply(), self._before, self._available)

    def hint(self) -> Optional[CoachingEvent]:
        return self.policy.request_hint(self.state, self.board.ply(), self._available)

    # ------------------------------------------------------------------ the pipeline
    def player_move(self, uci: str, clock_ms: Optional[int] = None) -> TurnResult:
        if not self.player_to_move or self._pending_bot:
            raise RuntimeError("not the player's turn")
        mv = chess.Move.from_uci(uci)
        if not self.board.is_legal(mv):
            raise ValueError(f"illegal move {uci}")
        board_before = self.board.copy()
        ply = self.board.ply()

        # 1–2. analyze + classify (reuse the analysis of the current position)
        before, after, assessment, pf_b, pf_a = self.analyzer.analyze(board_before.fen(), mv, before=self._before)
        # 3. match concepts
        hits = match(self.registry, views_after_move(board_before, mv, assessment, before, pf_b, after, pf_a), self.band)
        # 4. policy
        retry = self.state.active_hint is not None and self.state.takebacks and self.state.active_hint.ply == ply
        if retry:
            ev = self.policy.after_retry(self.state, ply, assessment)
            from chesscoach.policy.policy import PolicyOutput
            out = PolicyOutput(event=ev)
        else:
            out = self.policy.after_player_move(self.state, ply, assessment, hits, board_before, after,
                                                last_opponent_move=self._last_bot_move)
        self.board.push(mv)
        # 5. record
        entry = _Logged(ply, assessment, hits, out.event, available=list(self._available))
        self.log.append(entry)
        if self.store:
            # Available hits (position before the move, player to move) are logged with their role so
            # the weakness profile can count tactics found (06 §3).
            self.store.log_move(self.game_id, ply, asdict(assessment),
                                [asdict(h) for h in hits] + [asdict(h) for h in self._available],
                                asdict(out.event) if out.event else None, clock_ms=clock_ms,
                                phase=pf_b.phase, sharpness=before.sharpness)
        self.bot.observe_player_move(assessment.move_class,
                                     lesson_hit=any(h.concept_id == self.state.lesson_focus for h in hits))
        self._before = after

        res = TurnResult(assessment, out.event, out.queued)
        if self.board.is_game_over():
            res.game_over = True
            return res
        if out.event is not None and out.event.kind == "interrupt" and out.event.allow_takeback:
            self._pending_bot = True
            res.waiting_for_takeback = True
            return res
        # 6–7. bot reply + its analysis
        res.bot_move = self._bot_reply()
        res.bot_san = self._last_bot_san
        res.game_over = self.board.is_game_over()
        return res

    def _bot_reply(self) -> BotMove:
        bm = self.bot.choose(self.board)
        mv = chess.Move.from_uci(bm.move)
        self._last_bot_san = self.board.san(mv)
        _, after, a, _, _ = self.analyzer.analyze(self.board.fen(), mv, before=self._before)
        if self.log:
            self.log[-1].bot_move = bm
        if self.store and self.log:
            self.store.log_move(self.game_id, self.board.ply(), asdict(a), [], None, bot_move=asdict(bm))
        self.board.push(mv)
        self._last_bot_move = mv
        self._before = after
        self._pending_bot = False
        if not self.board.is_game_over():
            self._refresh_available()
        return bm

    def takeback(self) -> None:
        """Undo the player's last move (only while the bot is waiting after an interrupt)."""
        if not self._pending_bot:
            raise RuntimeError("takebacks are offered after an interrupt")
        self.board.pop()
        self._pending_bot = False
        self.policy.on_takeback(self.state)
        self._refresh_available()

    def resume(self) -> BotMove:
        """Player keeps the interrupted move; the bot replies."""
        if not self._pending_bot:
            raise RuntimeError("nothing to resume")
        return self._bot_reply()

    # ------------------------------------------------------------------ end of game (L5)
    def finish(self, mastery: dict[str, ConceptMastery], result: Optional[float] = None) -> dict[str, ConceptMastery]:
        """Mastery update after the game (06 §2). Returns the updated records. `result` is the player's
        score (1 / 0.5 / 0), stored with the game."""
        now = datetime.now(timezone.utc).isoformat()
        hint_levels = {}
        for h in self.state.hints_requested:
            if h["concept_id"]:
                hint_levels[(h["ply"], h["concept_id"])] = max(hint_levels.get((h["ply"], h["concept_id"]), 0), h["level"])
        for e in self.log:
            seen = set()
            for h in e.hits + e.available:
                if h.role not in ("missed", "allowed", "played", "available") or (h.concept_id, h.role) in seen:
                    continue
                seen.add((h.concept_id, h.role))
                lvl = hint_levels.get((e.ply, h.concept_id), 0)
                if h.role == "available":
                    via = next((ev.split("via:")[1] for ev in h.evidence if "via:" in ev), None)
                    found = via is not None and via == e.assessment.move
                    s = game_success("available", lvl) if found else 0.0
                else:
                    s = game_success(h.role, lvl)
                if s is None:
                    continue
                m = mastery.setdefault(h.concept_id, ConceptMastery(self.player_id, h.concept_id))
                m.record(Opportunity(success=s, source="game", hint_level=lvl, at=now))
                if self.store:
                    self.store.save_mastery(m)
        if self.store:
            self.store.save_game(self.game_id, self.player_id, self.player_color, self.start_fen,
                                 [m.uci() for m in self.board.move_stack], result, self.state.lesson_focus,
                                 self.state.concepts_mentioned, now)
        return mastery
