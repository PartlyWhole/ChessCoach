"""King-safety detectors (02 §6.2).

king_safety_shield: king on its back rank on files a–c or f–h (castled position); counts the
three shield files (king file ±1) whose pawn is missing from the 2nd and 3rd ranks (data.missing)
or stands on the 3rd rank (data.advanced). Emitted when either is > 0. side = owner.

king_attackers: number of enemy pieces (not pawns/king) attacking squares adjacent to the
king. Emitted when >= 1. side = the attacking side; data.owner = the king's side.

king_in_center: opening/middlegame, king on the d or e file, and (it has lost castling
rights or fullmove >= 10), and the d- or e-file has no pawn of the king's side. side = owner.
"""
from __future__ import annotations

import chess

from chesscoach.analysis.board_utils import PIECE_NAME, cname, sq
from chesscoach.analysis.detectors.base import DetectorContext
from chesscoach.types import Feature

FEATURE_IDS = ("king_safety_shield", "king_attackers", "king_in_center")
NEEDS_ENGINE = False
MOVE_BASED = False


def detect(board: chess.Board, ctx: DetectorContext) -> list[Feature]:
    out = []
    for color in (chess.WHITE, chess.BLACK):
        k = board.king(color)
        if k is None:
            continue
        kf, kr = chess.square_file(k), chess.square_rank(k)
        back = 0 if color == chess.WHITE else 7
        r2, r3 = (1, 2) if color == chess.WHITE else (6, 5)
        own = board.pieces(chess.PAWN, color)

        if kr == back and kf in (0, 1, 2, 5, 6, 7):
            missing, advanced = [], []
            for f in range(max(0, kf - 1), min(7, kf + 1) + 1):
                if chess.square(f, r2) in own:
                    continue
                if chess.square(f, r3) in own:
                    advanced.append(chess.FILE_NAMES[f])
                else:
                    missing.append(chess.FILE_NAMES[f])
            if missing or advanced:
                out.append(Feature(id="king_safety_shield", side=cname(color), squares=[sq(k)],
                                   data={"missing": len(missing), "advanced": len(advanced),
                                         "missing_files": missing, "advanced_files": advanced}))

        zone = chess.SquareSet(chess.BB_KING_ATTACKS[k])
        attackers = set()
        for z in zone:
            for a in board.attackers(not color, z):
                if board.piece_type_at(a) not in (chess.PAWN, chess.KING):
                    attackers.add(a)
        if attackers:
            out.append(Feature(id="king_attackers", side=cname(not color), squares=[sq(k)],
                               pieces=sorted(sq(a) for a in attackers),
                               data={"count": len(attackers), "owner": cname(color),
                                     "pieces": [PIECE_NAME[board.piece_type_at(a)] for a in sorted(attackers)]}))

        if ctx.phase in ("opening", "middlegame") and kf in (3, 4):
            can_castle = board.has_castling_rights(color)
            if not can_castle or board.fullmove_number >= 10:
                open_files = [chess.FILE_NAMES[f] for f in (3, 4) if not own & chess.SquareSet(chess.BB_FILES[f])]
                if open_files:
                    out.append(Feature(id="king_in_center", side=cname(color), squares=[sq(k)],
                                       data={"files": open_files, "can_castle": can_castle}))
    return out
