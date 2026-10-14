# 01 — Architecture and Shared Types

## Components

```
┌──────────────────────── Client (TS) ────────────────────────┐
│ Board UI · Coach panel · Hint button · Review screen · Drills│
└───────────────▲───────────────────────────────┬─────────────┘
                │ CoachingEvent, BotMove        │ PlayerMove
┌───────────────┴───────────────────────────────▼─────────────┐
│                   Game Session Orchestrator                  │
│  per move: analyze → match concepts → policy → bot reply     │
└──┬──────────────┬───────────────┬──────────────┬────────────┘
   │              │               │              │
┌──▼─────────┐ ┌──▼──────────┐ ┌──▼──────────┐ ┌─▼────────────┐
│ L1 Analysis│ │ L2 Concepts │ │ L3 Policy   │ │ L4 Sparring  │
│ Stockfish  │ │ registry +  │ │ speak/stay  │ │ Maia + steer │
│ detectors  │ │ templates   │ │ quiet, hints│ │ + engine     │
└──┬─────────┘ └─────────────┘ └──▲──────────┘ └──────────────┘
   │                              │ reads
┌──▼──────────────────────────────┴───────────────────────────┐
│ L5 Learner model: ratings, concept mastery, SRS cards,       │
│ weakness profile, post-game review builder                   │
└──────────────────────────────────────────────────────────────┘
```

## Per-move pipeline (player's turn just ended)

1. **Analyze** the position *before* and *after* the player's move (L1). Reuse the "after" analysis of the bot's previous move as this move's "before".
2. **Classify** the move by win-probability loss (L1).
3. **Match concepts** against both positions (L2). Produces candidate `ConceptHit`s.
4. **Policy** scores candidates against the learner model and decides: interrupt, comment, queue for review, or stay silent (L3).
5. **Record** the move, hits, and classification to the game log (L5 reads this later).
6. **Bot reply** (L4): choose a move, possibly steered toward an active lesson concept.
7. Analyze the bot's move too (for review and so the coach can say "watch out, it's threatening X").

Latency budget for steps 1–6: **< 1.5 s** at default settings. Engine work dominates; run the bot's move selection in parallel with the policy step.

## Shared types (the contract between layers)

These are written as TypeScript for readability. Mirror them exactly in Python
(dataclasses / pydantic). Field names are snake_case in both.

```ts
type Color = "white" | "black";
type Square = string;           // "e4"
type UciMove = string;          // "e2e4", "e7e8q"
type Fen = string;

// ---------- L1 output ----------
interface EngineLine {
  moves: UciMove[];             // principal variation
  cp: number | null;            // White POV; null if mate
  mate: number | null;          // White POV; +3 = White mates in 3
  win_prob: number;             // White POV, 0..1 (see 02)
  depth: number;
}

interface EngineResult {
  fen: Fen;
  lines: EngineLine[];          // MultiPV, best first
  sharpness: number;            // 0..1, see 02
  tablebase: boolean;           // true if from a Syzygy probe, see 02 §6.5
}

type MoveClass =
  | "best" | "excellent" | "good" | "inaccuracy" | "mistake" | "blunder"
  | "book" | "forced";

interface MoveAssessment {
  move: UciMove;
  mover: Color;
  win_prob_before: number;      // mover POV
  win_prob_after: number;       // mover POV
  loss: number;                 // before - after, clamped >= 0
  move_class: MoveClass;
  best_move: UciMove;
  best_line: UciMove[];
}

interface Feature {
  id: string;                   // detector feature id, e.g. "fork", "isolated_pawn"
  side: Color;                  // who the feature favours / belongs to
  squares: Square[];            // for board highlighting
  pieces?: Square[];            // squares of pieces involved
  data?: Record<string, unknown>;
}

interface PositionFeatures {
  fen: Fen;
  phase: "opening" | "middlegame" | "endgame";
  material: { white: number; black: number };   // pawn units
  features: Feature[];
  threats: ThreatInfo[];        // see 02 (null-move threat)
  structure_id: string | null;  // named pawn structure or null
}

interface ThreatInfo {
  by: Color;
  move: UciMove;                // the threatening move
  gain_win_prob: number;        // how much it would gain for `by`
  feature_ids: string[];        // tactics the threat realises
}

// ---------- L2 output ----------
interface ConceptHit {
  concept_id: string;
  role: "missed" | "allowed" | "played" | "available" | "plan";
  // missed:    player could have used it and didn't
  // allowed:   player's move let the opponent use it
  // played:    player used it (praise)
  // available: exists now, player to move (live hint material)
  // plan:      strategic suggestion from structure
  importance: number;           // 0..1 from concept record × context
  slots: Record<string, string>;// template fill values ("square": "d5")
  highlight: { squares: Square[]; arrows: [Square, Square][] };
  evidence: string[];           // feature ids / engine line that justify it
}

// ---------- L3 output ----------
interface CoachingEvent {
  kind: "interrupt" | "comment" | "praise" | "hint" | "queued_for_review";
  concept_id: string | null;    // null for generic engine fallback
  hint_level: 0 | 1 | 2 | 3;    // 0 = none yet; see 04 hint ladder
  text: string;                 // rendered template
  highlight: { squares: Square[]; arrows: [Square, Square][] };
  allow_takeback: boolean;
}

// ---------- L4 ----------
interface BotMove {
  move: UciMove;
  source: "maia" | "steer" | "book" | "engine_safety";
  steer_concept_id?: string;
}
```

L5 types (`LearnerProfile`, `ConceptMastery`, `ReviewCard`) are defined in
06 because only L3 and L5 use them.

## Services and process boundaries

- **Analysis service** (Python): owns Stockfish processes, detectors, concept matching. Stateless; cache by FEN + engine settings.
- **Bot service** (Python): owns Maia model(s). Stateless.
- **Session orchestrator**: stateful per game; can live in the analysis service at first.
- **Learner store**: DB tables for profile, mastery, cards, game logs.
- **Offline jobs**: puzzle mining from game databases, puzzle tagging, rating calibration, concept-library test runs.

Keep Stockfish in a pool of long-lived processes. Never spawn one per request.

## Caching

- Key: `fen4 + engine_version + depth + multipv`.
- Store `EngineResult` and `PositionFeatures` separately; detectors change more often than engine settings.
- Bump a `detector_version` constant whenever detector logic changes and include it in the features cache key.

## Configuration knobs (put these in one config module)

| Key | Default | Notes |
|-----|---------|-------|
| `engine.depth_live` | 16 | per-move live analysis |
| `engine.depth_review` | 22 | post-game review |
| `engine.multipv` | 3 | needed for sharpness and "only move" checks |
| `engine.threads` | 2 | per process |
| `engine.time_live` | 0.35 s | live searches stop at depth *or* this time, whichever first. Added because depth 16 × MultiPV 3 takes 2–5 s per tactical position on an M1, far over the 1.5 s budget. Review and tests use depth only. |
| `engine.time_threat` | 0.15 s | same cap for the live null-move threat search |
| `policy.max_comments_per_10_moves` | 3 | see 04 |
| `bot.temperature` | 1.0 | Maia sampling temperature, see 05 |
| `steer.max_win_prob_cost` | 0.05 | max eval the bot may give up to steer, see 05 |
| `steer.max_win_prob_cost_tactic` | 0.15 | higher cap for deliberately allowing a tactic, max once per game, see 05 |
