"""Pawn-structure detectors (02 §6.2): isolated_pawn (+isolated_queen_pawn), doubled_pawns,
backward_pawn, passed_pawn (+protected_passed, outside_passed), pawn_islands.

For all of these `side` is the pawns' owner (the feature *belongs to* that side).
"""
from __future__ import annotations

import chess

from chesscoach.analysis.board_utils import cname, sq
from chesscoach.analysis.detectors.base import DetectorContext
from chesscoach.types import Feature

FEATURE_IDS = ("isolated_pawn", "isolated_queen_pawn", "doubled_pawns", "backward_pawn",
               "passed_pawn", "protected_passed", "outside_passed", "pawn_islands")
NEEDS_ENGINE = False
MOVE_BASED = False


def _files(pawns) -> set[int]:
    return {chess.square_file(p) for p in pawns}


def _ahead(color: chess.Color, r_from: int, r: int) -> bool:
    return r > r_from if color == chess.WHITE else r < r_from


def is_passed(board: chess.Board, p: chess.Square, color: chess.Color) -> bool:
    f, r = chess.square_file(p), chess.square_rank(p)
    for e in board.pieces(chess.PAWN, not color):
        if abs(chess.square_file(e) - f) <= 1 and _ahead(color, r, chess.square_rank(e)):
            return False
    return True


def detect(board: chess.Board, ctx: DetectorContext) -> list[Feature]:
    out = []
    all_pawns = board.pieces(chess.PAWN, chess.WHITE) | board.pieces(chess.PAWN, chess.BLACK)
    for color in (chess.WHITE, chess.BLACK):
        side = cname(color)
        own = board.pieces(chess.PAWN, color)
        enemy = board.pieces(chess.PAWN, not color)
        files = _files(own)
        fwd = 1 if color == chess.WHITE else -1

        # islands
        islands, prev = 0, -2
        for f in sorted(files):
            if f != prev + 1:
                islands += 1
            prev = f
        if own:
            out.append(Feature(id="pawn_islands", side=side, squares=[], data={"count": islands}))

        for f in sorted(files):
            on_file = [p for p in own if chess.square_file(p) == f]
            if len(on_file) >= 2:
                out.append(Feature(id="doubled_pawns", side=side, squares=[sq(p) for p in on_file],
                                   data={"file": chess.FILE_NAMES[f], "count": len(on_file)}))

        for p in own:
            f, r = chess.square_file(p), chess.square_rank(p)
            neighbours = [q for q in own if abs(chess.square_file(q) - f) == 1]
            if not neighbours:
                out.append(Feature(id="isolated_pawn", side=side, squares=[sq(p)], data={"file": chess.FILE_NAMES[f]}))
                if f == 3:
                    out.append(Feature(id="isolated_queen_pawn", side=side, squares=[sq(p)], data={"file": "d"}))
            else:
                # backward: no adjacent friendly pawn level with or behind it; stop square hit by an enemy pawn.
                support = [q for q in neighbours if not _ahead(color, r, chess.square_rank(q))]
                stop_rank = r + fwd
                if not support and 0 <= stop_rank <= 7:
                    stop = chess.square(f, stop_rank)
                    if board.attackers(not color, stop) & enemy:
                        out.append(Feature(id="backward_pawn", side=side, squares=[sq(p)],
                                           data={"file": chess.FILE_NAMES[f], "stop": sq(stop)}))

            if is_passed(board, p, color):
                data = {"file": chess.FILE_NAMES[f], "rank": r + 1 if color == chess.WHITE else 8 - r}
                out.append(Feature(id="passed_pawn", side=side, squares=[sq(p)], data=data))
                if board.attackers(color, p) & own:
                    out.append(Feature(id="protected_passed", side=side, squares=[sq(p)], data=dict(data)))
                others = [chess.square_file(q) for q in all_pawns if q != p]
                enemy_files = [chess.square_file(e) for e in enemy]
                outermost = others and (all(o > f for o in others) or all(o < f for o in others))
                if outermost and enemy_files and min(abs(e - f) for e in enemy_files) >= 3:
                    out.append(Feature(id="outside_passed", side=side, squares=[sq(p)], data=dict(data)))
    return out
