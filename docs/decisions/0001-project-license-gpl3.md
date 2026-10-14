# ADR 0001 — Project license: GPL-3.0

Date: 2026-10-13 · Status: accepted (decided by repo owner)

## Context
The default stack (AGENTS.md) uses `python-chess` (GPL-3.0) in the analysis
service and Stockfish (GPL-3.0). 07 required a license decision before adding
GPL/AGPL dependencies to a network service or the client.

## Decision
The whole project is licensed **GPL-3.0** (`LICENSE`). GPL-3.0 dependencies
(`python-chess`, Stockfish, and later `chessground`/`chessops` in the client)
are allowed. AGPL-3.0 code is still **not** copied in (lichess-puzzler, lila):
it would extend obligations to network use; read for ideas only.

## Consequences
- Anyone we distribute the app to gets the source under GPL-3.0.
- Every dependency is still recorded in `THIRD_PARTY.md`.
