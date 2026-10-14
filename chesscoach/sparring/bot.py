"""Layer 4: the sparring partner (docs/05). Human-like, level-matched, never absurd, and able to
steer cheaply toward the game's lesson concept."""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Callable, Optional

import chess

from chesscoach import config
from chesscoach.analysis.board_utils import VALUE, cname, is_hanging
from chesscoach.analysis.book import TreeBook
from chesscoach.analysis.engine import EnginePool
from chesscoach.analysis.winprob import line_wp
from chesscoach.sparring.human_model import HumanMoveModel
from chesscoach.sparring.openings import lesson_line_move, tree_move
from chesscoach.types import BotMove

log = logging.getLogger(__name__)

MIN_PROB = 0.02             # drop sampled moves below this (05 §1 Sampling)
STEER_MIN_PROB = 0.05       # steering candidates must be human-plausible
STEER_EVERY = 4             # never steer more than once every 4 bot moves
GUARD_TRIES = 3
GUARD_QUEEN_ELO = 1200
GUARD_LOSS_ELO = 1600
GUARD_MAX_LOSS = 0.40


def sample(probs: dict[str, float], temperature: float, rng: random.Random) -> Optional[str]:
    """p ** (1/T), normalise, drop p < 0.02, renormalise, sample."""
    if not probs:
        return None
    w = {m: p ** (1 / temperature) for m, p in probs.items() if p > 0}
    z = sum(w.values())
    w = {m: x / z for m, x in w.items()}
    kept = {m: x for m, x in w.items() if x >= MIN_PROB} or {max(w, key=w.get): 1.0}
    r = rng.uniform(0, sum(kept.values()))
    acc = 0.0
    for m, x in sorted(kept.items(), key=lambda kv: -kv[1]):
        acc += x
        if r <= acc:
            return m
    return max(kept, key=kept.get)


def hangs_queen(board: chess.Board, move: chess.Move) -> bool:
    b = board.copy(stack=False)
    b.push(move)
    return any(is_hanging(b, q) for q in b.pieces(chess.QUEEN, board.turn))


def allows_mate_in_one(board: chess.Board, move: chess.Move) -> bool:
    b = board.copy(stack=False)
    b.push(move)
    for reply in b.legal_moves:
        b.push(reply)
        mate = b.is_checkmate()
        b.pop()
        if mate:
            return True
    return False


@dataclass
class SteerState:
    focus: Optional[str] = None             # lesson concept id
    focus_category: Optional[str] = None
    bot_moves: int = 0
    last_steer_at: int = -STEER_EVERY
    tactic_steer_used: bool = False
    pending: Optional[str] = None           # concept a just-played steer move was aiming at
    log: list[dict] = field(default_factory=list)


LessonScore = Callable[[chess.Board, chess.Move, str, str], float]
"""(board_before_bot_move, bot_move, concept_id, category) -> lesson_gain (0..1)."""


@dataclass
class BotConfig:
    bot_elo: int
    player_elo: int
    temperature: float = float(config.get("bot.temperature"))
    max_cost: float = float(config.get("steer.max_win_prob_cost"))
    max_cost_tactic: float = float(config.get("steer.max_win_prob_cost_tactic"))


