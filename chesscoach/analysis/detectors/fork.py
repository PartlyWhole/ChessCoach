"""fork / double_attack (02 §6.1).

fork: after move m the moved piece attacks >= 2 targets (enemy king, or enemy piece with
SEE > 0 for the mover) AND the engine's best line after m wins material (>= 1 pawn unit,
recapture included) or mates within 4 plies.
double_attack: same targets, by the moved piece alone or together with a slider whose line
m uncovered; no engine confirmation. Used for hints, never claimed as a winning fork.
"""
from __future__ import annotations

import chess

from chesscoach.analysis.board_utils import (PIECE_NAME, SLIDERS, cname, join_names,
                                             pv_material_gain, sq, valuable_target)
from chesscoach.analysis.detectors.base import DetectorContext
from chesscoach.types import Feature

FEATURE_IDS = ("fork", "double_attack")
NEEDS_ENGINE = True
MOVE_BASED = True

FORK_PLIES = 4


def _targets(board: chess.Board, attacker_sq: chess.Square, us: chess.Color) -> list[chess.Square]:
    return [t for t in board.attacks(attacker_sq) if valuable_target(board, t, us)]


def _target_names(board: chess.Board, targets: list[chess.Square]) -> str:
    order = sorted(targets, key=lambda t: -[chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK,
                                            chess.QUEEN, chess.KING].index(board.piece_type_at(t)))
    return join_names([PIECE_NAME[board.piece_type_at(t)] for t in order])


def engine_confirms(board: chess.Board, ctx: DetectorContext, us: chess.Color) -> bool:
    """Best line from `board` (opponent to move) mates for us within 4 plies or wins material."""
    if ctx.engine is not None and ctx.engine.lines:
        line = ctx.engine.lines[0]
        if line.mate is not None and (line.mate > 0) == (us == chess.WHITE) and abs(line.mate) <= 2:
            return True
    if board.is_checkmate():
        return board.turn != us
    return pv_material_gain(board, ctx.pv, us, FORK_PLIES) >= 1


def detect(board: chess.Board, ctx: DetectorContext) -> list[Feature]:
    m, before = ctx.move, ctx.board_before
    if m is None or before is None:
        return []
    us = before.turn
    piece = board.piece_at(m.to_square)
    if piece is None or piece.color != us:
        return []
    out = []
    own = _targets(board, m.to_square, us)

    # Targets newly hit by our sliders whose line ran through the vacated square.
    disc = []
    for s in board.pieces(chess.BISHOP, us) | board.pieces(chess.ROOK, us) | board.pieces(chess.QUEEN, us):
        if s == m.to_square:
            continue
        for t in board.attacks(s) & ~before.attacks(s):
            if chess.BB_SQUARES[m.from_square] & chess.between(s, t) and valuable_target(board, t, us):
                disc.append(t)
    combined = sorted(set(own) | set(disc))

    data = {"piece": PIECE_NAME[piece.piece_type], "targets": [sq(t) for t in own]}
    if len(own) >= 2:
        data["target_names"] = _target_names(board, own)
        if engine_confirms(board, ctx, us):
            out.append(Feature(id="fork", side=cname(us), squares=[sq(m.to_square)] + [sq(t) for t in own],
                               pieces=[sq(m.to_square)], data=dict(data)))
    if len(own) >= 2 or (own and disc and len(combined) >= 2):
        out.append(Feature(
            id="double_attack", side=cname(us), squares=[sq(m.to_square)] + [sq(t) for t in combined],
            pieces=[sq(m.to_square)],
            data={**data, "targets": [sq(t) for t in combined],
                  "target_names": _target_names(board, combined), "pair": len(own) < 2},
        ))
    return out
