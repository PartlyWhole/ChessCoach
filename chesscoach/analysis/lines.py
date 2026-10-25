"""Line explanations (docs/02 §6.6): what happens, ply by ply, along an engine line.

`explain_line(board, moves, perspective)` replays a line (normally an engine PV) and records for
every ply the capture, check, mate, promotion, the material balance from `perspective`'s point of
view, and the tactical features the move creates: the move-based detectors run with the rest of
the line as their engine continuation, plus pins/skewers/traps the move creates on its
destination. No engine is called; the line is the evidence.

The outcome is settled, not read off the last ply: a line that stops right after a capture is
corrected by static exchange evaluation of the recapture, so "wins a knight" is never claimed
from the middle of an exchange. `decisive_ply` is the first ply from which the settled material
change holds to the end of the line (or the mating ply).
"""
from __future__ import annotations

from typing import Optional

import chess

from chesscoach.analysis.analyzer import TACTICAL_IDS, move_features, static_opportunities
from chesscoach.analysis.board_utils import PIECE_NAME, balance, ccolor, cname, see_target, sq
from chesscoach.analysis.phase import game_phase
from chesscoach.types import Color, LineExplanation, LineStep

MIN_SWING = 1          # pawn units: smaller settled changes are reported as outcome "none"


def _settled_balance(board: chess.Board, last: Optional[chess.Move], color: chess.Color) -> int:
    """Balance for `color`, corrected by SEE when the line ended on a capture that can be answered."""
    bal = balance(board, color)
    if last is None or board.is_game_over():
        return bal
    target = last.to_square
    p = board.piece_at(target)
    if p is None:
        return bal
    gain = see_target(board, target, board.turn)        # side to move recaptures?
    if gain is not None and gain > 0:
        bal += -gain if board.turn != color else gain
    return bal


def explain_line(board: chess.Board, moves: list[str], perspective: Color) -> LineExplanation:
    persp = ccolor(perspective)
    b = board.copy(stack=False)
    start = balance(b, persp)
    steps: list[LineStep] = []
    parsed = []
    for u in moves:
        m = chess.Move.from_uci(u)
        if not b.is_legal(m):
            break
        parsed.append(m)
        b.push(m)
    b = board.copy(stack=False)
    last = None
    for i, m in enumerate(parsed):
        mover = b.turn
        captured = None
        if b.is_en_passant(m):
            captured = "pawn"
        elif b.piece_at(m.to_square):
            captured = PIECE_NAME[b.piece_type_at(m.to_square)]
        san = b.san(m)
        before = b.copy(stack=False)
        b.push(m)
        phase = game_phase(b)
        feats = move_features(before, m, parsed[i + 1:], None, phase)
        feats += static_opportunities(before, m, [], phase)
        tactical = [f for f in feats if f.id in TACTICAL_IDS and f.side == cname(mover)]
        ids: list[str] = []
        squares: list[str] = []
        for f in tactical:
            if f.id not in ids:
                ids.append(f.id)
            squares += [s for s in f.squares if s not in squares]
        steps.append(LineStep(
            ply=i, move=m.uci(), san=san, mover=cname(mover), captured=captured,
            promotion=PIECE_NAME[m.promotion] if m.promotion else None,
            check=b.is_check(), mate=b.is_checkmate(), material=balance(b, persp) - start,
            feature_ids=ids, squares=squares))
        last = m
        if b.is_game_over():
            break

    mate_for: Optional[Color] = None
    if steps and steps[-1].mate:
        mate_for = steps[-1].mover
        net = steps[-1].material
        decisive = steps[-1].ply
        outcome = "mate"
    else:
        net = _settled_balance(b, last, persp) - start
        decisive = None
        outcome = "none"
        if abs(net) >= MIN_SWING:
            outcome = "material"
            sign = 1 if net > 0 else -1
            # First ply from which the material change stays at or beyond the settled change.
            # A trailing SEE correction counts as reached at the last ply.
            series = [s.material for s in steps]
            if series:
                series[-1] = net if sign * series[-1] < sign * net else series[-1]
            for i in range(len(series)):
                if all(sign * x >= sign * net for x in series[i:]):
                    decisive = steps[i].ply
                    break
    return LineExplanation(perspective=perspective, start_fen=board.fen(), steps=steps,
                           material_change=net, outcome=outcome, decisive_ply=decisive, mate_for=mate_for)
