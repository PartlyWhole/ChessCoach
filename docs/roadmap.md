# Roadmap — end-to-end coach in the browser

Status: done 2026-10-24 (all milestones below). Remaining items need people, not code: see "Not in done".

## Definition of done

A learner can do all of this on the GitHub Pages site, with nothing installed:

1. Play the Maia sparring bot with live coaching (exists).
2. After each game, get a full review whose mistakes come with a **"Why?" view**: the line that
   punishes the move played and the best line, stepped through on a board, with each ply annotated
   by verified facts (material, checks, mate, detector-named tactics) and the decisive moment marked.
3. Keep a **learner profile** across visits: game rating (Glicko-2), band, concept mastery,
   weakness profile. The next game's lesson focus and bot strength follow from it.
4. Do **daily drills**: positions from their own mistakes (and puzzles, if M7 is in scope),
   scheduled with FSRS, graded with the hint ladder, feeding mastery.
5. A chess expert can **review and approve coaching text** with a tool built for it; approved text
   then appears for everyone without the developer preview.

Not in "done", because code cannot do it: approving the text itself (AGENTS rule 2), the human
explanation audit (08 §4), and the product metrics that need real users (08 §6–7).

## Rules that shape the design

- Every displayed claim traces to an engine line or a detector (rule 1). Line annotations are
  computed facts; any new prose is a template marked `review: draft` and stays behind the
  developer preview until approved.
- One Python codebase for native and browser (ADR 0002): new logic goes into `chesscoach/` with
  pytest tests; JavaScript only renders.
- New shared fields go into `chesscoach/types.py` and `docs/01` together (rule 5).
- Test positions before code for every new detector-like function (rule 7, 08).

## Milestones

| # | Milestone | Layer | Done when |
|---|-----------|-------|-----------|
| M1 | **Line explanations** — `explain_line()` walks an engine line ply by ply: material after each ply, captures, checks, mate, promotion, and tactical features from the existing move-based detectors applied with the rest of the line; marks the decisive ply. `MoveAssessment` gains the played-move line so the refutation is available. | L1 (+ types) | YAML test positions (≥ 5 positive, ≥ 5 negative incl. near misses) pass; native + browser |
| M2 | **Review carries the explanations** — `WebApp.review()` returns, per inaccuracy-or-worse, the refutation and best line with their explanations. Draft line templates added to the fallback file. | L5/L3 | pytest |
| M3 | **"Why?" explorer UI** — shared JS module: mini board, the two lines side by side, step/auto-play, per-ply badges, decisive ply highlighted. Used by the p2p analysis panel. | client | JS tests + browser check |
| M4 | **Browser persistence** — the existing SQLite `Store` runs in Pyodide on a file synced to IndexedDB. `WebApp` loads/saves the profile. | L5 + runtime | survives reload; pytest for the API |
| M5 | **Coach page learning loop** — after a game vs the bot: Glicko update vs bot Elo, band hysteresis, mastery update, review with "Why?", cards saved; next game picks lesson focus from the weakness profile; profile screen. Coach page gets move history and captured pieces like p2p. | L5 + client | end-to-end browser test |
| M6 | **Drills** — daily queue (due → new → puzzles), drill board with the hint ladder (approved text only, generic UI otherwise), FSRS grading, mastery from drills. | L5 + client | pytest for grading flow + browser |
| M7b | **Opening tree for the bot** — found in M5 testing: Maia-2 is trained only on plies > 10 (`maia2/dataset.py`), so the bot's opening moves were untrained guesses (…Na6, knight retreats). Build a rating-band opening tree from the Lichess games database (CC0) and use the engine's near-best moves when a game leaves it before ply 10. | L4 + build | bot plays real openings |
| M7 | **Puzzle bank** *(scope decision)* — build step selects Lichess puzzles (CC0) per mapped concept and band, re-tags them with our detectors, ships a compact JSON. | L5 + build | build + drill uses them |
| M8 | **Expert approval tool** — `/review/` page: every concept and fallback template rendered on its test positions (board, highlights, filled slots); approve / request changes / edit; exports decisions; `tools/apply_review.py` writes them into the YAML. | tooling | expert can approve a concept end to end |
| M9 | **Finish** — ADR 0004, docs 01/02/04/06 updates, full pytest + JS suites, deploy, live check. | — | deployed |

## Progress log

- 2026-10-24: plan written.
- 2026-10-24: M1–M3 done. `chesscoach/analysis/lines.py` + `tests/positions/lines/` (14 cases);
  `MoveAssessment.played_line`; review `why` blocks; "Why?" explorer in the p2p analysis panel
  (`web/shared/lines.mjs`, `web/shared/board.mjs`).
- 2026-10-24: M4–M6 done. Learner store on IndexedDB (Pyodide IDBFS + the `sqlite3` wheel);
  `chesscoach/learner/service.py` (learning loop) and `drill.py`; coach page rebuilt as an ES
  module (`web/coach/`) with Play / Drills / Progress tabs, post-game review with "Why?", shared
  review panel (`web/shared/review-panel.mjs`). Found the Maia-2 opening problem (M7b).
- 2026-10-24: M7b done. `tools/build_openings.py` (697k games, 96 s, 0.7 MB tree; median 7 plies
  deep); `band_tree()` with all-band fallback; bot never samples raw Maia before ply 10
  (`engine_opening`). Verified: 1.e4 e5 2.Nf3 Nf6 / 1.e4 Nc6 2.Nf3 e5 instead of …Na6/…Nb8.
- 2026-10-24: M7 done. `tools/build_puzzles.py` (6.2M rows read, 1,766 kept, 9 themes × 5 bands;
  `overloading` gets none: our detector never confirms Lichess's tag — input for 08 §2);
  `PuzzleBank.pick()` fills the drill queue by lesson focus and drill rating.
- 2026-10-24: M8 done. `/review/` page + `chesscoach/concepts/review_tool.py` +
  `tools/apply_review.py`. Found and fixed: approving a concept before its parent crashed the
  approved registry; parents/prerequisites may now be drafts.
