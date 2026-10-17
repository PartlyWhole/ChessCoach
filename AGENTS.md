# AGENTS.md — Chess Coaching App (non-LLM)

Read this file first. It tells you what we are building, the rules that are not
negotiable, and which reference doc to open for each part of the work.

## What we are building

A chess training app built around a **sparring partner that coaches while the
player plays freely**. The bot plays human-like moves at the player's level,
steers games toward concepts the player needs to learn, comments on the game
at the right moments, and turns mistakes into spaced-repetition drills.

**No large language models anywhere in the runtime.** Every explanation the app
shows is produced by deterministic detectors plus expert-authored templates.
This is a product decision, not a cost decision: chess explanations must be
correct, and an LLM cannot guarantee that.

## The five layers

| # | Layer | Job | Spec |
|---|-------|-----|------|
| 1 | Position analysis | Turn a position + engine output into structured facts | [docs/02-position-analysis.md](docs/02-position-analysis.md) |
| 2 | Concept library | Map facts to teachable concepts with templated text | [docs/03-concept-library.md](docs/03-concept-library.md) |
| 3 | Coaching policy | Decide whether to speak, what to say, how much to reveal | [docs/04-coaching-policy.md](docs/04-coaching-policy.md) |
| 4 | Sparring partner | Choose the bot's moves: human-like, level-matched, lesson-steering | [docs/05-sparring-partner.md](docs/05-sparring-partner.md) |
| 5 | Learner model & review | Ratings, weakness profile, post-game review, spaced repetition | [docs/06-learner-model-and-review.md](docs/06-learner-model-and-review.md) |

Also read:

- [docs/01-architecture.md](docs/01-architecture.md) — components, data flow, shared types. **The shared types in that file are the contract between layers.**
- [docs/07-resources-and-licenses.md](docs/07-resources-and-licenses.md) — libraries, datasets, and their licenses. Check here before adding any dependency.
- [docs/08-testing-and-evaluation.md](docs/08-testing-and-evaluation.md) — how to prove a detector, concept, or policy change is correct.

## Non-negotiable rules

1. **Never show the player a claim the code did not verify.** Every sentence the coach says must trace back to a detector output or an engine line. If nothing verifiable explains a move, fall back to showing the engine line (see 04, "Fallback").
2. **No LLM calls at runtime.** Not for explanations, not for "polishing" template text. Offline tooling (e.g. helping authors draft templates that a human then reviews) is allowed only if a human approves every string before it ships.
3. **The engine is the source of truth for evaluation; detectors are the source of truth for *why*.** Do not infer tactics from evaluation numbers alone, and do not override the engine with a heuristic.
4. **Use win probability, not raw centipawns,** for move classification and anything compared across positions. A 300cp drop at +8 is not a blunder; at 0.0 it is. (Formula in 02.)
5. **Shared types live in one place** (see 01). If you need a new field, add it there and update every doc that references the type.
6. **Licenses matter.** Several core chess libraries are GPL/AGPL. Read 07 before adding a dependency, and record every new one in `THIRD_PARTY.md`.
7. **Every detector and every concept ships with test positions** (FENs with expected outputs). No tests, no merge. (See 08.)

## Default stack (change only with a recorded decision)

These are defaults chosen because the key chess libraries live there. Record
any change in `docs/decisions/` as a short ADR.

- **Analysis service:** Python 3.11+, `python-chess` (rules, PGN, UCI engine control, Syzygy probing), Stockfish via UCI.
- **Human-move model:** Maia-2 (`pip install maia2`) or Maia-3 for new work (see 05).
- **Client:** TypeScript. Board UI and rules library choice is a license decision (see 07).
- **Storage:** any relational DB; schemas in 01 and 06 are written to be portable.

## Conventions

- Squares in algebraic (`e4`), moves in UCI (`e2e4`) internally and SAN (`Nf3`) only for display.
- Positions are identified by FEN; for caching, use the first four FEN fields (board, side, castling, en passant).
- Evaluation is always stored from **White's point of view**; convert at display time.
- Rating bands are referred to by the band IDs in 03 (e.g. `B1`), never by ad-hoc numbers in code.
- Concept IDs are kebab-case and stable forever once shipped (e.g. `tactic-fork-knight`). Rename the display title, never the ID.

## Out of scope (for now)

- Online multiplayer beyond the peer-to-peer page in `web/p2p/` (ADR 0003), anti-cheat, tournaments.
- Variants other than standard chess.
- Any feature that requires an LLM.

## How to work on this repo

1. Find the layer your task touches in the table above and read that spec end to end.
2. Read the shared types in 01.
3. Write test positions first (08), then the code.
4. If the spec is wrong or silent, do the smallest reasonable thing, then update the spec in the same change and note it in the PR description.
