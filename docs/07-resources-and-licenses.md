# 07 — Resources, Libraries, Datasets, Licenses

Licensing note for agents: **GPL-3.0** code combined into a distributed app
makes the combined work GPL. **AGPL-3.0** extends that to software offered over
a network (a web service). Before adding a dependency, check its license here
or at the source, and record it in `THIRD_PARTY.md`. If the owner of this repo
has not decided on the project's license, **ask before adding any GPL/AGPL
dependency to the client or a network service.** Running Stockfish as a
separate process over UCI is the common pattern for using it from non-GPL
code; confirm with whoever owns licensing decisions.

Entries marked *verify* could not be confirmed when this doc was written
(October 2026). Re-check every license against the project's own LICENSE file
before release; licenses change.

## Engines and models

| Resource | Use | License |
|----------|-----|---------|
| Stockfish | Evaluation, best moves, MultiPV | GPL-3.0 |
| Maia-2 (`CSSLab/maia2`, `pip install maia2`) | Human-like move prediction by rating | MIT |
| Maia-3 (`CSSLab/maia3`) | Newer human-move model, recommended by the Maia-2 repo for new projects | *verify* |
| Maia-1 (`CSSLab/maia-chess`) | Per-band human-like Lc0 nets | *verify* |
| Syzygy tablebases | Perfect play ≤ 7 pieces | Freely downloadable; *verify* redistribution terms |

## Chess libraries

| Library | Language | Use | License |
|---------|----------|-----|---------|
| `python-chess` | Python | Rules, PGN, FEN, UCI engine control, Syzygy probing, SEE-style attack helpers | GPL-3.0 |
| `chess.js` | TS/JS | Client-side move legality, PGN/FEN | BSD-2-Clause |
| `chessground` | TS/JS | Lichess's board UI (arrows, highlights, drag/drop). No chess logic inside. | GPL-3.0 — makes your website GPL |
| `chessops` | TS | Lichess's rules library | GPL-3.0 (*verify*) |

If the client must not be GPL, use `chess.js` plus a permissively licensed
board component, and draw arrows/highlights yourself.

## Reference implementations (read for ideas — do not copy code)

| Resource | What to learn from it | License |
|----------|----------------------|---------|
| `lichess-org/lichess-puzzler` (`tagger/cook.py`) | Rule-based tactical theme detection over puzzle lines; puzzle generation from games | AGPL-3.0 (*verify*; the pip-installable refactor `chess-puzzler` is AGPL-3.0) |
| `chess_detect` (PyPI) | Detector-per-file layout for forks, pins, skewers, discovered checks, open files, doubled/isolated pawns | *verify* |
| LiChess Tools pawn-structure feature | Per-file pawn encoding and similarity scoring against named structures | *verify* |
| Lichess `lila` (Scala) | Move classification (blunder/mistake/inaccuracy), accuracy formula, "Learn from your mistakes" | AGPL-3.0 |
| chessprogramming.org | Definitions of pawn-structure terms, evaluation terms, SEE, null-move | Wiki content, cite don't copy |

## Datasets

| Dataset | Use | License |
|---------|-----|---------|
| Lichess puzzle database (database.lichess.org) | Seed puzzle bank: FEN, solution, rating, themes, opening tags; millions of puzzles | CC0 |
| Lichess standard games database (database.lichess.org) | Opening trees by rating band, puzzle mining, regression positions, Maia training | CC0 |
| Lichess opening explorer API | Live opening statistics | API terms of use; respect rate limits |

## Learning science

| Resource | Use | License |
|----------|-----|---------|
| FSRS — `open-spaced-repetition` (`py-fsrs`, `ts-fsrs`, optimizer) | Spaced repetition scheduler | Open source (*verify* per package) |
| Glicko-2 (Mark Glickman's paper) | Player, drill and concept ratings | Algorithm is public; choose an MIT-licensed implementation |
| Steps Method (Brunia & van Wijgerden), 6 trainer manuals + workbooks | Concept ordering by level; tactics-first progression | Copyrighted books — use for curriculum design only, never copy positions or text |

## Prior art (products to study, not reuse)

| Product | Relevant to layer | What it shows |
|---------|-------------------|---------------|
| DecodeChess | 1–2 | Natural-language explanations of Stockfish moves (threats, plans, piece functionality, motifs) without an LLM; aimed at players up to ~2000 |
| Chess.com Play Coach | 3 | Real-time in-game coaching with on-demand hints; explains pins, forks, king safety, weak squares |
| ChessBase Fritz "Coach is watching" | 3 | Offers help after blunders; hints that aren't direct move suggestions |
| Lichess "Learn from your mistakes" | 3, 5 | Let the player retry before showing the answer |
| Noctie | 4, 5 | Human-like bots at 25 levels, opening selection, puzzles from your own games |
| Chessiverse | 4 | 1,000+ bots with personalities |
| Chess.com Game Review | 5 | Report card, phase accuracy, key moments |
| Aimchess | 5 | Six-area weakness profile compared against peers; lessons from your mistakes |
| Chessable MoveTrainer | 5 | Spaced repetition for chess lines, per-move timers |

## Research

- McGrath et al., *Acquisition of Chess Knowledge in AlphaZero* (PNAS 2022) — human concepts (labelled using Stockfish's evaluation terms) are linearly decodable from a self-play network. Background for any future learned concept detectors.
- Tang et al., *Maia-2: A Unified Model for Human-AI Alignment in Chess* (NeurIPS 2024) — skill-aware human move prediction; framed as a basis for teaching tools.
