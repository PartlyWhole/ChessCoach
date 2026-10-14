"""Pawn-structure classifier (02 §6.3), reimplemented from the idea of per-file encoding plus
similarity scoring (not copied from LiChess Tools).

Encoding: for each side, one char per file a..h — 'X' no pawn, '0' unmoved (2nd rank from
that side), '1'..'5' ranks advanced. With several pawns on a file the most advanced counts.

Each named structure lists required cells as {(side, file): allowed_chars}; 'owner' is the side
the template is written for and the template is also tried colour-reversed. Score = share of
required cells matched. Best score ≥ threshold wins; ties go to the template with more cells
(more specific), then to table order. `open_center` / `closed_center` are generic fallbacks
used only when no named structure matches.
"""
from __future__ import annotations

from typing import Optional

import chess

from chesscoach import config

FILES = "abcdefgh"


def encode(board: chess.Board, color: chess.Color) -> str:
    out = []
    for f in range(8):
        best = None
        for p in board.pieces(chess.PAWN, color):
            if chess.square_file(p) != f:
                continue
            adv = chess.square_rank(p) - 1 if color == chess.WHITE else 6 - chess.square_rank(p)
            best = adv if best is None else max(best, adv)
        out.append("X" if best is None else str(best))
    return "".join(out)


# (O = owner, T = the other side). Cells: "O:d" -> allowed chars.
STRUCTURES: dict[str, dict[str, str]] = {
    "iqp":                  {"O:c": "X", "O:d": "2", "O:e": "X", "T:d": "X"},
    "hanging_pawns":        {"O:b": "X", "O:c": "2", "O:d": "2", "O:e": "X", "T:c": "X", "T:d": "X"},
    "carlsbad":             {"O:c": "X", "O:d": "2", "O:e": "1", "T:c": "1", "T:d": "2", "T:e": "X"},
    # owner = the side with the c6-d5-e6 triangle; f-pawn not on f5 (that is a Stonewall)
    "slav_triangle":        {"O:c": "1", "O:d": "2", "O:e": "1", "O:f": "01X", "T:c": "2", "T:d": "2"},
    # owner = the side with the e5 spearhead; Black's c-pawn on c7, c5, c4 or gone
    "french_advance":       {"O:d": "2", "O:e": "3", "T:c": "023X", "T:d": "2", "T:e": "1"},
    "caro_kann_advance":    {"O:d": "2", "O:e": "3", "T:c": "1", "T:d": "2", "T:e": "01"},
    "kings_indian_closed":  {"O:c": "2", "O:d": "3", "O:e": "2", "T:d": "1", "T:e": "2"},
    "maroczy_bind":         {"O:c": "2", "O:d": "X", "O:e": "2", "T:c": "X", "T:d": "01"},
    "hedgehog":             {"O:c": "2", "O:d": "X", "O:e": "2", "T:b": "1", "T:c": "X", "T:d": "1", "T:e": "1"},
    "sicilian_scheveningen": {"O:c": "0", "O:d": "X", "O:e": "2", "T:c": "X", "T:d": "1", "T:e": "1"},
    "stonewall":            {"O:c": "1", "O:d": "2", "O:e": "1", "O:f": "2"},
}


def _score(cells: dict[str, str], enc: dict[str, str]) -> float:
    hit = sum(1 for key, allowed in cells.items()
              if enc[key[0]][FILES.index(key[2])] in allowed)
    return hit / len(cells)


def _generic(board: chess.Board) -> Optional[str]:
    centre = chess.BB_FILE_D | chess.BB_FILE_E
    pawns = (board.pieces_mask(chess.PAWN, chess.WHITE) | board.pieces_mask(chess.PAWN, chess.BLACK)) & centre
    if chess.popcount(pawns) <= 1:
        return "open_center"
    locked = 0
    for f in (3, 4):
        for wp in board.pieces(chess.PAWN, chess.WHITE):
            if chess.square_file(wp) == f and wp + 8 < 64 and board.piece_at(wp + 8) == chess.Piece(chess.PAWN, chess.BLACK):
                locked += 1
    return "closed_center" if locked >= 2 else None


def classify_structure(board: chess.Board, threshold: Optional[float] = None) -> tuple[Optional[str], Optional[str]]:
    """Returns (structure_id, owner colour name) — owner None for symmetric/generic ones."""
    threshold = config.get("structure.threshold") if threshold is None else threshold
    w, b = encode(board, chess.WHITE), encode(board, chess.BLACK)
    best = (0.0, 0, None, None)
    for order, (sid, cells) in enumerate(STRUCTURES.items()):
        for owner, enc in (("white", {"O": w, "T": b}), ("black", {"O": b, "T": w})):
            s = _score(cells, enc)
            cand = (s, len(cells), sid, owner)
            if s >= threshold and (s, len(cells)) > best[:2]:
                best = cand
    if best[2] is not None:
        return best[2], best[3]
    return _generic(board), None
