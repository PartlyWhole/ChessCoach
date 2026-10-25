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
from chesscoach.analysis.lines import explain_line
from chesscoach.concepts.registry import Registry
from chesscoach.learner.accuracy import game_accuracy
from chesscoach.learner.bands import band_for
from chesscoach.learner.review import build_review
from chesscoach.learner.drill import DrillAttempt
from chesscoach.learner.service import LearnerService, card_dict
from chesscoach.policy.policy import CoachingPolicy, CoachSettings, LearnerView, load_fallback
from chesscoach.session import GameSession
from chesscoach.sparring.bot import OFFSET_START, BotConfig, SparringBot, bot_target
from chesscoach.sparring.openings import band_tree
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
    def __init__(self, rpc: Rpc, seed: Optional[int] = None, store_path: Optional[str] = None,
                 player_id: str = "local"):
        self.pool = RpcEnginePool(rpc)
        self.maia = RpcMaiaModel(rpc)
        self.rng = random.Random(seed)
        self.session: Optional[GameSession] = None
        self._drafts, self._bot_elo, self._resigned, self._finished = False, 0, False, None
        self.registries = {flag: Registry.load(allow_unreviewed=flag) for flag in (False, True)}
        self.fallbacks = {flag: load_fallback(allow_unreviewed=flag) for flag in (False, True)}
        # Learner store (ADR 0004): SQLite, in the browser on IndexedDB-backed storage.
        self.store_path = store_path
        self.learner: Optional[LearnerService] = None
        self._queue: dict = {}                  # card_id → ReviewCard for the current drill queue
        self._drill: Optional[DrillAttempt] = None
        self._drill_result: Optional[dict] = None
        from chesscoach.learner.puzzles import PuzzleBank
        self.puzzles = PuzzleBank.load_default()  # drill puzzles (06 §6), None without a built bank
        if store_path is not None:
            from chesscoach.learner.store import Store
            self.learner = LearnerService(Store(store_path), player_id)

    def _state(self, **extra) -> str:
        s = self.session
        b = s.board
        out = {
            "fen": b.fen(),
            "turn": "white" if b.turn == chess.WHITE else "black",
            "player_color": s.player_color,
            "legal": [m.uci() for m in b.legal_moves]
            if s.player_to_move and not s._pending_bot and self._result() is None else [],
            "game_over": self._result() is not None,
            "result": self._result(),
            "resigned": self._resigned,
            "last_move": b.move_stack[-1].uci() if b.move_stack else None,
            # Engine evaluation of the current position, White POV (for the optional eval bar).
            "eval_white": round(s._before.lines[0].win_prob, 4) if s._before and s._before.lines else None,
            "start_fen": s.start_fen,
            "moves": [m.uci() for m in b.move_stack],
            "concepts_loaded": len(s.registry),
        }
        out.update(extra)
        return json.dumps(out)

    def new_game(self, color: str = "white", rating: int = 1000, mode: str = "standard",
                 show_drafts: bool = False) -> str:
        """`rating` seeds the learner profile on the first game; after that the stored profile sets
        the band, bot strength and lesson focus (06, 05 §3)."""
        drafts = bool(show_drafts)
        reg = self.registries[drafts]
        band, player_elo, bot_elo = band_for(rating), rating, bot_target(rating, OFFSET_START)
        focus, mastery, recent, store, pid = None, {}, set(), None, "local"
        if self.learner is not None:
            p = self.learner.ensure(rating)
            band, player_elo, bot_elo = p.band, int(round(p.game_rating.rating)), self.learner.bot_elo(p)
            focus = self.learner.lesson_focus(reg, band)
            store, pid = self.learner.store, self.learner.player_id
            mastery = {k: m.state for k, m in store.load_mastery(pid).items()}
            recent = {c for g in store.games(pid, 3) for c in g["concepts_mentioned"]}
        analyzer = Analyzer(self.pool, live=True)
        bot = SparringBot(self.maia, self.pool, BotConfig(bot_elo, player_elo), self.rng,
                          lesson_score=LessonScorer(analyzer, reg, band), opening_tree=band_tree(band))
        policy = CoachingPolicy(reg, CoachSettings(mode=mode), LearnerView(band=band, mastery=mastery,
                                                                         recent_concepts=recent),
                                fallback=self.fallbacks[drafts])
        self.session = GameSession(analyzer, reg, bot, policy, player_color=color, band=band, player_id=pid,
                                   store=store, lesson_focus=focus)
        self._drafts, self._bot_elo, self._resigned, self._finished = drafts, bot_elo, False, None
        first = self.session.start()
        return self._state(bot_move=first.move if first else None, band=band, bot_elo=bot_elo,
                           lesson_focus=focus, lesson_title=reg.concepts[focus].title if focus else None)

    def resign(self) -> str:
        self._resigned = True
        return self._state()

    def finish_game(self) -> str:
        """After the game (or a resignation): review both sides at browser review depth (with line
        explanations), save the player's cards, update rating, band, bot offset and mastery."""
        if self._finished is not None:
            return self._finished
        s = self.session
        moves = [m.uci() for m in s.board.move_stack]
        result = self._result()
        score = {"1-0": 1.0, "0-1": 0.0}.get(result, 0.5)
        if s.player_color == "black":
            score = 1.0 - score
        depth = int(config.get("engine.depth_review_web"))
        reg = self.registries[self._drafts]
        analyzer = Analyzer(self.pool, live=False)
        pid = self.learner.player_id if self.learner else "local"
        reviews = {c: build_review(moves, c, analyzer, reg, s.band, player_id=pid, game_id=s.game_id, depth=depth,
                                   fallback=self.fallbacks[self._drafts]) for c in ("white", "black")}
        summary = None
        if self.learner is not None:
            summary = self.learner.finish_game(s, score, self._bot_elo, reviews[s.player_color])
        self._finished = json.dumps({"result": result, "score": score, "summary": summary,
                                     "review": self._review_payload(moves, reviews, depth, s.band)})
        return self._finished

    def _result(self) -> Optional[str]:
        b = self.session.board
        if self._resigned:
            return "0-1" if self.session.player_color == "white" else "1-0"
        return b.result(claim_draw=True) if b.is_game_over(claim_draw=True) else None

    def move(self, uci: str) -> str:
        board = self.session.board.copy()
        r = self.session.player_move(uci)
        a = r.assessment
        best = chess.Move.from_uci(a.best_move) if a.best_move else None
        reg = self.session.registry
        return self._state(
            assessment={"move": a.move, "move_class": a.move_class, "loss": round(a.loss, 3),
                        "best_move": a.best_move, "san": board.san(chess.Move.from_uci(a.move)),
                        "best_san": board.san(best) if best and board.is_legal(best) else None,
                        "win_prob_before": round(a.win_prob_before, 4), "win_prob_after": round(a.win_prob_after, 4)},
            # Ideas the coach noticed but kept for the review (04 step 5): titles only, no text, so
            # nothing is given away mid-game; only concepts in the loaded registry (approved/preview).
            queued=[{"concept_id": q.concept_id, "title": reg.concepts[q.concept_id].title}
                    for q in r.queued if q.concept_id in reg.concepts],
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
        return json.dumps(self._review_payload(moves, reviews, depth, band))

    def _review_payload(self, moves: list[str], reviews: dict, depth: int, band: str) -> dict:
        """JSON shape shared by the p2p analysis and the coach page's post-game review."""
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
            why = None
            if a.move_class in BAD_CLASSES:
                n = int(config.get("explain.max_plies"))
                why = {"played": asdict(explain_line(board, a.played_line[:n], a.mover)),
                       "best": asdict(explain_line(board, a.best_line[:n], a.mover))}
            plies_out.append({
                "why": why,
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
        return {
            "depth": depth, "engine": self.pool.version, "band": band,
            "wp_white_start": round(first.win_prob_before, 4) if first else 0.5,
            "plies": plies_out, "sides": sides,
        }

    # ------------------------------------------------------------------ learner (ADR 0004)
    def learner_state(self, show_drafts: bool = False) -> str:
        if self.learner is None:
            return json.dumps({"has_profile": False, "persistent": False})
        out = self.learner.summary(self.registries[bool(show_drafts)])
        out["persistent"] = self.store_path not in (None, ":memory:")
        return json.dumps(out)

    def reset_progress(self) -> str:
        """Delete everything the learner store holds for this player (profile, games, cards)."""
        if self.learner is not None:
            db = self.learner.store.db
            for table in ("learner_profile", "concept_mastery", "review_card", "game"):
                db.execute(f"DELETE FROM {table} WHERE player_id=?", (self.learner.player_id,))
            db.execute("DELETE FROM game_log_move WHERE game_id NOT IN (SELECT game_id FROM game)")
            db.commit()
        return self.learner_state()

    # ------------------------------------------------------------------ drills (06 §5, ADR 0004)
    def _band(self) -> str:
        p = self.learner.load() if self.learner else None
        return p.band if p else "B1"

    def drill_queue(self, show_drafts: bool = False) -> str:
        if self.learner is None:
            return json.dumps({"cards": [], "counts": {"total": 0, "new": 0, "due": 0}})
        reg = self.registries[bool(show_drafts)]
        p = self.learner.load()
        focus = self.learner.lesson_focus(reg, p.band) if p else None

        def puzzles(n):
            if self.puzzles is None or p is None:
                return []
            done = {c.source.get("puzzle_id") for c in self.learner.store.load_cards(self.learner.player_id)}
            return self.puzzles.pick(n, focus, p.drill_rating.rating, exclude=done, player_id=self.learner.player_id)

        q = self.learner.queue(puzzles)
        self._queue = {c.card_id: c for c in q}
        return json.dumps({"cards": [card_dict(c, reg) for c in q], "counts": self.learner.card_counts(),
                           "focus": focus})

    def drill_start(self, card_id: str, show_drafts: bool = False) -> str:
        card = self._queue.get(card_id)
        if card is None:
            raise ValueError("card not in the current queue")
        reg = self.registries[bool(show_drafts)]
        band = self._band()
        analyzer = Analyzer(self.pool, live=True)

        def hint_text(board, concept_ids, level):
            """Concept template text for this position, only if the concept matches here."""
            from chesscoach.concepts.matcher import match, views_for_position
            from chesscoach.concepts.render import render
            eng = analyzer.engine(board)
            hits = match(reg, views_for_position(board, eng, analyzer.features(board, eng)), band)
            for h in hits:
                if h.role == "available" and h.concept_id in concept_ids:
                    text = render(reg.get(h.concept_id), h, level)
                    if text:
                        return text
            return None

        self._drill = DrillAttempt(card, analyzer.engine, hint_text=hint_text)
        self._drill_result = None
        return json.dumps(self._drill.state(card=card_dict(card, reg), player_moves=self._drill.player_moves))

    def _drill_out(self, st: dict) -> str:
        d = self._drill
        if d.done and self._drill_result is None and self.learner is not None:
            rating = d.card.source.get("rating")
            self._drill_result = self.learner.record_drill(d.card, d.solved, d.max_hint_level(),
                                                           d.seconds_per_move(), puzzle_rating=rating)
            self._drill_result["counts"] = self.learner.card_counts()
        if d.done:
            st["graded"] = self._drill_result
        return json.dumps(st)

    def drill_move(self, uci: str) -> str:
        return self._drill_out(self._drill.move(uci))

    def drill_hint(self) -> str:
        return self._drill_out(self._drill.hint())

    def drill_show(self) -> str:
        return self._drill_out(self._drill.reveal())

    # ------------------------------------------------------------------ expert review page (AGENTS rule 2)
    def review_concepts(self) -> str:
        from chesscoach.concepts.review_tool import concept_list, fallback_detail
        return json.dumps({"concepts": concept_list(self.registries[True]), "fallback": fallback_detail()})

    def review_concept(self, concept_id: str, templates_json: str = "null") -> str:
        """The concept's templates and its test positions run through the matcher at browser review
        depth, with `templates_json` edits applied ({role: {level: text}}) and checked."""
        from chesscoach.concepts.review_tool import concept_detail
        reg = self.registries[True]
        out = concept_detail(reg.get(concept_id), reg, Analyzer(self.pool, live=False), json.loads(templates_json),
                             depth=int(config.get("engine.depth_review_web")))
        out["engine"] = f"{self.pool.version}, depth {config.get('engine.depth_review_web')}"
        return json.dumps(out)
