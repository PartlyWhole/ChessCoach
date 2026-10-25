# 03 — Layer 2: Concept Library

The concept library is the product's core asset: a chess textbook encoded as
data. Each concept says **when it applies** (in terms of L1 features), **who
it's for** (rating bands), and **what to say** (templates per hint level).

Concepts are data files, not code. Chess experts author and review them; code
only evaluates triggers and fills templates.

## Rating bands

| Band | Rating range | Teaching focus (after the Steps Method's progression) |
|------|--------------|------------------------------------------------------|
| `B0` | < 800 | Safety: hanging pieces, checks/captures/threats, basic mates |
| `B1` | 800–1199 | One-move tactics (forks, pins, skewers), opening principles |
| `B2` | 1200–1599 | Preparatory tactical moves (luring, removing the defender, clearance), simple endgames, piece activity |
| `B3` | 1600–1999 | Pawn structures and plans, weak squares, prophylaxis, technical endgames |
| `B4` | 2000+ | Imbalances, deep structures, exchange decisions |

Ratings here mean the app's own rating scale (see 06), not FIDE.

Design note: the Steps Method (Brunia & van Wijgerden, official method of the
Royal Dutch Chess Federation) deliberately keeps players at the early steps on
tactics because their games are decided by tactics, and introduces preparatory
tactical moves (luring, eliminating the defence, chasing, clearing) at a later
step. Follow that ordering: **don't teach positional concepts to B0–B1 players
unless they are about piece safety or development.**

## Concept record schema

One YAML file per concept in `concepts/<category>/<concept_id>.yaml`.

```yaml
id: tactic-fork-knight            # kebab-case, permanent
title: Knight fork                # display name, can change
category: tactic                  # tactic | positional | structure | endgame | opening | safety | defence
bands: [B1, B2]                   # who this concept is taught to
base_importance: 0.8              # 0..1, author's judgment
prerequisites: [safety-hanging-piece]

trigger:                          # evaluated by the concept matcher
  roles: [missed, allowed, played, available]
  all:
    - feature: fork
      piece: knight               # optional filter on Feature.data.piece
  engine:
    min_gain: 0.10                # win-prob the idea gains for its user

slots:                            # how to fill template variables
  square:  feature.squares[0]
  targets: feature.data.target_names   # "queen and rook"

templates:                        # one entry per role × hint level
  missed:
    1: "There was a tactical shot here for your knight. Want to try again?"
    2: "Look at what your knight could attack from {square}."
    3: "{move_san} forks the {targets}. A knight fork attacks two pieces at once, and the opponent can only save one."
  allowed:
    1: "Careful — check what your opponent's knights can reach."
    2: "Your move let a knight jump to {square}."
    3: "After your move, {move_san} forks your {targets}."
  played:
    0: "Nice fork — your knight hits the {targets} at once."
  available:
    1: "Is there a square where your knight attacks two things?"
    2: "Look at {square}."

drill:                            # how to turn it into an SRS card (see 06)
  kind: find_move
  max_solution_plies: 3

tests: tests/positions/concepts/tactic-fork-knight.yaml   # format in 08 — required

review:                           # AGENTS rule 2: AI-drafted text ships only once approved
  status: draft                   # draft | approved
  by: ""                          # reviewer
  date: ""
```

**Review gate.** The registry (`chesscoach/concepts/registry.py`) loads only
`review.status: approved` concepts unless started with `allow_unreviewed`
(env `CHESSCOACH_ALLOW_UNREVIEWED=1`, development and tests only). The v1
concept set and `templates/en/_fallback.yaml` were drafted with AI help and are
all `draft`: until a chess expert approves them, a production build coaches
with no text at all.

Concept test files use the shared position format in 08, with
`expect: { role: <role>, slots: {...} }` per case.

### Trigger language

Keep it small and declarative. Supported keys:

- `all` / `any` / `none`: lists of feature conditions.
- `feature: <id>` plus optional filters on `side`, `piece`, `data.<key>` with `eq | gte | lte | in`.
- `phase: [opening, middlegame, endgame]`
- `structure: [<structure_id>, ...]`
- `move_class: [mistake, blunder]` (for `missed` / `allowed` roles)
- `engine.min_gain`: the concept's idea must be confirmed by the engine line. The
  gain per role: missed/allowed = the player's win-prob loss; played = played
  move's win prob minus the best other MultiPV line; available = best line minus
  2nd-best line for the side to move; plan = not checked.
- `sharpness_gte`
- `idea_targets_feature: true`: the move named by `{move_san}` (engine best move,
  or the opponent's best reply for `allowed`) must land on one of the primary
  feature's squares — so "{move_san} wins the knight on c3" is only said when it does.
- `moved_piece: [rook]`: the played move moved one of these piece types.
- `tablebase: true|false`: the analysis came from a Syzygy probe.
- Data filters also accept `len_gte` / `len_lte` for list values.
- `side: user | other | any` (default `user`, the side the idea is for: the player
  for missed/played/available/plan, the opponent for allowed).

If a concept cannot be expressed with these keys, add a **named predicate** in
code (`predicate: rook_behind_passer`) with its own tests. Predicates live in
`chesscoach/concepts/predicates.py` and declare the slots they fill; the build
checks templates against them. Do not grow
the trigger language into a programming language.

### Roles

| Role | Which position is matched | Typical use |
|------|---------------------------|-------------|
| `missed` | *before* the player's move, player's features | Player didn't use an available idea |
| `allowed` | *after* the player's move, opponent's features/threats | Player's move created a problem |
| `played` | *after* the player's move, player's features, move matches | Praise |
| `available` | current position, player to move | Live hint |
| `plan` | current position, structure-based | Strategic suggestion |

### Templates

- Write in second person, present tense, short sentences. Max 2 sentences per level.
- Level 1 asks a question or points at an area, never names the move.
- Level 2 names a square or piece.
- Level 3 gives the move and the reason.
- Use `{move_san}` only at level 3.
- Every `{slot}` must be fillable from detector output; the build fails on unknown slots.
- No hedging words ("probably", "might be") — if a claim needs hedging, the trigger is too loose.
- Localize by keeping templates in `templates/<lang>/<concept_id>.yaml` keyed identically.

## Matching algorithm

Which features each role may use is defined in the table at the top of
`chesscoach/concepts/matcher.py` (opportunities carry `data.via`, features
created by the move just played carry `data.created_by`, see 02 §6).

Role rules found by the concept tests (2026-10-13): `missed`/`allowed` never fire when the
move was `best`, `excellent`, `forced` or `book`; "new since before" compares against static
features only; `trapped_piece` counts for `played` even though the trapping move does not
touch the trapped piece's square, and as `missed`/`available` material only when it is an
opportunity (an already-trapped piece is a hanging piece).

The matcher includes concepts for the player's band **and one band above** (so
the policy's `band_fit` 0.5 in 04 can apply), plus band−1 in review.

```
for each concept in registry filtered by player's band (and band−1 for review):
    for each role the concept declares:
        pick the position/side for that role (table above)
        if trigger matches:
            importance = base_importance
                       × role_weight[role]            # allowed 1.0, missed 0.9, available 0.7, plan 0.5, played 0.4
                       × min(1, eval_swing / 0.15)    # for missed/allowed
            emit ConceptHit(...)
deduplicate: if two hits share evidence, keep the more specific (subtype beats parent, e.g. tactic-fork-knight beats tactic-double-attack)
```

Specificity is declared with `parent: <concept_id>` in the record.

## Initial concept set (target for v1: ~45 concepts)

Ship B0–B2 first. Each line is one concept file.

**v1 status (2026-10-13):** 43 concepts drafted (all `review: draft`), each with
≥ 3 positive / ≥ 2 negative test positions covering every declared role. Not yet
built, because the detector they need does not exist: `safety-queen-early`,
`opening-control-center`, `opening-same-piece-twice`, `opening-dont-block-pawns`,
`tactic-exploit-pin`, `tactic-deflection`, `tactic-decoy`, `tactic-clearance`,
`tactic-zwischenzug`, `defence-counterattack`, `defence-block-check-vs-move-king`,
`endgame-opposition`, `endgame-king-activity`, `endgame-lucena`,
`endgame-philidor`, `positional-improve-worst-piece`. Added beyond the list:
`structure-*` for every structure id, including `structure-open-center` and
`structure-closed-center`.

**Safety (B0–B1)**
`safety-hanging-piece`, `safety-undefended-after-move`, `safety-check-captures-threats` (meta prompt), `safety-queen-early`, `safety-king-in-center`

**Opening principles (B0–B1)**
`opening-develop-minors`, `opening-control-center`, `opening-castle-early`, `opening-same-piece-twice`, `opening-dont-block-pawns`

**Basic tactics (B1–B2)**
`tactic-double-attack`, `tactic-fork-knight`, `tactic-fork-pawn`, `tactic-fork-queen`, `tactic-pin-absolute`, `tactic-pin-relative`, `tactic-exploit-pin`, `tactic-skewer`, `tactic-discovered-attack`, `tactic-discovered-check`, `tactic-double-check`, `tactic-back-rank-mate`, `tactic-trapped-piece`

**Preparatory tactics (B2)**
`tactic-remove-defender`, `tactic-overloaded-defender`, `tactic-deflection`, `tactic-decoy`, `tactic-clearance`, `tactic-zwischenzug`

**Defence (B1–B2)**
`defence-what-is-threatened` (uses null-move threats), `defence-counterattack`, `defence-block-check-vs-move-king`

**Basic mates & endgames (B0–B2)**
`endgame-kq-vs-k`, `endgame-kr-vs-k`, `endgame-opposition`, `endgame-square-of-pawn`, `endgame-king-activity`, `endgame-rook-behind-passer`, `endgame-lucena`, `endgame-philidor`

**Positional (B2–B3)**
`positional-outpost-knight`, `positional-open-file-rook`, `positional-bad-bishop`, `positional-bishop-pair`, `positional-weak-square`, `positional-improve-worst-piece`

**Structures & plans (B3)** — one concept per `structure_id` in 02 §6.3, `role: plan`, e.g. `structure-iqp-attack` / `structure-iqp-blockade`, `structure-carlsbad-minority-attack`, `structure-french-advance-break-c5-f6`.

## Structure → plan knowledge

Each structure concept carries plans for **both** sides:

```yaml
id: structure-iqp
category: structure
bands: [B3, B4]
trigger: { structure: [iqp] }
plans:
  owner:      # side with the isolated pawn
    - "Keep pieces on — your pieces are more active and the d-pawn supports outposts on e5 and c5."
    - "Look for the d4-d5 break when your pieces are ready."
  opponent:
    - "Blockade the square in front of the pawn with a knight."
    - "Trade pieces; the pawn becomes weaker in the endgame."
```

The idea of linking pawn-structure classes to plans is old and well
established in chess programming research (e.g. knowledge-based programs that
associated pawn-structure classes with plans). Our version is simpler: plans
are text for the player, not search guidance.

## Authoring workflow

1. Chess expert drafts the concept YAML and ≥ 5 test positions (3 positive, 2 negative).
2. Engineer adds any missing detector/predicate with its own tests.
3. CI runs the concept against its tests and against a 10k-position regression set (08) and reports how often it fires per 100 positions. A concept firing in > 5% of random middlegame positions is almost always too loose.
4. Second expert reviews text and a sample of 20 real-game hits. Tool: the site's `/review/` page
   shows every concept's text at each hint level on its test positions (as the browser coach
   renders it), lets the expert edit text (checked against the rules above), approve or request
   changes, and download the decisions; `python tools/apply_review.py decisions.json` writes them
   into the YAML (`review: {status, by, date, note}`), re-validates, and the change ships through a
   normal commit. Approval order does not matter: an approved concept may have a draft parent.
5. Merge.
