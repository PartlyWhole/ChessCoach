"""Shared types — the contract between layers.

Mirrors docs/01-architecture.md exactly (snake_case field names). If you add a
field here, update 01 and every doc that references the type (AGENTS.md rule 5).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional

Color = Literal["white", "black"]
Square = str      # "e4"
UciMove = str     # "e2e4", "e7e8q"
Fen = str

Phase = Literal["opening", "middlegame", "endgame"]
MoveClass = Literal[
    "best", "excellent", "good", "inaccuracy", "mistake", "blunder", "book", "forced"
]
Role = Literal["missed", "allowed", "played", "available", "plan"]


def other(color: Color) -> Color:
    return "black" if color == "white" else "white"


# ---------- L1 output ----------
@dataclass
class EngineLine:
    moves: list[UciMove]          # principal variation
    cp: Optional[int]             # White POV; None if mate
    mate: Optional[int]           # White POV; +3 = White mates in 3
    win_prob: float               # White POV, 0..1
    depth: int


@dataclass
class EngineResult:
    fen: Fen
    lines: list[EngineLine]       # MultiPV, best first
    sharpness: float              # 0..1, see 02 §4
    tablebase: bool = False       # result comes from a Syzygy probe (02 §6.5)


@dataclass
class MoveAssessment:
    move: UciMove
    mover: Color
    win_prob_before: float        # mover POV
    win_prob_after: float         # mover POV
    loss: float                   # before - after, clamped >= 0
    move_class: MoveClass
    best_move: UciMove
    best_line: list[UciMove]


@dataclass
class Feature:
    id: str                       # detector feature id, e.g. "fork"
    side: Color                   # who the feature favours / belongs to (see 02 §6)
    squares: list[Square]
    pieces: Optional[list[Square]] = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ThreatInfo:
    by: Color
    move: UciMove                 # the threatening move
    gain_win_prob: float          # how much it would gain for `by`
    feature_ids: list[str]        # tactics the threat realises


@dataclass
class PositionFeatures:
    fen: Fen
    phase: Phase
    material: dict[str, float]    # {"white": .., "black": ..} pawn units
    features: list[Feature]
    threats: list[ThreatInfo]
    structure_id: Optional[str]


# ---------- L2 output ----------
@dataclass
class Highlight:
    squares: list[Square] = field(default_factory=list)
    arrows: list[tuple[Square, Square]] = field(default_factory=list)


@dataclass
class ConceptHit:
    concept_id: str
    role: Role
    importance: float
    slots: dict[str, str]
    highlight: Highlight
    evidence: list[str]


# ---------- L3 output ----------
@dataclass
class CoachingEvent:
    kind: Literal["interrupt", "comment", "praise", "hint", "queued_for_review"]
    concept_id: Optional[str]     # None for generic engine fallback
    hint_level: Literal[0, 1, 2, 3]
    text: str
    highlight: Highlight
    allow_takeback: bool


# ---------- L4 ----------
@dataclass
class BotMove:
    move: UciMove
    source: Literal["maia", "steer", "book", "engine_safety"]
    steer_concept_id: Optional[str] = None


def to_dict(obj: Any) -> Any:
    return asdict(obj)
