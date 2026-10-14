# 02 — Layer 1: Position Analysis

Goal: given a position (and the move just played), produce `EngineResult`,
`MoveAssessment` and `PositionFeatures` (types in 01). This layer states
**facts only**. It never decides what to tell the player.

## 1. Engine wrapper

Use `python-chess`'s `chess.engine` module to drive Stockfish over UCI.

```python
import chess, chess.engine

engine = chess.engine.SimpleEngine.popen_uci("stockfish")
engine.configure({"Threads": 2, "Hash": 128})

def analyse(board: chess.Board, depth: int, multipv: int):
    infos = engine.analyse(board, chess.engine.Limit(depth=depth), multipv=multipv)
    lines = []
    for info in infos:
        score = info["score"].white()          # always White POV
        lines.append(dict(
            moves=[m.uci() for m in info.get("pv", [])],
            cp=score.score(),                  # None if mate
            mate=score.mate(),
            win_prob=win_prob(score),
            depth=info.get("depth", depth),
        ))
    return lines
```

Rules:
- Always request MultiPV ≥ 3 for live analysis; several detectors need the 2nd and 3rd lines.
- Engine processes are pooled (see 01). Don't share one `SimpleEngine` across threads.
- Stockfish's modern evaluation is a neural network (NNUE). Older versions exposed a per-term breakdown via the `eval` command (material, mobility, king safety, threats, passed pawns, space, ...). Current releases do not provide that breakdown, so **do not build features on it**. Our detectors below replace it.

## 2. Win probability

Convert centipawns to a 0..1 win probability for the side in question. Use the
logistic curve Lichess uses for its accuracy and move classification:

```python
import math
K = 0.00368208   # Lichess constant — verified 2026-10-13 against scalachess eval.scala

def win_prob_cp(cp: int) -> float:
    cp = max(-1000, min(1000, cp))   # Lichess clamps cp to ±1000 (Cp.CEILING) first
    return 1 / (1 + math.exp(-K * cp))

def win_prob(score) -> float:            # score: chess.engine.Score, White POV
    if score.is_mate():
        return 1.0 if score.mate() > 0 else 0.0
    return win_prob_cp(score.score())
```

Mover-POV conversion: `p_mover = p_white if mover == white else 1 - p_white`.

## 3. Move classification

`loss = max(0, win_prob_before - win_prob_after)` in mover POV, where *before*
is the best line's value and *after* is the value after the played move. When the
played move is one of the MultiPV lines of the *before* search, *after* is taken
from that line (same search, no depth noise between the two numbers); otherwise
from the best line of the analysis after the move.

Class precedence: `forced` → `book` → `best` → loss thresholds.

| Class | Condition (starting thresholds — tune with 08) |
|-------|------------------------------------------------|
| `book` | position+move found in opening book/explorer data with enough games |
| `forced` | only one legal move |
| `best` | played move == engine best move |
| `excellent` | loss < 0.02 |
| `good` | loss < 0.05 |
| `inaccuracy` | 0.05 ≤ loss < 0.10 |
| `mistake` | 0.10 ≤ loss < 0.15 |
| `blunder` | loss ≥ 0.15 |

These correspond to Lichess-style thresholds expressed on a 0..1 scale.
Additional rule: if the mover's win prob stays > 0.95 after the move, cap the
class at `inaccuracy` unless it throws away a forced mate — players up a queen
should not be told they "blundered" a won game.

Note: on the win-probability scale this guard is nearly always already satisfied
(after > 0.95 implies loss < 0.05), which is exactly why rule 4 prefers win
probability. It stays in the code as a safety net. Losing a forced mate is graded
by the same loss thresholds, which matches lila's "mate lost" advice: mate →
+7 is an inaccuracy, mate → equal is a blunder.

## 4. Sharpness

How much the position punishes a slightly-wrong move.

```
sharpness = clamp((wp(line1) - wp(line2)) / 0.15, 0, 1)   # mover POV
```

`sharpness ≈ 1` means "only move" — the coach should prompt before the player
moves only in positions like this (see 04). If fewer than 2 legal moves,
sharpness = 0.

