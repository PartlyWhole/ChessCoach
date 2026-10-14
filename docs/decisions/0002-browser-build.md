# ADR 0002 — Browser build on GitHub Pages

Date: 2026-10-13 · Status: accepted (proof of concept)

## Context
GitHub Pages serves static files only. The app is Python (L1–L5), drives Stockfish over UCI and
runs Maia-2 on PyTorch. Measured on an M1 before deciding:

| Piece | Browser option | Measurement |
|-------|----------------|-------------|
| Engine | Stockfish 19 lite, single-threaded WASM (npm `stockfish` 19.0.1, GPL-3.0) | 1.8 MB; depth 15 in 350 ms at MultiPV 3 (native live setting reaches depth 14) |
| L1–L3 Python | Pyodide 0.27.7 (MPL-2.0) | our detectors run unchanged, 2.5 ms/position; boot ≈ 1.9 s |
| Maia-2 | fp16 ONNX on onnxruntime-web 1.24.3 (MIT) | 46.6 MB; top move = fp32 in 120/120 positions (int8 changed top moves: rejected) |

## Decision
Ship one Python codebase to both targets. In the browser:

- `web/py-worker.js` runs the unchanged `chesscoach` package in Pyodide.
- Python reaches the engine and Maia through `chesscoach/web/bridge.py` (`RpcEnginePool`,
  `RpcMaiaModel`), which call a synchronous `rpc_sync()`. The worker posts the request to the page
  and blocks with `Atomics.wait` on a SharedArrayBuffer; the page relays it to the Stockfish worker
  (UCI) or the Maia worker (onnxruntime-web) and writes the answer back.
- This needs cross-origin isolation. Pages cannot send COOP/COEP headers, so `coi-serviceworker`
  (MIT) adds them; the first visit reloads once. All assets are same-origin.
- Python-side preprocessing for Maia-2 (`chesscoach/sparring/maia_features.py`) is tested to match
  the maia2 package exactly.

Rejected: making the Python engine interface async (large change to analyzer, session, bot and
tests for no behavioural gain); a TypeScript rewrite (duplicates every detector and test).

## Consequences
- The site is ≈ 75 MB, ≈ 47 MB of it the Maia model; browsers cache it after the first visit.
- Evaluations come from the lite network, whose centipawn scale differs from the full network
  (+20.2 vs +12.8 in one test position). Win-probability clamping absorbs most of it, but the
  engine-pinned test suite is calibrated on full Stockfish 19; re-validate before relying on the
  browser build for anything beyond a demo.
- No tablebases, no persistence (no SQLite) in the proof of concept.
- AGENTS rule 2 still holds: the page loads approved concepts only, unless the visitor ticks the
  developer-preview box to see unreviewed drafts.
- Browsers without SharedArrayBuffer support (very old ones) cannot run it.
