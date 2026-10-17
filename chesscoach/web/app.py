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

from chesscoach import config
from chesscoach.analysis.analyzer import Analyzer
from chesscoach.concepts.registry import Registry
from chesscoach.learner.accuracy import game_accuracy
from chesscoach.learner.bands import band_for
from chesscoach.learner.review import build_review
from chesscoach.policy.policy import CoachingPolicy, CoachSettings, LearnerView, load_fallback
from chesscoach.session import GameSession
from chesscoach.sparring.bot import OFFSET_START, BotConfig, SparringBot, bot_target
from chesscoach.sparring.steering import LessonScorer
from chesscoach.types import CoachingEvent
from chesscoach.web.bridge import Rpc, RpcEnginePool, RpcMaiaModel

BAD_CLASSES = ("inaccuracy", "mistake", "blunder")
BEST_LINE_PLIES = 6


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

    def review(self, moves_json: str, rating: int = 1200, show_drafts: bool = False,
               depth: Optional[int] = None) -> str:
        """Post-game review of a finished game for both sides (docs/06 §4; p2p page, ADR 0003).

        Every number comes from the engine through the same classification and accuracy code the
        native app uses. Moment summaries are concept or fallback templates, so they are empty
        unless approved or the visitor opted in to the developer preview (AGENTS rule 2)."""
        moves = json.loads(moves_json)
        depth = depth or int(config.get("engine.depth_review_web"))
        drafts = bool(show_drafts)
        band = band_for(rating)
        analyzer = Analyzer(self.pool, live=False)
        reviews = {c: build_review(moves, c, analyzer, self.registries[drafts], band, depth=depth,
                                   fallback=self.fallbacks[drafts]) for c in ("white", "black")}
        plies_out = []
        for p in reviews["white"].plies:          # identical engine data in both reviews (cached pool)
            a = p.assessment
            board = chess.Board(p.fen_before)
            best_line = []
            b2 = board.copy(stack=False)
            for u in a.best_line[:BEST_LINE_PLIES]:
                mv = chess.Move.from_uci(u)
                if not b2.is_legal(mv):
                    break
                best_line.append(b2.san(mv))
                b2.push(mv)
            wp_after_white = a.win_prob_after if a.mover == "white" else 1 - a.win_prob_after
            plies_out.append({
                "ply": p.ply, "move": p.move, "san": board.san(chess.Move.from_uci(p.move)), "mover": a.mover,
                "move_class": a.move_class, "loss": round(a.loss, 4),
                "wp_before": round(a.win_prob_before, 4), "wp_after": round(a.win_prob_after, 4),
                "wp_white_after": round(wp_after_white, 4), "best_move": a.best_move,
                "best_san": best_line[0] if best_line else None, "best_line_san": best_line, "phase": p.phase,
            })
        sides = {}
        for c, rv in reviews.items():
            mine = [p for p in rv.plies if p.is_player]
            sides[c] = {
                "accuracy": game_accuracy([p.assessment.win_prob_before for p in mine],
                                          [p.assessment.win_prob_after for p in mine]),
                "phase_accuracy": rv.phase_accuracy,
                "counts": {k: sum(p.assessment.move_class == k for p in mine) for k in BAD_CLASSES},
                "moments": [{"ply": m.ply, "move_class": m.move_class, "summary": m.summary,
                             "concept_id": m.concept_id, "unpunished": m.unpunished} for m in rv.moments],
            }
        first = reviews["white"].plies[0].assessment if moves else None
        return json.dumps({
            "depth": depth, "engine": self.pool.version, "band": band,
            "wp_white_start": round(first.win_prob_before, 4) if first else 0.5,
            "plies": plies_out, "sides": sides,
        })