class SparringBot:
    def __init__(self, model: HumanMoveModel, pool: Optional[EnginePool], cfg: BotConfig,
                 rng: Optional[random.Random] = None, lesson_score: Optional[LessonScore] = None,
                 opening_tree: Optional[TreeBook] = None, lesson_structure: Optional[str] = None,
                 repertoire_lines: Optional[list[list[str]]] = None):
        self.model, self.pool, self.cfg = model, pool, cfg
        self.rng = rng or random.Random()
        self.lesson_score = lesson_score
        self.tree = opening_tree
        self.lesson_structure = lesson_structure
        self.repertoire = repertoire_lines
        self.steer = SteerState()

    def set_focus(self, concept_id: Optional[str], category: Optional[str]) -> None:
        self.steer.focus, self.steer.focus_category = concept_id, category

    # ------------------------------------------------------------ main entry
    def choose(self, board: chess.Board) -> BotMove:
        self.steer.bot_moves += 1
        self.steer.pending = None
        played = [m.uci() for m in board.move_stack]
        color = "white" if board.turn == chess.WHITE else "black"

        # Opening: repertoire line → lesson-structure line → band opening tree.
        for mv in (self._line(self.repertoire, played),
                   lesson_line_move(self.lesson_structure, color, played, self.rng) if self.lesson_structure else None,
                   tree_move(self.tree, board, self.rng) if self.tree else None):
            if mv and board.is_legal(chess.Move.from_uci(mv)):
                return BotMove(move=mv, source="book")

        probs = self.model.move_probs(board, self.cfg.bot_elo, self.cfg.player_elo)
        steered = self._try_steer(board, probs)
        if steered is not None:
            return steered
        return self._sample_guarded(board, probs)

    def _line(self, lines, played) -> Optional[str]:
        if not lines:
            return None
        from chesscoach.sparring.openings import line_move
        return line_move(lines, played, self.rng)

    # ------------------------------------------------------------ sampling + sanity guard
    def _sample_guarded(self, board: chess.Board, probs: dict[str, float]) -> BotMove:
        top = max(probs, key=probs.get)
        for _ in range(GUARD_TRIES):
            mv = sample(probs, self.cfg.temperature, self.rng)
            if mv is None:
                break
            if not self._absurd(board, chess.Move.from_uci(mv)):
                return BotMove(move=mv, source="maia")
        # 3 rejected samples → the most likely move that passes the guard; Maia's top move only
        # if every move fails it (05 says "Maia's top move"; that move can itself be the absurd one).
        for mv in sorted(probs, key=probs.get, reverse=True):
            if not self._absurd(board, chess.Move.from_uci(mv)):
                return BotMove(move=mv, source="engine_safety")
        return BotMove(move=top, source="engine_safety")

    def _absurd(self, board: chess.Board, move: chess.Move) -> bool:
        """05 §1 Sanity guard. Below 1200 everything is allowed: beginners must see hanging pieces."""
        elo = self.cfg.bot_elo
        if elo >= GUARD_QUEEN_ELO and (hangs_queen(board, move) or allows_mate_in_one(board, move)):
            return True
        if elo >= GUARD_LOSS_ELO and self.pool is not None:
            me = cname(board.turn)
            res = self.pool.analyse(board, multipv=int(config.get("engine.multipv")),
                                    time=float(config.get("engine.time_threat")))
            after = board.copy(stack=False)
            after.push(move)
            res_after = self.pool.analyse(after, multipv=1, time=float(config.get("engine.time_threat")))
            if res.lines and res_after.lines:
                if line_wp(res.lines[0], me) - line_wp(res_after.lines[0], me) > GUARD_MAX_LOSS:
                    return True
        return False

    # ------------------------------------------------------------ lesson steering (05 §3)
    def _try_steer(self, board: chess.Board, probs: dict[str, float]) -> Optional[BotMove]:
        s = self.steer
        if not s.focus or self.lesson_score is None or self.pool is None:
            return None
        if s.bot_moves - s.last_steer_at < STEER_EVERY:
            return None
        is_tactic = s.focus_category == "tactic"
        if is_tactic and s.tactic_steer_used:
            return None
        cands = [m for m, p in probs.items() if p >= STEER_MIN_PROB]
        if not cands:
            return None
        me = cname(board.turn)
        res = self.pool.analyse(board, multipv=max(len(cands), 1),
                                time=float(config.get("engine.time_live")))
        if not res.lines:
            return None
        best_wp = line_wp(res.lines[0], me)
        wp_of = {l.moves[0]: line_wp(l, me) for l in res.lines if l.moves}
        cap = self.cfg.max_cost_tactic if is_tactic else self.cfg.max_cost
        best_choice, best_val = None, None
        for m in cands:
            if m not in wp_of:
                continue                       # not evaluated → cannot prove it is cheap
            cost = best_wp - wp_of[m]
            if cost > cap:
                continue
            mv = chess.Move.from_uci(m)
            if self._absurd(board, mv):
                continue
            gain = self.lesson_score(board, mv, s.focus, s.focus_category or "")
            if gain <= 0:
                continue
            val = gain - 2 * cost
            if best_val is None or val > best_val:
                best_choice, best_val = (m, cost, gain), val
        if best_choice is None:
            return None
        m, cost, gain = best_choice
        s.last_steer_at = s.bot_moves
        s.pending = s.focus
        if is_tactic:
            s.tactic_steer_used = True
        entry = {"bot_move": s.bot_moves, "move": m, "concept_id": s.focus, "cost": round(cost, 4),
                 "gain": round(gain, 4)}
        s.log.append(entry)
        log.info("steer %s", entry)
        return BotMove(move=m, source="steer", steer_concept_id=s.focus)

    def observe_player_move(self, move_class: str, lesson_hit: bool) -> None:
        """05 §3: if the player answers a steer with a strong move that escapes the lesson,
        drop the focus for the rest of the game."""
        if self.steer.pending and not lesson_hit and move_class in ("best", "excellent"):
            self.steer.focus = None
        self.steer.pending = None


