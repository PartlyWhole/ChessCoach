# Third-party components

Project license: GPL-3.0 (see `LICENSE`, ADR 0001).

| Component | Version | Use | License | How used |
|-----------|---------|-----|---------|----------|
| python-chess (`chess`) | 1.11.2 | Rules, FEN/PGN, UCI engine control, Syzygy probing | GPL-3.0 | Python import |
| Stockfish | 19 | Evaluation engine | GPL-3.0 | Separate process over UCI |
| PyYAML | 6.0.x | Concept / test-position files | MIT | Python import |
| fsrs (py-fsrs) | 6.3.x | Spaced-repetition scheduler (06 §5) | MIT | Python import |
| maia2 | see `pyproject.toml` | Human-like move model (05) | MIT | Python import, optional extra |
| PyTorch | via maia2 | Runtime for Maia-2 | BSD-3-Clause | Transitive |
| pytest | 9.x | Tests (dev only) | MIT | Dev dependency |

Browser build (ADR 0002), shipped in the GitHub Pages site:

| Component | Version | Use | License | How used |
|-----------|---------|-----|---------|----------|
| Pyodide | 0.27.7 | Python runtime in the browser | MPL-2.0 | Static assets |
| PyYAML (Pyodide build) | 6.0.2 | Concept files | MIT | Wheel from the Pyodide CDN, sha256-checked |
| typing-extensions (Pyodide build) | 4.11.0 | Needed by fsrs | PSF-2.0 | Wheel from the Pyodide CDN, sha256-checked |
| sqlite3 (Pyodide build of CPython's module) | Pyodide 0.27.7 | Learner store in the browser (ADR 0004) | PSF-2.0 (module), public domain (SQLite) | Wheel from the Pyodide CDN, sha256-checked |
| fsrs (py-fsrs) | 6.3.x | Imported by the review builder (p2p analysis, ADR 0003) | MIT | Pure-Python wheel built from the sdist |
| stockfish.js (`stockfish` npm) | 19.0.1 | Stockfish 19 lite, single-threaded WASM | GPL-3.0 | Web Worker |
| onnxruntime-web | 1.24.3 | Runs the Maia-2 ONNX model | MIT | Web Worker |
| coi-serviceworker | 0.1.7 | Adds COOP/COEP headers on GitHub Pages | MIT | Service worker |
| Maia-2 rapid weights (fp16 ONNX export) | maia2 0.11 | Human-like move model | MIT | Static asset, exported in CI |

Peer-to-peer page (ADR 0003), bundled into `p2p/p2p.js` by esbuild; notices ship in `p2p/LICENSES.txt`:

| Component | Version | Use | License | How used |
|-----------|---------|-----|---------|----------|
| @automerge/vanillajs (automerge-repo + websocket, broadcastchannel, indexeddb adapters) | 2.5.6 | Sync the game document between peers | MIT | Bundled |
| @automerge/automerge | 3.5.0 | CRDT core | MIT | Bundled JS + `automerge.wasm` static asset |
| chess.js | 1.4.0 | Move legality, SAN, game-end detection | BSD-2-Clause | Bundled |
| Transitive: @noble/hashes, base-x, bs58, bs58check, cbor-x, debug, eventemitter3, isomorphic-ws, ms, uuid, xstate | see `web/package-lock.json` | automerge-repo internals | MIT | Bundled |
| Transitive: fast-sha256 | 1.3.0 | automerge-repo internals | Unlicense | Bundled |

Service (not a dependency): the public Automerge sync relay `wss://sync.automerge.org`.

Data built into the site (ADR 0004):

| Data | Source | Use | License |
|------|--------|-----|---------|
| Opening tree (`data/opening_tree.json` in app.zip) | Lichess games database, standard rated, 2014-01 (database.lichess.org), sha256-checked; counts only | The bot's opening moves per rating band (05 §2) | CC0-1.0 |

Build-only: onnx (Apache-2.0), onnxconverter-common (MIT), esbuild 0.28.2 (MIT), zstandard 0.23 (BSD-3-Clause).

Glicko-2 is implemented in-repo from Glickman's public paper (no dependency).
