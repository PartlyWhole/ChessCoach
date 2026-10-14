"""Concept matcher: L1 facts → ConceptHit candidates (docs/03 "Matching algorithm").

Which features each role may use (player = the side whose move/turn it is about):

| role      | position          | idea user | features considered                                         |
|-----------|-------------------|-----------|-------------------------------------------------------------|
| missed    | before the move   | player    | opportunities whose `via` != played move; static ones the   |
|           |                   |           | move did not act on (move.to_square not in feature.squares) |
| allowed   | after the move    | opponent  | opponent opportunities (`via`); static ones new since before |
| played    | after the move    | player    | `created_by` == played move; static ones new since before   |
|           |                   |           | that involve the moved piece's square                       |
| available | current, player   | player    | opportunities (`via`) and static                            |
|           | to move           |           |                                                             |
| plan      | current           | player    | static (structure etc.)                                     |

`side: user` in a condition (the default) means Feature.side == idea user; `other` the
opposite; `any` either.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional

import chess

from chesscoach.analysis.board_utils import ccolor, join_names
from chesscoach.analysis.winprob import line_wp
from chesscoach.concepts.predicates import PREDICATES, PredicateInput
from chesscoach.concepts.registry import BANDS, ROLE_WEIGHT, Concept, Registry
from chesscoach.types import (Color, ConceptHit, EngineResult, Feature, Highlight, MoveAssessment,
                              PositionFeatures, other)

SWING_FULL = 0.15


@dataclass
class RoleView:
    role: str
    board: chess.Board                      # position the role is matched on
    features: list[Feature]
    pf: PositionFeatures
    engine: Optional[EngineResult]
    user: Color                             # who uses the idea
    player: Color
    gain: Optional[float]                   # win prob the idea gains for its user (engine.min_gain)
    swing: Optional[float]                  # for importance (missed/allowed)
    move_class: Optional[str]
    idea_move: Optional[chess.Move]         # the move that realises the idea ({move_san})
    played: Optional[chess.Move] = None
    board_before: Optional[chess.Board] = None


# Features a move can create without touching their squares (trapping a piece from afar).
REMOTE_EFFECT = {"trapped_piece"}
# As hint/missed material only the *creating* move counts: an already-trapped piece is simply
# hanging (safety-hanging-piece covers it), and "{capture} traps the knight" would be false.
OPPORTUNITY_ONLY = {"trapped_piece"}
# A player who found a best/excellent move did not "miss" or "allow" anything.
NOT_A_MISS = {"best", "excellent", "forced", "book"}


def _key(f: Feature) -> tuple:
    return (f.id, f.side, tuple(sorted(f.squares)), tuple(sorted(f.pieces or [])))


def _static(f: Feature) -> bool:
    return "via" not in f.data and "created_by" not in f.data


# ---------------- condition evaluation ----------------
def _cmp(actual: Any, spec: Any) -> bool:
    if isinstance(spec, dict):
        for op, v in spec.items():
            if actual is None:
                return False
            if op == "eq" and actual != v:
                return False
            if op == "gte" and not actual >= v:
                return False
            if op == "lte" and not actual <= v:
                return False
            if op == "in" and actual not in v:
                return False
            if op == "len_gte" and not len(actual) >= v:
                return False
            if op == "len_lte" and not len(actual) <= v:
                return False
        return True
    return actual == spec


def feature_matches(f: Feature, cond: dict, user: Color) -> bool:
    if f.id != cond["feature"]:
        return False
    side = cond.get("side", "user")
    if side == "user" and f.side != user or side == "other" and f.side == user:
        return False
    if "piece" in cond and not _cmp(f.data.get("piece"), cond["piece"]):
        return False
    for k, v in cond.items():
        if k.startswith("data.") and not _cmp(f.data.get(k[5:]), v):
            return False
    return True


def _first(features: Iterable[Feature], cond: dict, user: Color) -> Optional[Feature]:
    return next((f for f in features if feature_matches(f, cond, user)), None)


# ---------------- slots ----------------
def _resolve(expr: str, feature: Feature) -> Optional[str]:
    """`feature.squares[0]`, `feature.data.target_names`, `feature.pieces[1]`, `feature.side`."""
    if not expr.startswith("feature."):
        return None
    cur: Any = feature
    for part in expr[len("feature."):].split("."):
        idx = None
        if part.endswith("]"):
            part, idx = part[:-1].split("[")
        if isinstance(cur, Feature):
            cur = getattr(cur, part, None)
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if idx is not None:
            if not isinstance(cur, list) or int(idx) >= len(cur):
                return None
            cur = cur[int(idx)]
        if cur is None:
            return None
    if isinstance(cur, list):
        return join_names([str(x) for x in cur]) if cur else None
    return str(cur)


def _san(board: chess.Board, moves: list[chess.Move], limit: int = 6) -> Optional[str]:
    b = board.copy(stack=False)
    out = []
    for m in moves[:limit]:
        if not b.is_legal(m):
            break
        prefix = f"{b.fullmove_number}." if b.turn == chess.WHITE else (f"{b.fullmove_number}..." if not out else "")
        out.append(prefix + b.san(m))
        b.push(m)
    return " ".join(out) if out else None


def builtin_slots(view: RoleView, concept: Concept, feature: Optional[Feature]) -> dict[str, str]:
    s: dict[str, str] = {"user_color": view.user.capitalize(), "other_color": other(view.user).capitalize()}
    if view.idea_move is not None and view.board.is_legal(view.idea_move):
        s["move_san"] = view.board.san(view.idea_move)
    if view.engine and view.engine.lines and view.engine.lines[0].moves:
        best = chess.Move.from_uci(view.engine.lines[0].moves[0])
        if view.board.is_legal(best):
            s["best_san"] = view.board.san(best)
        pv = _san(view.board, [chess.Move.from_uci(m) for m in view.engine.lines[0].moves])
        if pv:
            s["pv_san"] = pv
    threats = [t for t in view.pf.threats if t.by != view.user] if view.pf else []
    if threats and view.board.turn == ccolor(view.user):
        t = max(threats, key=lambda x: x.gain_win_prob)
        b = view.board.copy(stack=False)
        b.push(chess.Move.null())
        mv = chess.Move.from_uci(t.move)
        if b.is_legal(mv):
            s["threat_move_san"] = b.san(mv)
    if concept.plans and feature is not None and feature.id == "structure":
        owner = feature.data.get("owner")
        key = "owner" if owner in (None, view.user) else "opponent"
        lines = concept.plans.get(key) or []
        if lines:
            s["plan"] = lines[0]
    return s


# ---------------- trigger ----------------
def evaluate(concept: Concept, view: RoleView) -> Optional[tuple[list[Feature], dict[str, str]]]:
    """Returns (evidence features, slot values) if the trigger matches this role view."""
    t = concept.trigger
    if "phase" in t and view.pf.phase not in t["phase"]:
        return None
    if "structure" in t and view.pf.structure_id not in t["structure"]:
        return None
    if "move_class" in t and view.role in ("missed", "allowed") and view.move_class not in t["move_class"]:
        return None
    if view.role in ("missed", "allowed") and view.move_class in NOT_A_MISS:
        return None
    if "sharpness_gte" in t and (view.engine is None or view.engine.sharpness < t["sharpness_gte"]):
        return None
    if "tablebase" in t and (view.engine is None or view.engine.tablebase != t["tablebase"]):
        return None
    if "moved_piece" in t:
        if view.played is None or view.board_before is None:
            return None
        pt = view.board_before.piece_type_at(view.played.from_square)
        if pt is None or chess.piece_name(pt) not in t["moved_piece"]:
            return None
    min_gain = (t.get("engine") or {}).get("min_gain")
    if min_gain is not None and view.role != "plan" and (view.gain is None or view.gain < min_gain):
        return None

    evidence: list[Feature] = []
    extra: dict[str, str] = {}
    target_sq = None
    if t.get("idea_targets_feature") and view.idea_move is not None and view.role != "played":
        target_sq = chess.square_name(view.idea_move.to_square)
    for i, cond in enumerate(t.get("all", [])):
        f = None
        if i == 0 and target_sq is not None:
            # Several features can match (two loose pieces): use the one the idea move acts on.
            f = next((x for x in view.features if feature_matches(x, cond, view.user)
                      and (target_sq in x.squares or x.data.get("via") == view.idea_move.uci())), None)
        f = f or _first(view.features, cond, view.user)
        if f is None:
            return None
        evidence.append(f)
    if "any" in t:
        hits = [f for cond in t["any"] for f in view.features if feature_matches(f, cond, view.user)]
        if not hits:
            return None
        evidence.append(hits[0])
    for cond in t.get("none", []):
        if _first(view.features, cond, view.user) is not None:
            return None
    if "structure" in t:
        sf = next((f for f in view.features if f.id == "structure"), None)
        if sf is not None and sf not in evidence:
            evidence.append(sf)
    if "predicate" in t:
        res = PREDICATES[t["predicate"]](PredicateInput(
            board=view.board, features=view.pf, engine=view.engine, user=view.user,
            move=view.played, board_before=view.board_before))
        if res is None:
            return None
        evidence.append(res.feature)
        extra.update(res.slots)
    primary = evidence[0] if evidence else None

    # A via-feature carries its own realising move (e.g. the fork square move).
    if primary is not None and "via" in primary.data and view.role in ("missed", "available", "allowed"):
        view = RoleView(**{**view.__dict__, "idea_move": chess.Move.from_uci(primary.data["via"])})

    # The {move_san} claim must be about this feature: the realising move lands on one of its squares.
    if t.get("idea_targets_feature") and view.role != "played":
        if primary is None or view.idea_move is None \
                or chess.square_name(view.idea_move.to_square) not in primary.squares:
            return None

    slots = builtin_slots(view, concept, primary)
    slots.update(extra)
    for name, expr in concept.slots.items():
        if name in slots:
            continue
        val = _resolve(expr, primary) if primary is not None else None
        if val is not None:
            slots[name] = val
    return evidence, slots


def _highlight(evidence: list[Feature], idea_move: Optional[chess.Move]) -> Highlight:
    squares: list[str] = []
    for f in evidence[:1]:
        for s in f.squares[:4]:
            if s not in squares:
                squares.append(s)
    arrows = []
    if idea_move is not None:
        arrows.append((chess.square_name(idea_move.from_square), chess.square_name(idea_move.to_square)))
    return Highlight(squares=squares, arrows=arrows)


def _evidence_ids(evidence: list[Feature], engine: Optional[EngineResult]) -> list[str]:
    out = []
    for f in evidence:
        tag = f.id + ("@" + ",".join(f.squares[:3]) if f.squares else "")
        if "via" in f.data:
            tag += f"|via:{f.data['via']}"
        out.append(tag)
    if engine and engine.lines and engine.lines[0].moves:
        out.append("engine:" + " ".join(engine.lines[0].moves[:6]))
    return out


# ---------------- role views ----------------
def views_after_move(board_before: chess.Board, move: chess.Move, assessment: MoveAssessment,
                     eng_before: EngineResult, pf_before: PositionFeatures,
                     eng_after: EngineResult, pf_after: PositionFeatures) -> list[RoleView]:
    player = assessment.mover
    opp = other(player)
    after = board_before.copy(stack=False)
    after.push(move)
    before_keys = {_key(f) for f in pf_before.features if _static(f)}

    missed = [f for f in pf_before.features if f.side == player and (
        ("via" in f.data and f.data["via"] != move.uci())
        or (_static(f) and f.id not in OPPORTUNITY_ONLY and chess.square_name(move.to_square) not in f.squares))]
    allowed = [f for f in pf_after.features if f.side == opp and (
        "via" in f.data or (_static(f) and _key(f) not in before_keys))]
    frm, to = chess.square_name(move.from_square), chess.square_name(move.to_square)
    # Same feature (id, side, squares) before the move that already involved the moved piece:
    # e.g. a rook sliding along a file it already held does not "take the open file".
    held = {(f.id, f.side, tuple(sorted(f.squares))) for f in pf_before.features
            if _static(f) and frm in (f.pieces or [])}
    played = [f for f in pf_after.features if f.side == player and (
        f.data.get("created_by") == move.uci()
        or (_static(f) and _key(f) not in before_keys
            and (f.id, f.side, tuple(sorted(f.squares))) not in held
            and (f.id in REMOTE_EFFECT or to in f.squares or to in (f.pieces or []))))]

    # Gain of the played move over the best alternative (for praise).
    alt = [line_wp(l, player) for l in eng_before.lines if l.moves and l.moves[0] != move.uci()]
    played_gain = max(0.0, assessment.win_prob_after - max(alt)) if alt else None
    best_move = chess.Move.from_uci(assessment.best_move) if assessment.best_move else None
    opp_best = chess.Move.from_uci(eng_after.lines[0].moves[0]) if eng_after.lines and eng_after.lines[0].moves else None
    common = dict(player=player, move_class=assessment.move_class, played=move, board_before=board_before)
    return [
        RoleView(role="missed", board=board_before, features=missed, pf=pf_before, engine=eng_before,
                 user=player, gain=assessment.loss, swing=assessment.loss, idea_move=best_move, **common),
        RoleView(role="allowed", board=after, features=allowed, pf=pf_after, engine=eng_after,
                 user=opp, gain=assessment.loss, swing=assessment.loss, idea_move=opp_best, **common),
        RoleView(role="played", board=after, features=played, pf=pf_after, engine=eng_after,
                 user=player, gain=played_gain, swing=None, idea_move=move, **common),
    ]


def views_for_position(board: chess.Board, engine: Optional[EngineResult], pf: PositionFeatures) -> list[RoleView]:
    player: Color = "white" if board.turn == chess.WHITE else "black"
    gain = None
    if engine and len(engine.lines) >= 2:
        gain = max(0.0, line_wp(engine.lines[0], player) - line_wp(engine.lines[1], player))
    elif engine and engine.lines:
        gain = 0.0
    best = chess.Move.from_uci(engine.lines[0].moves[0]) if engine and engine.lines and engine.lines[0].moves else None
    avail = [f for f in pf.features if f.side == player and (
        "via" in f.data or (_static(f) and f.id not in OPPORTUNITY_ONLY))]
    statics = [f for f in pf.features if _static(f)]
    common = dict(pf=pf, engine=engine, user=player, player=player, move_class=None)
    return [
        RoleView(role="available", board=board, features=avail, gain=gain, swing=None, idea_move=best, **common),
        RoleView(role="plan", board=board, features=statics, gain=None, swing=None, idea_move=None, **common),
    ]


# ---------------- matching ----------------
def eligible(concept: Concept, band: str, review: bool = False) -> bool:
    """Player's band, one band above (policy scores it at 0.5, 04), and band−1 in review."""
    i = BANDS.index(band)
    ok = {band}
    if i + 1 < len(BANDS):
        ok.add(BANDS[i + 1])
    if review and i > 0:
        ok.add(BANDS[i - 1])
    return bool(ok & set(concept.bands))