## 5. Game phase

Simple and stable; avoid anything fancier until tests demand it.

- **opening:** the position is still in book, *or* fullmove ≤ 12 and at least 10 non-pawn, non-king pieces remain on the board.
- **endgame:** total non-pawn material (N=B=3, R=5, Q=9) ≤ 13 for both sides combined, or no queens and ≤ 2 minor/major pieces per side.
- **middlegame:** otherwise.

## 6. Detectors

Each detector is a pure function `(board, ctx) -> list[Feature]`, where `ctx`
holds the engine result for that position. One file per detector (a file may
emit a family of closely related ids, e.g. `pawns.py` emits all pawn-structure
ids). Each one declares its `feature_id`s, needs-engine flag, move-based flag,
and test positions (see 08). Code: `chesscoach/analysis/detectors/`.

**Move-based detectors** (`fork`, `double_attack`, `discovered_attack`,
`removing_defender`) describe what a move *m* created. `PositionFeatures` for a
position P therefore contains three kinds of feature:

| Kind | Marker in `Feature.data` | Meaning |
|------|--------------------------|---------|
| static | none | true of P as it stands |
| created | `created_by: <uci>` | created by the move that led to P (side = that move's mover) |
| opportunity | `via: <uci>` | available to the side to move: move-based detectors applied after the engine's best move, confirmed by the rest of the engine line |

**`Feature.side`.** Tactical features, outposts, open/half-open files,
`space_advantage` and `king_attackers`: the side that can exploit it.
Structural weaknesses and properties (`isolated_pawn`, `doubled_pawns`,
`backward_pawn`, `passed_pawn` family, `pawn_islands`, `weak_square`,
`bishop_pair`, `bad_bishop`, `king_safety_shield`, `king_in_center`,
`undeveloped_pieces`): the side that owns them. Where the two differ,
`data.owner` names the owner.

**Sub-ids** are emitted as separate features alongside the parent (e.g. a
discovered check emits both `discovered_attack` and `discovered_check`).

### 6.1 Tactical detectors

Definitions are given so that two implementations would agree. "Valuable" uses
P=1, N=3, B=3, R=5, Q=9, K=∞.

| feature_id | Definition |
|-----------|-----------|
| `hanging_piece` | A piece (not king) attacked by the opponent and either undefended, or attacked by a lower-value piece. Compute with static exchange evaluation (SEE); hanging iff SEE for the attacker > 0. SEE uses legal captures only (pins and king safety respected), least-valuable attacker first, either side may stop. |
| `fork` | After move *m*, the moved piece attacks ≥ 2 enemy targets where each target is the king or has SEE > 0 for us, **and** the engine's best line after *m* mates within 4 plies or wins ≥ 1 pawn unit of material within 4 plies (extended by one ply when the 4th ply is our capture, so the recapture counts). Without the engine confirmation it is only a `double_attack`. |
| `double_attack` | Same targets as fork, attacked by the moved piece alone or by the moved piece plus a slider whose line *m* uncovered (`data.pair = true`); engine confirmation not required. Used for hints, never claimed as a "winning fork". |
| `pin_absolute` | Enemy piece on a line between our slider and their king; it cannot legally move off the line. `python-chess`: `board.is_pinned(color, square)`. |
| `pin_relative` | Our slider attacks enemy piece X; the first piece behind X on that line is a non-king enemy piece Y of higher value than X, and with X removed our SEE on Y is > 0. Not reported if X can capture the slider with SEE ≥ 0. |
| `skewer` | Our slider attacks enemy piece A (king allowed); the first piece behind A on that line is an enemy piece B of lower value than A, and with A removed our SEE on B is > 0 (so a defended lower-value piece only counts when winning it still gains material). Not reported if A can capture the slider with SEE ≥ 0. |
| `discovered_attack` | Move *m* by piece A uncovers a line from our slider B to an enemy target: the king, or a piece on which our SEE > 0. Sub-id `discovered_check` if the target is the king. |
| `double_check` | Side to move is in check from two pieces. |
| `back_rank_weakness` | King on its back rank, all escape squares on the 2nd rank blocked by own pieces/attacked, and the back rank can be reached by an enemy rook/queen in one move along a file or rank. |
| `mate_threat` | Null-move search (below) finds mate for the opponent. |
| `overloaded_defender` | An enemy piece is the sole defender of ≥ 2 enemy pieces that we attack, each of which is currently safe (our SEE ≤ 0) but lost without that defender (our SEE > 0 with it removed). |
| `trapped_piece` | An enemy piece (not pawn/king) that we win where it stands (our SEE > 0) and every legal move of which loses material (SEE of that move < 0 for its owner). |
| `removing_defender` | Move *m* captures the sole defender D of an enemy piece T that we attack and that was safe before *m* (our SEE ≤ 0); the engine line then captures on T with one of our next two moves (within 4 plies — engine lines often insert a quiet move first) and the sequence from before *m*, through the reply to that capture, wins ≥ 1 pawn unit. Engine-confirmed. v1 covers capturing the defender only; deflection by a non-capture is not detected yet. |

Reference implementations to read before writing these: the Lichess puzzle
tagger (`tagger/cook.py` in `lichess-org/lichess-puzzler`) and the
`chess_detect` Python package. **The Lichess tagger is AGPL and `chess_detect`'s
license must be checked before any reuse — read them for ideas, don't copy
code** (see 07).

### 6.2 Positional detectors

| feature_id | Definition |
|-----------|-----------|
| `isolated_pawn` | Pawn with no friendly pawns on adjacent files. Sub-id `isolated_queen_pawn` for d-file. |
| `doubled_pawns` | ≥ 2 friendly pawns on one file. |
| `backward_pawn` | Pawn that has friendly pawns on adjacent files but none behind or level with it, whose stop square is attacked by an enemy pawn. (Pawns with no adjacent friendly pawns are `isolated_pawn`, not backward.) |
| `passed_pawn` | No enemy pawns in front of it on its own or adjacent files. Sub-ids `protected_passed` (defended by a friendly pawn) and `outside_passed` (every other pawn on the board is on one side of it, and the nearest enemy pawn is ≥ 3 files away). |
| `pawn_islands` | Count of groups of adjacent files containing friendly pawns (data: count). |
| `outpost` | Square on ranks 4–6 from our side that no enemy pawn can ever attack (no enemy pawns on adjacent files ahead of it) and that is defended by our pawn. One feature per square; `data.occupant` names our piece on it, if any. |
| `weak_square` | Square on ranks 3–4 of our camp, not occupied by our pawn, that none of our pawns can ever defend again (no own pawn on an adjacent file behind it) and that an enemy knight, bishop, rook or queen attacks now. Ranks 1–2 are excluded: they are pawn-undefendable in nearly every position. |
| `open_file` / `half_open_file` | No pawns / no own pawns (but enemy pawns) on a file. One feature per side that may use the file; `data.occupants` lists that side's rooks/queens on it (possibly empty). |
| `bishop_pair` | Side has both bishops and opponent does not. |
| `bad_bishop` | ≥ 2 of the owner's c/d/e/f pawns stand on the bishop's colour and are fixed (an enemy pawn directly in front). |
| `king_safety_shield` | King on its back rank on files a–c or f–h. For each of the three shield files (king file ±1), the pawn is *missing* if not on the 2nd or 3rd rank, *advanced* if on the 3rd. Emitted when either count > 0 (data: `missing`, `advanced`). |
| `king_attackers` | Number of enemy pieces (not pawns/king) attacking squares adjacent to the king; emitted when ≥ 1 (data: count, pieces). |
| `undeveloped_pieces` | In the opening phase: minor pieces still on starting squares after move 8. |
| `king_in_center` | In opening/middlegame: king on the d or e file, and either it has lost castling rights or it is move 10 or later without castling, and the d- or e-file has no pawn of the king's side. |
| `space_advantage` | Count of squares on files c–f in the opponent's half that we attack and no enemy pawn attacks; reported for the side ahead only when the difference is ≥ 4. |

### 6.3 Pawn structure classifier

Produces `structure_id`. Approach (adapted from LiChess Tools' pawn-structure
feature, reimplemented — do not copy): encode each side's pawns per file as a
character (`X` missing, `0` unmoved, `1`–`5` ranks advanced), then score
similarity against a table of named structures. Return the best match if its
score ≥ threshold, else `null`.

Matching is exact on the cells a structure specifies (threshold 1.0, tunable as
`structure.threshold`); each template is also tried colour-reversed and the
result carries the owner side. The more specific template wins ties.
`open_center` (≤ 1 pawn on the d+e files) and `closed_center` (≥ 2 White d/e
pawns blocked by a Black pawn directly in front) are fallbacks used only when no
named structure matches. Code: `chesscoach/analysis/structure.py`.

**Owner** of each named structure (whose plans are `plans.owner` in 03): `iqp` the side with
the isolated d-pawn; `hanging_pawns` the side with the c+d pawns; `carlsbad` the side with
d4+e3 and no c-pawn (minority-attack side); `slav_triangle` the side with c6-d5-e6 (and the
f-pawn not on f5, otherwise it is a Stonewall); `french_advance` / `caro_kann_advance` the
side with the e5 spearhead; `kings_indian_closed` the side with c4-d5-e4; `maroczy_bind` and
`hedgehog` the side with c4+e4; `sicilian_scheveningen` the side with e4 and the c-pawn on c2;
`stonewall` the side with c3-d4-e3-f4. `french_advance` accepts the defender's c-pawn on c7,
c5, c4 or gone.

Start with these named structures (each gets a concept with plans in 03):
`iqp`, `hanging_pawns`, `carlsbad`, `slav_triangle`, `french_advance`,
`caro_kann_advance`, `kings_indian_closed`, `maroczy_bind`, `hedgehog`,
`sicilian_scheveningen`, `stonewall`, `open_center`, `closed_center`.

### 6.4 Threat detection (null move)

"What is my opponent threatening?" is the most valuable question a coach asks.

```python
def threats(board: chess.Board, ctx) -> list[ThreatInfo]:
    if board.is_check():
        return []                       # null move illegal in check
    b = board.copy()
    b.push(chess.Move.null())           # pass the turn
    lines = analyse(b, depth=12, multipv=2)
    base = ctx.win_prob_for(opponent)   # opponent's win prob in the real position
    out = []
    for line in lines:
        gain = wp_for(line, opponent) - base
        if gain >= 0.10:
            out.append(ThreatInfo(by=opponent, move=line.moves[0],
                                  gain_win_prob=gain,
                                  feature_ids=run_tactical_detectors_on(b, line)))
    return out
```

Only *aggressive* moves count as threats: a capture, a check, a move that realises a
tactical feature, or a move that leaves one of our pieces newly en prise (feature id
`attack`) — or a mate. Without this filter the gain test also rewards the opponent
rescuing its own hanging piece or defending against our mate, which are not threats
(found by concept tests, 2026-10-13).

Caveat: in zugzwang-like endgames the null move misleads. Skip threat detection
when `phase == "endgame"` and total material ≤ 6 pawn units excluding kings.

### 6.5 Endgame tablebases

For ≤ 7 pieces, prefer Syzygy probes over the engine for result and DTZ
(`chess.syzygy.open_tablebase(path)`). Mark the `EngineResult` as
`tablebase=True` (field defined in 01) so L2 can use exact-result concepts
("this is a theoretical draw"). Lines are legal moves ranked by WDL then DTZ;
win prob is 1 / 0.5 / 0 (cursed wins and blessed losses count as draws), `cp`
is ±1000 for wins and 0 for draws. Enable by setting `CHESSCOACH_SYZYGY`.

## 7. Output contract

`analyze(fen_before, move) -> (EngineResult_before, EngineResult_after,
MoveAssessment, PositionFeatures_before, PositionFeatures_after)`

- Features are computed for **both** sides in each position; L2 filters by side.
- A detector that throws must not fail the whole analysis: log, drop its features, increment a metric.
