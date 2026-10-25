# 05 — Layer 4: Sparring Partner

The bot must (1) play like a human of the target strength, (2) never be
absurd, and (3) steer games toward a lesson concept when it can do so cheaply.
Point (3) is the feature that distinguishes this app: existing products let
players choose the bot's opening, but none we found publicly documents
steering the middlegame toward a specific teaching concept.

## 1. Human-like move generation

### Options, best first

| Option | What it is | Notes |
|--------|-----------|-------|
| **Maia-3** | Latest model from the Maia project (CSSLab, U. Toronto). | The Maia-2 repo now recommends Maia-3 for new projects. Check its license and API before adopting. |
| **Maia-2** | Single skill-aware model; takes the position plus `elo_self` and `elo_oppo` and returns a probability distribution over legal moves and a win-probability estimate. `pip install maia2`, MIT license. | Proven, published (NeurIPS 2024), runs on CPU. Use as the default until Maia-3 is evaluated. |
| Maia-1 | Separate network per rating band (1100–1900). | Superseded; only useful as a UCI engine shortcut. |
| Weakened Stockfish | Skill level / depth limits / random MultiPV sampling. | Plays unhuman mistakes (random blunders in quiet positions). Use only as a fallback. |

Maia-2 is described by its authors as conditioning predictions on both
players' rating categories; it is **not** a calibrated estimate of an
individual's strength. Set `elo_self` to the bot's target level and
`elo_oppo` to the player's current rating.

### Sampling

Don't always play Maia's top move — that makes the bot stronger and more
predictable than the humans it imitates.

```
probs = maia(fen, elo_self=bot_elo, elo_oppo=player_elo)    # dict move -> p
probs = {m: p ** (1 / temperature) for m, p in probs.items()}; normalize
drop moves with p < 0.02; renormalize
move = sample(probs)
```

`temperature` default 1.0. Lower it (0.7) for the top bot levels.

Maia-2's rating buckets are `<1100`, `1100–1199` … `1900–1999`, `>=2000`, so
every target below 1100 plays like the `<1100` bucket. B0 bots (< 800) are
therefore weakened only through temperature and the sanity guard being off below
1200. Measured on an M1: 15 ms per Maia-2 inference on CPU.

### Sanity guard (`engine_safety`)

Humans blunder, so the bot must too — but not absurdly. Reject the sampled
move and resample (max 3 tries, then take the most probable move that passes the
guard — Maia's top move only if every move fails, since the top move can itself be
the absurd one) if:

- it hangs the queen or allows mate-in-1 while `bot_elo ≥ 1200`, or
- it loses > 0.40 win prob while the bot's rating is ≥ 1600.

Below 1200, let it through: beginner bots should leave pieces hanging, because
punishing that is exactly what B0 players need to practise.

### Bot strength calibration

Target the bot at `player_rating + offset`. Start with offset = +50 (slightly
stronger opponent) and adjust per player so their score against the bot over
the last 10 games stays in 40–60%. Store as `bot_offset` in the profile (06).

## 2. Opening selection

- The player can pick an opening for either side (repertoire training).
- Otherwise, the bot picks openings that lead to the current lesson's structure (table below) or uses Maia freely.
- For forced openings, play from an opening tree built from Lichess game data filtered to the player's rating band, weighted by frequency — i.e. "the lines humans at this level actually play". Leave the tree when its game count at a node drops below 50.
- **Maia-2 is not used before ply 10.** Its training data keeps only `move_ply > 10`
  (`maia2/dataset.py`), so its opening predictions are untrained (measured: after 1.e4 Nc6 2.Nf3
  it gives …Nb8 60%). Order of sources: repertoire line → lesson line → band opening tree
  (`tools/build_openings.py`, Lichess games, CC0) → before ply 10, a random move among the
  engine's MultiPV lines within `steer.max_win_prob_cost` of its best (`source: engine_opening`)
  → Maia.

| Lesson structure | Bot as White | Bot as Black |
|------------------|-------------|--------------|
| `iqp` | Queen's Gambit Tarrasch lines, Caro-Kann Panov | Tarrasch Defence, Semi-Tarrasch |
| `carlsbad` | QGD Exchange | Accept QGD Exchange when offered |
| `french_advance` | 1.e4 e6 2.d4 d5 3.e5 | French Defence |
| `kings_indian_closed` | Mainline KID with d5 | King's Indian Defence |
| `maroczy_bind` | vs Accelerated Dragon | Accelerated Dragon |

A chess expert must own and review this table.

## 3. Lesson steering

Each game may have a `lesson_focus` concept chosen at game start from the
player's weakest relevant concepts (06). The bot steers **only among moves
that are already human-plausible and nearly equal**:

```
candidates = top moves from maia with p >= 0.05
for each m in candidates:
    eval_cost(m)  = wp_bot(best_engine_move) - wp_bot(m)          # from engine, bot POV
    lesson_gain(m) = lesson_score(position_after(m), lesson_focus)
keep m where eval_cost(m) <= steer.max_win_prob_cost (default 0.05)
if any kept m has lesson_gain > 0:
    choose argmax(lesson_gain - 2 * eval_cost) → source = "steer"
else:
    normal sampling → source = "maia"
```

`lesson_score` is per concept category:

| Category | lesson_score heuristic |
|----------|-----------------------|
| tactic (player should *find* it) | 1 if after the bot's move the player has an `available` hit for the concept that wins ≥ 0.10 win prob within 4 plies, else 0. This is a deliberate "inaccuracy" by the bot — use `steer.max_win_prob_cost_tactic` (0.15) instead of the default cap, and limit to once per game. |
| defence (player should *defend*) | 1 if the bot's move creates a `ThreatInfo` the player can parry with exactly one good move. |
| structure | *improvement* in similarity to the target `structure_id` (0..1). Raw similarity would make almost every move score > 0, so the bot would "steer" constantly. |
| endgame | 1 if the move is a trade that heads toward the target endgame material signature. |

Concepts in other categories (safety, opening, positional) are not steered
toward in v1.

Rules:
- Never steer more than once every 4 bot moves (except structure steering in the opening, which is just opening choice).
- Log every steer decision (`BotMove.source`, `steer_concept_id`) — 08 measures whether steered games actually produce lesson opportunities.
- If the player plays a strong move that escapes the lesson, drop the focus for the rest of the game. Don't contort the game.

## 4. Move timing

Instant replies feel robotic. In untimed games, wait 0.5–2.5 s scaled by
position complexity (number of legal moves × sharpness). In timed games,
spend time proportional to the clock (e.g. remaining / 40, jittered ±30%).

## 5. Endgame drills

For scenario training ("win K+R vs K", "hold the Philidor"), start from a
FEN library, and let the bot defend with tablebase-perfect moves
(Syzygy, see 02) when the drill is about technique, or with Maia when it is
about practical play. Say which in the drill description.
