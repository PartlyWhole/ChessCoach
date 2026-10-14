"""Layer 3: coaching policy (docs/04). Decides whether the coach speaks, about which single idea,
and how much it reveals. Default is silence.

Inputs per player move: MoveAssessment, ConceptHit[] (L2), the learner view (band, mastery,
lesson focus, concepts said in the last 3 games), session state, settings.
Output: zero or one shown CoachingEvent, plus queued_for_review events (stored, not shown).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

import chess
import yaml

from chesscoach import config
from chesscoach.concepts.registry import BANDS, Registry
from chesscoach.concepts.render import render
from chesscoach.types import CoachingEvent, ConceptHit, EngineResult, Highlight, MoveAssessment

FALLBACK_FILE = Path(__file__).resolve().parent.parent.parent / "templates" / "en" / "_fallback.yaml"

VERBOSITY_BUDGET = {"low": 2, "normal": 3, "high": 5}
MAX_PRAISE_PER_GAME = 1          # "about once per game when earned" (04 Tone rules)
PRE_MOVE_GAP = 5                 # no pre-move prompt in the last 5 player moves
RETRY_ATTEMPTS = 2               # attempts after a takeback before level 3 auto-reveals
BLITZ_LIMIT_S = 600              # games faster than 10+0 force silent mode


@dataclass
class CoachSettings:
    mode: Literal["guided", "standard", "silent"] = "standard"
    interrupt_blunders: bool = True
    allow_takebacks: bool = True
    verbosity: Literal["low", "normal", "high"] = "normal"
    praise: bool = True


@dataclass
class HintSession:
    ply: int
    concept_id: Optional[str]       # None → engine/threat fallback
    hit: Optional[ConceptHit]
    level: int
    attempts: int = 0
    fallback: Optional[str] = None  # "engine" | "threat"
    slots: dict = field(default_factory=dict)


@dataclass
class CoachSessionState:
    """Persisted per game (04 "Session state to persist")."""
    game_id: str
    player_moves: int = 0
    comment_ply_history: list[int] = field(default_factory=list)
    concepts_mentioned: list[str] = field(default_factory=list)
    hints_requested: list[dict] = field(default_factory=list)
    takebacks: int = 0
    lesson_focus: Optional[str] = None
    # Additions (documented in 04): needed to apply the rules above.
    player_move_plies: list[int] = field(default_factory=list)   # ply of each player move
    pre_move_prompt_plies: list[int] = field(default_factory=list)
    praise_count: int = 0
    active_hint: Optional[HintSession] = None


@dataclass
class LearnerView:
    """What L3 reads from L5 (06)."""
    band: str = "B1"
    mastery: dict[str, str] = field(default_factory=dict)        # concept_id → new|learning|practised|mastered
    recent_concepts: set[str] = field(default_factory=set)       # mentioned in the last 3 games


@dataclass
class PolicyOutput:
    event: Optional[CoachingEvent] = None
    queued: list[CoachingEvent] = field(default_factory=list)


def is_fast_time_control(base_s: Optional[float], increment_s: float = 0.0) -> bool:
    """Estimated game length base + 40·increment under 10 minutes → faster than 10+0."""
    return base_s is not None and base_s + 40 * increment_s < BLITZ_LIMIT_S


def load_fallback(allow_unreviewed: Optional[bool] = None) -> dict[str, dict[int, str]]:
    if allow_unreviewed is None:
        allow_unreviewed = os.environ.get("CHESSCOACH_ALLOW_UNREVIEWED") == "1"
    doc = yaml.safe_load(FALLBACK_FILE.read_text())
    if doc.get("review", {}).get("status") != "approved" and not allow_unreviewed:
        return {}
    return {k: {int(lv): t for lv, t in v.items()} for k, v in doc["templates"].items()}


class CoachingPolicy:
    def __init__(self, registry: Registry, settings: Optional[CoachSettings] = None,
                 learner: Optional[LearnerView] = None, time_control: Optional[tuple[float, float]] = None,
                 fallback: Optional[dict] = None):
        self.registry = registry
        self.settings = settings or CoachSettings()
        self.learner = learner or LearnerView()
        self.fallback = load_fallback() if fallback is None else fallback
        if time_control is not None and is_fast_time_control(*time_control):
            self.settings.mode = "silent"

    # ------------------------------------------------------------------ scoring
    def relevance(self, concept_id: str, state: CoachSessionState) -> float:
        if state.lesson_focus == concept_id:
            return 1.5
        m = self.learner.mastery.get(concept_id, "new")
        # 04 gives mastered 0.3 and weak 1.0; practised sits between (our choice, see 04).
        return {"mastered": 0.3, "practised": 0.65}.get(m, 1.0)

    def band_fit(self, concept_id: str) -> float:
        bands = self.registry.get(concept_id).bands
        i = BANDS.index(self.learner.band)
        if self.learner.band in bands or any(BANDS.index(b) < i for b in bands):
            return 1.0             # in band, or a below-band basic the player still got wrong
        if i + 1 < len(BANDS) and BANDS[i + 1] in bands:
            return 0.5
        return 0.0

    def novelty(self, concept_id: str, state: CoachSessionState) -> float:
        if concept_id in state.concepts_mentioned:
            return 0.0
        if concept_id in self.learner.recent_concepts:
            return 0.5
        return 1.0

    def score(self, hit: ConceptHit, state: CoachSessionState) -> float:
        return (hit.importance * self.relevance(hit.concept_id, state)
                * self.band_fit(hit.concept_id) * self.novelty(hit.concept_id, state))

    def budget(self) -> int:
        if self.settings.verbosity == "normal":
            return int(config.get("policy.max_comments_per_10_moves"))
        return VERBOSITY_BUDGET[self.settings.verbosity]

    # ------------------------------------------------------------------ rendering
    def start_level(self, concept_id: str) -> int:
        if self.learner.mastery.get(concept_id, "new") == "new" and self.learner.band in ("B0", "B1"):
            return 2
        return 1

    def _render_at_or_above(self, hit: ConceptHit, level: int, allow_3: bool) -> Optional[tuple[int, str]]:
        concept = self.registry.get(hit.concept_id)
        for lv in range(level, 4):
            if lv == 3 and not allow_3:
                break
            text = render(concept, hit, lv)
            if text is not None:
                return lv, text
        return None

    def _fallback_text(self, kind: str, level: int, slots: dict) -> Optional[str]:
        text = self.fallback.get(kind, {}).get(level)
        if text is None:
            return None
        try:
            return text.format(**slots)
        except KeyError:
            return None

    @staticmethod
    def fallback_slots(board_before: chess.Board, assessment: MoveAssessment,
                       engine_after: Optional[EngineResult]) -> dict[str, str]:
        """Slots for the engine/threat fallback, all read from engine output."""
        from chesscoach.concepts.matcher import _san
        s: dict[str, str] = {}
        if assessment.best_line:
            best = chess.Move.from_uci(assessment.best_line[0])
            if board_before.is_legal(best):
                s["best_san"] = board_before.san(best)
                s["best_from"] = chess.square_name(best.from_square)
                pv = _san(board_before, [chess.Move.from_uci(m) for m in assessment.best_line], limit=6)
                if pv:
                    s["pv_san"] = pv
        after = board_before.copy(stack=False)
        after.push(chess.Move.from_uci(assessment.move))
        if engine_after and engine_after.lines and engine_after.lines[0].moves:
            reply = chess.Move.from_uci(engine_after.lines[0].moves[0])
            if after.is_legal(reply):
                s["reply_san"] = after.san(reply)
                s["reply_from"] = chess.square_name(reply.from_square)
        return s

    # ------------------------------------------------------------------ events
    def _event(self, kind, hit: Optional[ConceptHit], level: int, text: str, allow_takeback=False,
               highlight: Optional[Highlight] = None) -> CoachingEvent:
        hl = highlight or Highlight()
        if hit is not None and highlight is None:
            # Level 1 points at nothing on the board; 2 shows squares; 3 adds the arrow.
            if level >= 2 or level == 0:
                hl = Highlight(squares=list(hit.highlight.squares),
                               arrows=list(hit.highlight.arrows) if level in (0, 3) else [])
        return CoachingEvent(kind=kind, concept_id=hit.concept_id if hit else None, hint_level=level,
                             text=text, highlight=hl, allow_takeback=allow_takeback)

    def _queue(self, hits: list[ConceptHit]) -> list[CoachingEvent]:
        out = []
        for h in hits:
            if h.role not in ("missed", "allowed"):
                continue
            concept = self.registry.get(h.concept_id)
            text = render(concept, h, 3) or ""
            out.append(CoachingEvent(kind="queued_for_review", concept_id=h.concept_id, hint_level=3, text=text,
                                     highlight=h.highlight, allow_takeback=False))
        return out

    def _record(self, state: CoachSessionState, ply: int, concept_id: Optional[str]) -> None:
        state.comment_ply_history.append(ply)
        if concept_id and concept_id not in state.concepts_mentioned:
            state.concepts_mentioned.append(concept_id)

    def _comments_in_last_10(self, state: CoachSessionState) -> int:
        recent = state.player_move_plies[-10:]
        if not recent:
            return 0
        return sum(1 for p in state.comment_ply_history if p >= recent[0])

    # ------------------------------------------------------------------ after a player move
    def after_player_move(self, state: CoachSessionState, ply: int, assessment: MoveAssessment,
                          hits: list[ConceptHit], board_before: chess.Board,
                          engine_after: Optional[EngineResult] = None,
                          last_opponent_move: Optional[chess.Move] = None) -> PolicyOutput:
        state.player_moves += 1
        state.player_move_plies.append(ply)
        state.active_hint = None
        out = PolicyOutput()
        cls = assessment.move_class

        if self.settings.mode == "silent":
            out.queued = self._queue(hits)
            return out

        # 1. HARD INTERRUPT
        if cls == "blunder" and self.settings.interrupt_blunders:
            cands = sorted((h for h in hits if h.role in ("allowed", "missed") and self.band_fit(h.concept_id) > 0),
                           key=lambda h: self.score(h, state) or h.importance * 0.01, reverse=True)
            takeback = self.settings.allow_takebacks
            for h in cands:
                r = self._render_at_or_above(h, 1, allow_3=False)
                if r:
                    lv, text = r
                    out.event = self._event("interrupt", h, lv, text, allow_takeback=takeback)
                    state.active_hint = HintSession(ply, h.concept_id, h, lv)
                    break
            else:
                slots = self.fallback_slots(board_before, assessment, engine_after)
                kind = "threat" if "reply_san" in slots else "engine"
                text = self._fallback_text(kind, 1, slots)
                if text:
                    out.event = CoachingEvent("interrupt", None, 1, text, Highlight(), takeback)
                    state.active_hint = HintSession(ply, None, None, 1, fallback=kind, slots=slots)
            if out.event:
                self._record(state, ply, out.event.concept_id)
            out.queued = self._queue([h for h in hits if out.event is None or h.concept_id != out.event.concept_id])
            return out

        # 2. SCORE
        scored = [(self.score(h, state), h) for h in hits if self.band_fit(h.concept_id) > 0]
        scored = [(s, h) for s, h in scored if not (h.role == "played" and not self._praise_ok(state, assessment, board_before, last_opponent_move))]

        # 3. BUDGET
        if self._comments_in_last_10(state) >= self.budget():
            out.queued = self._queue(hits)
            return out
        threshold = 0.35 if cls in ("mistake", "inaccuracy") else 0.55

        # 4. CHOOSE (best renderable candidate above threshold)
        chosen = None
        for s, h in sorted(scored, key=lambda x: x[0], reverse=True):
            if s < threshold:
                break
            if h.role == "played":
                text = render(self.registry.get(h.concept_id), h, 0)
                if text:
                    chosen = self._event("praise", h, 0, text)
                    state.praise_count += 1
                    break
            else:
                r = self._render_at_or_above(h, self.start_level(h.concept_id), allow_3=False)
                if r:
                    chosen = self._event("comment", h, r[0], r[1])
                    state.active_hint = HintSession(ply, h.concept_id, h, r[0])
                    break
        if chosen is None and cls == "mistake" and not any(s >= threshold for s, _ in scored):
            chosen = self._fallback_comment(state, ply, board_before, assessment, engine_after)
        out.event = chosen
        if chosen is not None:
            self._record(state, ply, chosen.concept_id)

        # 5. QUEUE the rest of the missed/allowed hits
        out.queued = self._queue([h for h in hits if chosen is None or h.concept_id != chosen.concept_id])
        return out

    def _fallback_comment(self, state, ply, board_before, assessment, engine_after) -> Optional[CoachingEvent]:
        """04 Fallback: threat hit → engine line → silence (quiet position, loss < 0.10)."""
        if assessment.loss < 0.10:
            return None
        slots = self.fallback_slots(board_before, assessment, engine_after)
        kind = "threat" if "reply_san" in slots else "engine"
        text = self._fallback_text(kind, 1, slots)
        if not text:
            return None
        state.active_hint = HintSession(ply, None, None, 1, fallback=kind, slots=slots)
        return CoachingEvent("comment", None, 1, text, Highlight(), False)

    def _praise_ok(self, state, assessment: MoveAssessment, board_before: chess.Board,
                   last_opponent_move: Optional[chess.Move]) -> bool:
        if not self.settings.praise or state.praise_count >= MAX_PRAISE_PER_GAME:
            return False
        if assessment.move_class == "forced":
            return False
        if assessment.move_class not in ("best", "excellent", "good"):
            return False
        mv = chess.Move.from_uci(assessment.move)
        if last_opponent_move is not None and mv.to_square == last_opponent_move.to_square \
                and board_before.is_capture(mv):
            return False              # obvious recapture
        return True

    # ------------------------------------------------------------------ hint ladder
    def request_hint(self, state: CoachSessionState, ply: int,
                     available_hits: Optional[list[ConceptHit]] = None) -> Optional[CoachingEvent]:
        """Hint button: advance the active hint one level, or open a new hint session from the best
        `available` hit. Each press is recorded (06 uses hint depth)."""
        h = state.active_hint
        if h is None and available_hits:
            cands = sorted((x for x in available_hits if x.role == "available" and self.band_fit(x.concept_id) > 0),
                           key=lambda x: self.score(x, state) or x.importance * 0.01, reverse=True)
            for x in cands:
                r = self._render_at_or_above(x, 1, allow_3=False)
                if r:
                    state.active_hint = HintSession(ply, x.concept_id, x, r[0])
                    state.hints_requested.append({"ply": ply, "concept_id": x.concept_id, "level": r[0]})
                    return self._event("hint", x, r[0], r[1])
            return None
        if h is None:
            return None
        nxt = h.level + 1
        if nxt > 3:
            return None
        ev = self._event_at(h, nxt, kind="hint")
        if ev is not None:
            state.hints_requested.append({"ply": ply, "concept_id": h.concept_id, "level": ev.hint_level})
        return ev

    def _event_at(self, h: HintSession, level: int, kind: str) -> Optional[CoachingEvent]:
        if h.hit is not None:
            r = self._render_at_or_above(h.hit, level, allow_3=True)
            if r is None:
                return None
            h.level = r[0]
            return self._event(kind, h.hit, r[0], r[1])
        for lv in range(level, 4):
            text = self._fallback_text(h.fallback or "engine", lv, h.slots)
            if text:
                h.level = lv
                return CoachingEvent(kind, None, lv, text, Highlight(), False)
        return None

    def on_takeback(self, state: CoachSessionState) -> None:
        state.takebacks += 1
        if state.active_hint is not None:
            state.active_hint.attempts = 0

    def after_retry(self, state: CoachSessionState, ply: int, assessment: MoveAssessment) -> Optional[CoachingEvent]:
        """After a takeback the player gets RETRY_ATTEMPTS tries; then level 3 auto-reveals.
        A retry that is no longer a mistake closes the hint session silently."""
        h = state.active_hint
        if h is None:
            return None
        if assessment.move_class not in ("inaccuracy", "mistake", "blunder"):
            state.active_hint = None
            return None
        h.attempts += 1
        if h.attempts >= RETRY_ATTEMPTS:
            ev = self._event_at(h, 3, kind="hint")
            state.active_hint = None
            return ev
        return None

    # ------------------------------------------------------------------ before the player moves
    def pre_move_prompt(self, state: CoachSessionState, ply: int, engine: EngineResult,
                        available_hits: list[ConceptHit]) -> Optional[CoachingEvent]:
        """Guided mode only: sharpness >= 0.8, an in-band available or threat-based hit, and no
        pre-move prompt in the last 5 player moves."""
        if self.settings.mode != "guided" or engine.sharpness < 0.8:
            return None
        recent = state.player_move_plies[-PRE_MOVE_GAP:]
        if any(p >= (recent[0] if recent else ply) for p in state.pre_move_prompt_plies):
            return None
        if not any(h.role == "available" and self.band_fit(h.concept_id) > 0 for h in available_hits):
            return None
        text = self._fallback_text("pre_move", 1, {})
        if not text:
            return None
        state.pre_move_prompt_plies.append(ply)
        return CoachingEvent("hint", None, 1, text, Highlight(), False)
