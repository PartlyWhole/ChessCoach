"""JSON API the web page drives (ADR 0002). Every method returns a JSON string.

The page decides whether unreviewed (draft) coaching text may be shown: AGENTS rule 2 forbids
shipping unapproved text, so `show_drafts` defaults to False and the page only enables it after
the visitor opts in to the developer preview.
"""
from __future__ import annotations

import json
import random
from dataclasses import asdict
from typing import Optional

import chess

from chesscoach.analysis.analyzer import Analyzer
from chesscoach.concepts.registry import Registry
from chesscoach.learner.bands import band_for
from chesscoach.policy.policy import CoachingPolicy, CoachSettings, LearnerView, load_fallback
from chesscoach.session import GameSession
from chesscoach.sparring.bot import OFFSET_START, BotConfig, SparringBot, bot_target
from chesscoach.sparring.steering import LessonScorer
from chesscoach.types import CoachingEvent
from chesscoach.web.bridge import Rpc, RpcEnginePool, RpcMaiaModel


def _event(ev: Optional[CoachingEvent]) -> Optional[dict]:
    if ev is None:
        return None
    d = asdict(ev)
    d["highlight"]["arrows"] = [list(a) for a in d["highlight"]["arrows"]]
    return d


class WebApp:
    def __init__(self, rpc: Rpc, seed: Optional[int] = None):
        self.pool = RpcEnginePool(rpc)
        self.maia = RpcMaiaModel(rpc)
        self.rng = random.Random(seed)
        self.session: Optional[GameSession] = None
        self.registries = {flag: Registry.load(allow_unreviewed=flag) for flag in (False, True)}
        self.fallbacks = {flag: load_fallback(allow_unreviewed=flag) for flag in (False, True)}

    def _state(self, **extra) -> str:
        s = self.session
        b = s.board
        out = {
            "fen": b.fen(),
            "turn": "white" if b.turn == chess.WHITE else "black",
            "player_color": s.player_color,
            "legal": [m.uci() for m in b.legal_moves] if s.player_to_move and not s._pending_bot else [],
            "game_over": b.is_game_over(),
            "result": b.result(claim_draw=True) if b.is_game_over() else None,
            "last_move": b.move_stack[-1].uci() if b.move_stack else None,
            "concepts_loaded": len(s.registry),
        }
        out.update(extra)
        return json.dumps(out)

    def new_game(self, color: str = "white", rating: int = 1000, mode: str = "standard",
                 show_drafts: bool = False) -> str:
        band = band_for(rating)
        reg = self.registries[bool(show_drafts)]
        analyzer = Analyzer(self.pool, live=True)
        bot = SparringBot(self.maia, self.pool, BotConfig(bot_target(rating, OFFSET_START), rating), self.rng,
                          lesson_score=LessonScorer(analyzer, reg, band))
        policy = CoachingPolicy(reg, CoachSettings(mode=mode), LearnerView(band=band),
                                fallback=self.fallbacks[bool(show_drafts)])
        self.session = GameSession(analyzer, reg, bot, policy, player_color=color, band=band)
        first = self.session.start()
        return self._state(bot_move=first.move if first else None, band=band, bot_elo=bot.cfg.bot_elo)

    def move(self, uci: str) -> str:
        r = self.session.player_move(uci)
        a = r.assessment
        return self._state(
            assessment={"move": a.move, "move_class": a.move_class, "loss": round(a.loss, 3),
                        "best_move": a.best_move},
            event=_event(r.event), bot_move=r.bot_move.move if r.bot_move else None,
            bot_source=r.bot_move.source if r.bot_move else None, bot_san=r.bot_san,
            waiting_for_takeback=r.waiting_for_takeback)

    def hint(self) -> str:
        return self._state(event=_event(self.session.hint()))

    def pre_move_prompt(self) -> str:
        return self._state(event=_event(self.session.pre_move_prompt()))

    def takeback(self) -> str:
        self.session.takeback()
        return self._state()

    def resume(self) -> str:
        bm = self.session.resume()
        return self._state(bot_move=bm.move, bot_source=bm.source, bot_san=self.session._last_bot_san)
