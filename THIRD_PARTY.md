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

Glicko-2 is implemented in-repo from Glickman's public paper (no dependency).
