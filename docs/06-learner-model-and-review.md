# 06 — Layer 5: Learner Model, Post-Game Review, Spaced Repetition

## 1. Ratings (Glicko-2)

Use Glicko-2 for everything that is "player vs something":

- **Game rating**: player vs bot (bot's rating = its target Elo).
- **Puzzle/drill rating**: each drill attempt is a game between player and drill. Lichess uses this exact approach for puzzles — a failed puzzle counts as a win for the puzzle — so drill ratings self-calibrate as people attempt them.
- **Concept rating** (optional, v2): one rating per concept per player from attempts on drills tagged with it.

Glicko-2 is implemented in-repo from Glickman's paper
(`chesscoach/learner/glicko2.py`; tested against the paper's worked example), so
there is no dependency to record. Drill ratings start from the source puzzle's rating when imported from Lichess.

Map Glicko rating → band (03) using the player's game rating, with
hysteresis: move up a band only after 5 consecutive games above the
threshold, down after 10 below.

## 2. Data model

```ts
interface LearnerProfile {
  player_id: string;
  game_rating: Glicko;           // { rating, rd, vol }
  drill_rating: Glicko;
  band: "B0" | "B1" | "B2" | "B3" | "B4";
  bot_offset: number;            // see 05
  settings: CoachSettings;       // see 04
  repertoire: { white: string[]; black: string[] };   // opening tree ids
  band_tracker: { above: number; below: number };      // band hysteresis counters (§1)
}

interface ConceptMastery {
  player_id: string;
  concept_id: string;
  state: "new" | "learning" | "practised" | "mastered";
  opportunities: number;         // times the concept was available/relevant in their games
  successes: number;             // found / avoided without hints
  hint_depth_sum: number;        // sum of hint levels used
  last_seen_at: string;          // ISO date
  rating?: Glicko;               // v2
  history: { success: number; source: "game" | "drill"; hint_level: number; at: string }[];
                                 // recent opportunities (last 20 kept): the state rules below need windows
}

interface ReviewCard {
  card_id: string;
  player_id: string;
  kind: "find_move" | "avoid_mistake" | "opening_line" | "endgame_technique";
  fen: string;
  solution: UciMove[];           // player's moves only, with expected replies interleaved
  concept_ids: string[];
  source: { game_id?: string; ply?: number; puzzle_id?: string };
  srs: FsrsState;                // card state as defined by the FSRS library, see §5
}
// Glicko = { rating: number; rd: number; vol: number }
// CoachSettings: see 04 "Modes and settings"; UciMove, MoveAssessment, ConceptHit,
// CoachingEvent, BotMove: see 01

interface GameLogMove {
  game_id: string; ply: number;
  assessment: MoveAssessment;
  hits: ConceptHit[];
  coach_event: CoachingEvent | null;
  bot_move?: BotMove;
  clock_ms?: number;
  phase?: "opening" | "middlegame" | "endgame";   // of the position before the move (§3 metrics)
  sharpness?: number;                             // of that position (§3 "tactics found")
}
// `hits` of a player's move also carries the `available` hits of the position before it (role
// "available"), so "tactics found" can be computed from the log.
```

### Mastery update (after every game and drill)

For each concept hit in the game with role `missed`, `allowed`, `played`, or
`available`:

- `opportunities += 1`
- Success = role `played`, or role `available` where the player found it without hints, or a threat that existed and was parried.
- Weighted success for drills: 1.0 no hints, 0.6 after level 1, 0.3 after level 2, 0 after level 3.

State transitions (simple and explainable; tune later):

| From | To | When |
|------|----|------|
| new | learning | first opportunity |
| learning | practised | success rate ≥ 60% over last 8 opportunities |
| practised | mastered | success rate ≥ 85% over last 12 and ≥ 2 successes in real games (not drills) |
| any | learning | 3 failures in last 5 opportunities |

## 3. Weakness profile

Aggregate the game log into category scores so the app can say "this is what
to work on". Aimchess is the reference product: it scores six areas
(openings, tactics, endgames, advantage capitalization, resourcefulness, time
management) and compares them to players of similar rating. Our version:

| Metric | Definition |
|--------|-----------|
| Tactics found | % of `available` tactical hits (sharpness ≥ 0.6) the player converted |
| Tactics allowed | blunders with an `allowed` tactical hit per 100 moves |
| Opening | average win-prob loss in plies 1–24 |
| Conversion | % of games where player reached win prob ≥ 0.85 and won |
| Resourcefulness | % of games where player fell to ≤ 0.15 and drew or won |
| Endgame | average loss per move in endgame phase |
| Time trouble | % of mistakes made with < 10% of starting clock |
| Phase accuracy | per-phase accuracy (Lichess-style accuracy from win-prob loss; formula verified against lila `AccuracyPercent.scala`, see `chesscoach/learner/accuracy.py`) |

Compare each metric with the median of other players in the same band (needs
enough users; until then compare against fixed targets set by a coach). The draft
targets and the metric → concept-category mapping used for lesson focus are in
`chesscoach/learner/weakness.py` and need a coach's review.

The **lesson focus** for the next game (05) is chosen as: the lowest
`ConceptMastery` among concepts in the player's band whose category maps to
the worst weakness metric, excluding concepts mentioned in the last 2 games.

## 4. Post-game review

Builder runs after each game at `engine.depth_review` (01). The learning loop around it (profile,
rating, band, bot offset, mastery, cards, weakness profile, lesson focus, drills) is
`chesscoach/learner/service.py`; one drill attempt is `chesscoach/learner/drill.py` (alternatives
accepted only if they are the engine's best move or mate; a solve after a wrong try is graded at
least Hard). The browser build runs the same
builder at `engine.depth_review_web` for the peer-to-peer page's analysis, for both players and
without saving cards (ADR 0003).

1. Re-analyse all positions at review depth; recompute `MoveAssessment` and hits.
2. Select **2–3 critical moments**: rank plies by `loss × importance of best hit`, keep the top 3 with at least 4 plies between them. Always include the single largest swing.
3. For each moment, create an interactive exercise: start one ply **before** the player's move so they don't know exactly when the mistake happens (Lichess users asked for this in "Learn from your mistakes"), and use the hint ladder from 04.
4. Add a one-line summary per moment from the top concept's level-3 template.
5. Show phase accuracy and the one weakness metric that moved most.
6. Offer to save each moment as a `ReviewCard`. Default: save automatically for mistakes/blunders.

Also mine the **opponent's** mistakes that the player failed to punish
(`missed` hits) — these are often the most instructive.

## 5. Spaced repetition

Every `ReviewCard` is scheduled with spaced repetition.

**Recommended: FSRS** (Free Spaced Repetition Scheduler). It models memory with
difficulty, stability and retrievability, adapts to the individual, and has
maintained open-source implementations including `py-fsrs` and `ts-fsrs`
(github.com/open-spaced-repetition). Store `FsrsState` exactly as the chosen
library defines it.

Simple fallback (if you need something before integrating FSRS): Chessable's
MoveTrainer uses fixed levels of 4 hours, 1 day, 3 days, 1 week, 2 weeks,
1 month, 3 months, 6 months, resets to level 1 on a mistake, and gives each
move in a line its own timer. That is easy to implement and well understood by
chess players.

Grading a drill attempt for FSRS:

| Outcome | Rating |
|---------|--------|
| Solved with no hints, quickly (< 15 s per move) | Easy |
| Solved with no hints | Good |
| Solved after hint level 1–2 | Hard |
| Failed or needed level 3 | Again |

Daily queue: due cards first (cap 20), then new cards from recent games (cap
5), then rating-matched puzzles from the mined bank tagged with the lesson
focus.

## 6. Puzzle bank

Seed from the Lichess puzzle database (database.lichess.org, CC0): millions of
puzzles from real games with ratings and theme tags. Map Lichess theme tags to
concept IDs in `concepts/lichess_theme_map.yaml` (e.g. `fork` →
`tactic-double-attack`, refined by our detectors to the knight/pawn/queen
subtypes). Re-tag with our own detectors and drop puzzles where our tags and
Lichess's disagree on the primary theme, so the concept library and puzzle
bank use one vocabulary.
