# 04 — Layer 3: Coaching Policy

L2 produces many `ConceptHit`s. This layer decides **whether the coach speaks,
which single idea it talks about, and how much it reveals**. The default is
silence. A coach that comments on every move gets ignored.

No published product documents its prioritization logic; this spec is our own.
Treat the numbers as starting points to tune with the metrics in 08.

## Inputs

- `MoveAssessment` for the player's move
- `ConceptHit[]` from L2
- `LearnerProfile` and `ConceptMastery` (06)
- Session state: moves since last comment, comments this game, hints used, current lesson focus, time control
- User settings (below)

## Output

Zero or one `CoachingEvent` per player move, plus zero or more
`queued_for_review` events (stored, not shown).

## Decision procedure

```
1. HARD INTERRUPT
   if move_class == blunder and settings.interrupt_blunders:
       pick top hit with role in {allowed, missed}; if none → engine fallback
       emit interrupt(hint_level=1, allow_takeback=True)
       return

2. SCORE candidate hits
   score(h) = h.importance
            × relevance(h.concept, profile)     # 0.3 if mastered, 0.65 if practised, 1.0 if new/learning, 1.5 if current lesson focus
            × band_fit(h.concept, profile.band) # 1.0 in band (or a below-band basic), 0.5 one band above, 0 two+ above
            × novelty(h.concept, session)       # 0 if said this game, 0.5 if said in last 3 games
   drop hits with band_fit == 0

3. BUDGET
   if comments_in_last_10_player_moves >= max_comments_per_10_moves: queue all, return
   threshold = 0.35 if move_class in {mistake, inaccuracy} else 0.55

4. CHOOSE
   best = argmax score
   if best.score < threshold: queue hits with role missed/allowed for review, return
   kind = praise if best.role == played else comment
   level = 0 for praise, else start_level(best, profile)   # see hint ladder
   emit event

5. QUEUE the rest of the missed/allowed hits for post-game review (06).
```

### Before the player moves (pre-move prompts)

Only in "guided" mode, and only when **all** hold:
- `sharpness ≥ 0.8` (one move holds or wins), and
- the position has an `available` or threat-based hit within the player's band, and
- no pre-move prompt in the last 5 player moves.

Then show a level-1 prompt such as *"Something important is happening here —
check your opponent's threats first."* This teaches the habit without
solving the position for them.

## Hint ladder

Each concept template defines levels (03). The policy owns the progression.

| Level | Reveals | Example |
|-------|---------|---------|
| 1 | Category / question | "What is your opponent threatening?" |
| 2 | Location | "Look at the knight on f3 and the square e5." |
| 3 | Answer + reason | "Nxe5 wins a pawn because the d6 pawn is pinned." |

- Start at level 1 by default.
- Start at level 2 if the concept's mastery is `new` (never seen) and the player is B0–B1.
- The hint button advances one level. Each press is recorded (06 uses hint depth as a mastery signal).
- After a takeback following an interrupt, the player gets up to 2 attempts before level 3 auto-reveals.
- Never jump straight to level 3 except on the third failed attempt or in review mode.

This mirrors the approach Lichess uses in "Learn from your mistakes": let the
player rethink the position first and show the best move only on request.

Implementation notes (`chesscoach/policy/policy.py`):
- Interrupt and comment text never jumps to level 3; a hit whose level 1/2
  templates cannot render (missing slot) is skipped for the next one.
- Highlights follow the ladder: level 1 shows nothing on the board, level 2 the
  squares, level 3 (and praise) adds the move arrow.
- Praise is capped at 1 per game, never for `forced` moves or a recapture on the
  square the opponent just captured on.
- After an interrupt that allows a takeback, the bot waits; the player takes
  back (`retry`) or resumes. A retry that is no longer an inaccuracy or worse
  closes the hint silently.
- Faster than 10+0 means base + 40 × increment < 600 s.

## Fallback when no concept explains it

Sometimes the engine's best move has no detectable idea. The coach must not
invent one. Use, in order:

1. A threat-based hit (null-move threat) if one exists: *"This allowed {threat_move_san}."*
2. Engine line: *"The engine prefers {best_san}. Main line: {pv_san_first_6_plies}."* (`concept_id = null`)
3. If even that is uninformative (quiet position, loss < 0.10): stay silent and queue for review.

The fallbacks are hint ladders too (`templates/en/_fallback.yaml`), so an
interrupt can start at level 1 without naming the move: level 1 says the move
gave away a lot, level 2 points at the piece, level 3 is the wording above.
`{threat_move_san}` after the player's move is the engine's best reply
(`reply_san`). Without a concept hit, a non-blunder only gets a fallback comment
when it is a `mistake`.

## Modes and settings (`CoachSettings`)

| Setting | Values | Default |
|---------|--------|---------|
| `mode` | `guided` (pre-move prompts, interrupts) / `standard` (interrupts on blunder only) / `silent` (review only) | `standard` |
| `interrupt_blunders` | bool | true |
| `allow_takebacks` | bool | true |
| `verbosity` | low (budget 2/10) / normal (3/10) / high (5/10) | normal |
| `praise` | bool | true |

In timed games faster than 10+0, force `silent` mode: coaching during blitz
interferes with the clock and trains bad habits.

## Tone rules

- Praise specific good moves (`played` role) about once per game when earned. Don't praise `best` moves that were the only legal move or an obvious recapture.
- Never use "bad move", "terrible", or similar. Describe consequences: "This lets…", "After this…".
- One idea per message.
- Use the player's perspective: "your knight", "your opponent's bishop".

## Session state to persist

```ts
interface CoachSessionState {
  game_id: string;
  player_moves: number;
  comment_ply_history: number[];       // plies where the coach spoke
  concepts_mentioned: string[];        // this game
  hints_requested: { ply: number; concept_id: string | null; level: number }[];
  takebacks: number;
  lesson_focus: string | null;         // concept_id chosen at game start (05 steering)
  // additions needed to apply the rules above:
  player_move_plies: number[];         // ply of each player move (budget window)
  pre_move_prompt_plies: number[];
  praise_count: number;
  active_hint: { ply: number; concept_id: string | null; level: number; attempts: number } | null;
}
```
