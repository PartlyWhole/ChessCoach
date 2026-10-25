# ADR 0004 — The whole learning loop in the browser

Date: 2026-10-24 · Status: accepted

## Context
ADR 0002 put the coach's Python in the browser for a single game against the bot. The product
(AGENTS.md "What we are building") is the loop around games: explain mistakes, keep a learner
model, steer the next game, and drill mistakes with spaced repetition. GitHub Pages has no server,
and the user asked for the whole thing to work there (roadmap: `docs/roadmap.md`).

## Decision
- **Explanations along the line (L1, 02 §6.6).** `explain_line()` replays an engine line and
  labels each ply with computed facts (capture, check, mate, material, detector-named tactics) and
  the decisive ply, SEE-settled so an exchange in progress is never reported as a gain. Reviews
  attach it to every inaccuracy or worse, for the line after the move played and the best line;
  the "Why?" view steps through both on the board. Labels are facts, not prose; prose stays in
  templates behind the review gate.
- **Persistence.** The existing SQLite `Store` runs unchanged in Pyodide on an IDBFS folder that
  IndexedDB keeps (the build ships Pyodide's `sqlite3` wheel). The worker syncs after each call.
  Private windows fall back to memory and the page says so. Data stays in the browser.
- **Learning loop.** `chesscoach/learner/service.py` runs it over the store: profile from the first
  game's rating, Glicko-2 against the bot's Elo, band hysteresis, bot offset, mastery, review cards,
  weakness profile → lesson focus. `WebApp` exposes `finish_game`, `learner_state`, drills.
- **Drills.** `chesscoach/learner/drill.py`: replies played automatically; an alternative counts only
  if it is the engine's best move or mate (win probability saturates in won positions, so a 2%
  threshold accepted almost anything); two wrong tries, then the solution; hints from solution
  facts (piece, square, move) plus concept text when approved; grading per 06 §5.
- **Data built from Lichess (CC0).** A per-band opening tree (one month of games, 0.7 MB) and a
  puzzle bank (~1,800 puzzles re-tagged by our detectors, 0.34 MB), both shipped in `app.zip` and
  built in CI with cached downloads.
- **Maia-2 is not used before ply 10.** Measured during this work: Maia-2 is trained only on plies
  after the 10th (`maia2/dataset.py`), and its opening output was untrained (…Nb8 60% after 1.e4
  Nc6 2.Nf3). The bot uses lines → opening tree → engine near-best moves (`engine_opening`) there.
- **Expert review tool.** `/review/` shows each concept's text on its test positions as the browser
  coach renders it; edits are validated with the registry's rules; decisions are exported and
  applied by `tools/apply_review.py`. Approval remains a human decision committed to the repo.
- **One page per job, shared modules.** Coach page (`web/coach/`), p2p page (`web/p2p/`) and review
  page (`web/review/`) are ES modules bundled by esbuild and share `web/shared/` (board, review panel,
  line formatting, replay helpers) and `web/runtime.js` (Pyodide + Stockfish + Maia broker).

Rejected: a hosted backend for profiles (accounts, privacy, operating cost); IndexedDB-native
storage written in JS (would duplicate the store and its tests); Lichess's live opening-explorer
API (rate limits, not static, sends players' moves to a third party).

## Consequences
- Progress lives in one browser profile. Two tabs of the coach page can overwrite each other's last
  sync; clearing site data deletes everything. Reset is in the Progress tab.
- Until a chess expert approves concepts, the registry is empty for normal visitors: reviews show
  engine lines and line facts only, mastery and lesson focus stay idle, and drill hints use solution
  facts. The developer preview shows the drafts.
- Browser reviews run Stockfish lite at depth 14 (22 natively); close calls can differ.
- The opening tree reflects 2014 Lichess ratings: B0 has no data and B1 is thin, so those bands use
  the all-band tree. A newer or larger month would deepen it (build script, one constant).
- The site is ~80 MB (Maia ~47 MB); first visit downloads the parts each page needs.
