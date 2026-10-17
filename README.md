# ChessCoach

A chess sparring partner that coaches while you play. Every explanation comes from
deterministic detectors and expert-authored templates; no LLM runs in the app. Start with
[AGENTS.md](AGENTS.md) and the specs in [docs/](docs/).

License: GPL-3.0 ([LICENSE](LICENSE), [ADR 0001](docs/decisions/0001-project-license-gpl3.md)).
Dependencies: [THIRD_PARTY.md](THIRD_PARTY.md).

## Setup

```bash
brew install stockfish            # tests are pinned to Stockfish 19
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[maia,dev]'
```

Maia-2 downloads its weights (~280 MB) into `models/maia2/` on first use.

## Play in the terminal

```bash
.venv/bin/python -m chesscoach.play --rating 1000 --mode guided --dev
```

`--dev` shows draft coaching text. **All 43 v1 concepts and the fallback texts are
`review: draft`** (AI-assisted). Per AGENTS rule 2 they must be approved by a chess expert
(`review.status: approved` in each YAML) before they ship; without `--dev` the coach stays
silent until then.

## Browser build (GitHub Pages)

Everything runs in the browser: Pyodide runs this Python package, Stockfish 19 lite runs as
WebAssembly and Maia-2 runs as an fp16 ONNX model ([ADR 0002](docs/decisions/0002-browser-build.md)).

```bash
uv pip install --python .venv/bin/python -e '.[webbuild]'
.venv/bin/python tools/export_maia_onnx.py      # once: models/maia2_rapid.fp16.onnx
(cd web && npm ci)
.venv/bin/python tools/build_web.py             # → _site/
```

The build also produces `p2p/`, a "play a friend" page: create a game, send the link, and the
moves sync peer to peer through an Automerge document on the public Automerge relay
([ADR 0003](docs/decisions/0003-p2p-play-automerge.md)). Its game logic tests run with
`(cd web && npm test)`.

Serve `_site/` with any static server. `.github/workflows/pages.yml` builds and deploys it on
pushes to `main` once GitHub Pages is set to "GitHub Actions" in the repo settings.

## Tests

```bash
CHESSCOACH_ALLOW_UNREVIEWED=1 .venv/bin/python -m pytest
```

Engine-dependent tests run Stockfish 19 single-threaded with a cleared hash, so results are
reproducible. The full suite takes several minutes (the concept tests run the engine).

## Layout

| Path | Layer |
|------|-------|
| `chesscoach/types.py`, `config.py` | shared types (01) and knobs |
| `chesscoach/analysis/` | L1 position analysis: engine pool, win prob, classification, detectors, structures, threats, tablebase |
| `chesscoach/concepts/` + `concepts/` | L2 concept registry, trigger matcher, templates, predicates; concept YAML data |
| `chesscoach/policy/` + `templates/` | L3 coaching policy; fallback texts |
| `chesscoach/sparring/` | L4 Maia-2 bot, sanity guard, openings, lesson steering, drills |
| `chesscoach/learner/` | L5 Glicko-2, bands, mastery, weakness profile, review builder, FSRS, puzzles, SQLite store |
| `chesscoach/session.py` | game session orchestrator (01 pipeline) |
| `tests/positions/` | shared test positions (08) |
| `tools/firing_rates.py` | regression firing-rate check (08 §3) |
