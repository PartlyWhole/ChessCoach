# ADR 0003 — Peer-to-peer play over Automerge

Date: 2026-10-17 · Status: accepted (demo page)

## Context
We wanted a page on the GitHub Pages site where two people play each other from a shared link.
Pages is static, so there is no game server. AGENTS.md listed online multiplayer as out of scope;
this page is a deliberate, narrow exception: no accounts, matchmaking, clocks, ratings or
anti-cheat, and no coaching (it does not touch L1–L5).

## Decision
- One game is one Automerge document. Its `automerge:` URL is the page's hash, so the link is the
  invitation. Peers sync through the public Automerge relay `wss://sync.automerge.org`, plus a
  BroadcastChannel between tabs of one browser; IndexedDB keeps a local copy across reloads.
- The document is an append-only record (seats, names, a `moves` event log, draw offer,
  takeback request, end record, rematch link). `web/p2p/game.mjs` derives the game from it
  deterministically with chess.js: a move counts only if its author holds the side-to-move's
  seat, it is legal and its recorded ply matches; an end record (resign or agreed draw) stops the
  replay at the log length it was made at. Concurrent edits therefore converge on the same game
  on every peer without coordination. Tested in `game.test.mjs`.
- Takebacks (added 2026-10-17) need the opponent's consent. A request is `takeback: {by, n}`
  and lapses when the log grows (a move instead of an answer declines it). Accepting appends
  `{undo: 1|2, by, req, ply}` to the log, which removes the requester's last move, plus the
  opponent's reply if one was made. Nothing is deleted from the document, and because undo
  entries and moves both carry the ply they were made at, an accept racing the requester's own
  move resolves the same way on every peer (whichever lands first in the merged log wins; the
  other is skipped). Documents from before takebacks (no ply on moves, `ply` instead of `n` on
  records) still replay.
- Move history: every position can be viewed at any time, during play too, with step buttons,
  the arrow keys, a clicked move or an automatic replay. The page also keeps a list of the games
  opened in this browser (`localStorage`, max 20) so they can be reopened and replayed.
- Opening a link right after the game is created can reach the relay before the game does. The
  page then waits up to 30 s for it (`find` with `unavailable` allowed, then `whenReady`).
- A player is identified by a random ID in `localStorage`. Online status uses Automerge
  ephemeral heartbeats, which the relay forwards but does not store.
- Packages: `@automerge/vanillajs` 2.5.6 (latest stable; the npm `latest` tag points at an
  alpha), chess.js 1.4.0. esbuild bundles them into one same-origin `p2p.js`, and the Automerge
  WASM ships as a static file, so the page works under the site's coi-serviceworker (COEP).
- Post-game analysis (added 2026-10-17): once a game is over, either player or a spectator can
  ask for it. The page loads the shared browser runtime (`web/runtime.js`, factored out of the
  main page's `app.js`: Pyodide + Stockfish 19 lite WASM + the synchronous RPC broker of ADR 0002)
  and calls `WebApp.review()`, which runs the existing `build_review` (docs/06 §4) for each side.
  Classification, accuracy and moment selection therefore come from the same Python as the
  native app; `web/p2p/review.mjs` only formats the result. The page shows per-side accuracy and
  inaccuracy/mistake/blunder counts, a White-win-probability graph, the engine's best move and
  line for every move, and the key moments. Moment summaries are concept/fallback templates, so
  they appear only when approved or behind the developer-preview opt-in (AGENTS rule 2). It runs
  at `engine.depth_review_web` = 14 rather than 22: the lite single-threaded engine reaches
  depth 14 in ~0.5 s per position, so a 33-ply game takes ~30 s including the first load
  (~15 MB). Results are cached per viewer in `localStorage` and never written to the shared
  document, so a peer cannot plant a fake analysis. Analysis is offered only for finished games,
  so the page itself never offers an engine during play.
- The p2p page includes `coi-serviceworker` for that runtime (first visit reloads once). The
  browser build now also ships the `fsrs` and `typing-extensions` wheels, because
  `chesscoach.learner.review` imports the SRS module.

Rejected: a hosted relay of our own (operational cost for a demo); WebRTC without a relay (still
needs signalling, and NAT traversal fails for some pairs); chessground (GPL is fine for us, but the
existing board renderer already covers click-to-move).

## Consequences
- Trust model is "friends with a link": anyone with the URL can watch, and a client that edits
  the document directly could forge a move under another player's ID. The page is not suitable
  for anything that needs fair-play guarantees.
- The public relay stores the document and has no SLA or privacy promise; the page says so.
  Swapping relays is a one-line change (`RELAY` in `main.mjs`).
- Depth 14 on the lite network has a shorter horizon than native review at depth 22: a deep
  combination can show up one move late on the graph (seen with a mate-in-3 queen sacrifice).
  The panel names the engine and depth and says to treat close calls with care.
- No clocks. If both players click Rematch at once, one rematch document wins and the
  other is orphaned; the loser's browser may land in the orphan and has to follow the winner's link.
