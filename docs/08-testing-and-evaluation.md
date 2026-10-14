# 08 — Testing and Evaluation

Correctness is the product's promise. A coach that says "fork" when there is
no fork loses the player's trust permanently. Test accordingly.

## 1. Test position format

All chess tests use one YAML format so detector, concept and policy tests can
share positions.

```yaml
# tests/positions/detectors/fork.yaml
detector: fork
cases:
  - id: knight-fork-king-rook-basic
    fen: "<FEN>"
    move: "<uci move that creates the fork>"   # optional: features after this move
    expect:
      present: true
      squares_include: ["<fork square>"]
      data: { piece: knight }
  - id: fork-but-defended-not-winning
    fen: "<FEN>"
    move: "<uci>"
    expect:
      present: false            # double attack exists, but engine shows no gain
    note: "Guards against claiming a fork that loses material."
```

Rules:
- Every detector: ≥ 5 positive and ≥ 5 negative cases. Negatives must include *near misses* (the thing almost exists).
- Every concept: ≥ 3 positive, ≥ 2 negative, covering each role it declares.
- Every FEN is validated by a test helper (`board.is_valid()`) before use.
- Engine-dependent expectations run with a pinned Stockfish version and depth. Record both in the test file header. Upgrading Stockfish = rerun all and review diffs.

Source positions from: Lichess puzzle database (CC0), positions from our own
users' games (with consent), and positions constructed by the chess expert.
**Do not copy positions from copyrighted books** (including the Steps Method
workbooks).

## 2. Detector agreement test

For tactical detectors, measure agreement with Lichess puzzle theme tags on a
fixed sample (e.g. 20k puzzles):

| Metric | Target |
|--------|--------|
| Precision vs Lichess tag (our `fork` ⇒ Lichess has `fork`) | ≥ 0.90 |
| Recall vs Lichess tag | ≥ 0.70 |

Lichess tags are partly crowdsourced and partly automatic, so they are noisy.
Investigate disagreements by hand in batches of 50; fix whichever side is
wrong (ours) or add the case to an `exclusions.yaml` (theirs).

## 3. Regression set and firing rates

Maintain `tests/regression/positions.jsonl`: 10k positions sampled from Lichess
games, stratified by rating band and phase. On every change to detectors or
concepts, CI computes:

- firing rate per feature and per concept (per 100 positions),
- diff against the previous run.

Fail CI if any concept's firing rate changes by more than 50% relative without
an explicit acknowledgement in the PR. Flag any concept firing in > 5% of
middlegame positions for review (too loose).

## 4. Explanation correctness audit (human)

Before each release, a chess expert reviews a random sample of 100 coaching
events from test games against bots at each band.

| Grade | Meaning |
|-------|---------|
| Correct & useful | ship |
| Correct, not useful | tune policy (04) |
| Incorrect | **release blocker**; add the position as a negative test |

Target: 0 incorrect, ≥ 70% "correct & useful".

## 5. Bot evaluation

| Test | Method | Target |
|------|--------|--------|
| Strength calibration | Bot at target T vs bot at T±200 (and vs Maia/Stockfish references); fit Elo | Within ±75 of target |
| Human-likeness | Move-match rate with human moves at the same rating on held-out Lichess games | Within 2 points of raw Maia at that rating |
| Sanity guard | Count absurd moves (queen hang, missed mate-in-1) per 100 games above 1200 | ≤ 1 |
| Steering effectiveness | % of games with a `lesson_focus` where the player got ≥ 1 opportunity for that concept | ≥ 50% (vs baseline without steering) |
| Steering cost | Average win-prob given up by `steer` moves | ≤ `steer.max_win_prob_cost` |

## 6. Policy metrics (product analytics)

Logged per game; reviewed weekly.

- Comments per 10 moves (target 1–3 in `standard` mode).
- % of comments dismissed within 1 s (proxy for annoyance; target < 20%).
- Hint ladder: distribution of final hint level per hint session. If most end at level 3, level 1/2 texts aren't helping.
- Takeback-after-interrupt: % of interrupts where the player took back and found a better move.
- Concept transfer: for concepts that reached `practised` via drills, success rate in real games over the next 20 games.

## 7. Learning outcome (the real goal)

Run as an ongoing experiment, not a launch gate:

- Rating change over 30 days for active users vs a holdout without steering, or without coaching (`silent` mode with review only).
- Per-concept: does `mastered` in our model predict fewer `allowed` hits for that concept in later games? If not, the mastery thresholds in 06 are wrong.

## 8. Performance

- Live per-move pipeline p95 < 1.5 s on target hardware (01).
- Review build for a 40-move game < 20 s.
- Detector suite (all detectors, one position, no engine) < 20 ms.