def match(registry: Registry, views: list[RoleView], band: str, review: bool = False) -> list[ConceptHit]:
    hits: list[ConceptHit] = []
    for concept in registry:
        if not eligible(concept, band, review):
            continue
        for view in views:
            if view.role not in concept.roles:
                continue
            res = evaluate(concept, view)
            if res is None:
                continue
            evidence, slots = res
            importance = concept.base_importance * ROLE_WEIGHT[view.role]
            if view.role in ("missed", "allowed"):
                importance *= min(1.0, (view.swing or 0.0) / SWING_FULL)
            idea = chess.Move.from_uci(evidence[0].data["via"]) if evidence and "via" in evidence[0].data \
                else view.idea_move
            hits.append(ConceptHit(
                concept_id=concept.id, role=view.role, importance=round(importance, 4), slots=slots,
                highlight=_highlight(evidence, idea), evidence=_evidence_ids(evidence, view.engine)))
    return dedupe(registry, hits)


def dedupe(registry: Registry, hits: list[ConceptHit]) -> list[ConceptHit]:
    """Keep one hit per (concept, role); when two hits share evidence, the more specific
    concept (a descendant via `parent`) beats its ancestor."""
    best: dict[tuple[str, str], ConceptHit] = {}
    for h in hits:
        k = (h.concept_id, h.role)
        if k not in best or h.importance > best[k].importance:
            best[k] = h
    kept = list(best.values())
    drop = set()
    for a in kept:
        anc = registry.ancestors(a.concept_id)
        for b in kept:
            if b.concept_id in anc and b.role == a.role:
                fa = {e.split("|")[0] for e in a.evidence if not e.startswith("engine:")}
                fb = {e.split("|")[0] for e in b.evidence if not e.startswith("engine:")}
                if _same_evidence(fa, fb):
                    drop.add((b.concept_id, b.role))
    return [h for h in kept if (h.concept_id, h.role) not in drop]


def _same_evidence(a: set[str], b: set[str]) -> bool:
    """Evidence tags are `<feature_id>@<squares>`; different feature ids for the same squares
    (fork vs double_attack on the same move) count as shared evidence."""
    sq_a = {e.split("@", 1)[1] for e in a if "@" in e}
    sq_b = {e.split("@", 1)[1] for e in b if "@" in e}
    return bool(a & b) or bool(sq_a & sq_b)
