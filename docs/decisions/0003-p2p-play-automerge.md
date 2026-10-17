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
- The document is an append-only record (seats, names, `moves: [{uci, by}]`, draw offer, end
  record, rematch link). `web/p2p/game.mjs` derives the game from it deterministically with
  chess.js: a move counts only if its author holds the side-to-move's seat and it is legal, and
  an end record (resign or agreed draw) stops the replay at its ply. Concurrent edits therefore
  converge on the same game on every peer without coordination. Tested in `game.test.mjs`.
- A player is identified by a random ID in `localStorage`. Online status uses Automerge
  ephemeral heartbeats, which the relay forwards but does not store.
- Packages: `@automerge/vanillajs` 2.5.6 (latest stable; the npm `latest` tag points at an
  alpha), chess.js 1.4.0. esbuild bundles them into one same-origin `p2p.js`, and the Automerge
  WASM ships as a static file, so the page works under the site's coi-serviceworker (COEP).

Rejected: a hosted relay of our own (operational cost for a demo); WebRTC without a relay (still
needs signalling, and NAT traversal fails for some pairs); chessground (GPL is fine for us, but the
existing board renderer already covers click-to-move).

## Consequences
- Trust model is "friends with a link": anyone with the URL can watch, and a client that edits
  the document directly could forge a move under another player's ID. The page is not suitable
  for anything that needs fair-play guarantees.
- The public relay stores the document and has no SLA or privacy promise; the page says so.
  Swapping relays is a one-line change (`RELAY` in `main.mjs`).
- No clocks or takebacks. If both players click Rematch at once, one rematch document wins and the
  other is orphaned; the loser's browser may land in the orphan and has to follow the winner's link.
