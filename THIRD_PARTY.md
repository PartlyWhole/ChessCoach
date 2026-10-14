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
| stockfish.js (`stockfish` npm) | 19.0.1 | Stockfish 19 lite, single-threaded WASM | GPL-3.0 | Web Worker |
| onnxruntime-web | 1.24.3 | Runs the Maia-2 ONNX model | MIT | Web Worker |
| coi-serviceworker | 0.1.7 | Adds COOP/COEP headers on GitHub Pages | MIT | Service worker |
| Maia-2 rapid weights (fp16 ONNX export) | maia2 0.11 | Human-like move model | MIT | Static asset, exported in CI |

Build-only: onnx (Apache-2.0), onnxconverter-common (MIT).

Glicko-2 is implemented in-repo from Glickman's public paper (no dependency).