# ---------------------------------------------------------------- calibration (05 §1)
OFFSET_START = 50
OFFSET_STEP = 25


def bot_target(player_rating: float, offset: float) -> int:
    return int(round(player_rating + offset))


def update_offset(offset: float, last_scores: list[float]) -> float:
    """Keep the player's score over the last 10 games in 40–60%: raise the bot when the player
    scores more, lower it when less. Scores: 1 win, 0.5 draw, 0 loss."""
    recent = last_scores[-10:]
    if len(recent) < 5:
        return offset
    pct = sum(recent) / len(recent)
    if pct > 0.60:
        return offset + OFFSET_STEP
    if pct < 0.40:
        return offset - OFFSET_STEP
    return offset


def think_time(board: chess.Board, sharpness: float, clock_s: Optional[float] = None,
               rng: Optional[random.Random] = None) -> float:
    """05 §4: untimed 0.5–2.5 s scaled by (legal moves × sharpness); timed remaining/40 ± 30%."""
    rng = rng or random.Random()
    if clock_s is not None:
        return max(0.1, clock_s / 40 * rng.uniform(0.7, 1.3))
    complexity = min(1.0, board.legal_moves.count() * max(sharpness, 0.1) / 20)
    return 0.5 + 2.0 * complexity


# ---------------------------------------------------------------- endgame drills (05 §5)
class DrillDefender:
    """Scenario training from a FEN library. mode="technique": tablebase-perfect replies
    (engine at review depth when no tablebase is configured); mode="practical": the human model.
    The drill description must say which (05 §5)."""

    def __init__(self, mode: str, pool: Optional[EnginePool], tablebase=None,
                 model: Optional[HumanMoveModel] = None, cfg: Optional[BotConfig] = None,
                 rng: Optional[random.Random] = None):
        if mode not in ("technique", "practical"):
            raise ValueError(mode)
        self.mode, self.pool, self.tablebase, self.model, self.cfg = mode, pool, tablebase, model, cfg
        self.rng = rng or random.Random()

    def choose(self, board: chess.Board) -> BotMove:
        if self.mode == "practical" and self.model is not None and self.cfg is not None:
            mv = sample(self.model.move_probs(board, self.cfg.bot_elo, self.cfg.player_elo),
                        self.cfg.temperature, self.rng)
            if mv:
                return BotMove(move=mv, source="maia")
        if self.tablebase is not None:
            res = self.tablebase.probe(board)
            if res is not None and res.lines:
                return BotMove(move=res.lines[0].moves[0], source="engine_safety")
        res = self.pool.analyse(board, depth=int(config.get("engine.depth_review")), multipv=1)
        return BotMove(move=res.lines[0].moves[0], source="engine_safety")
