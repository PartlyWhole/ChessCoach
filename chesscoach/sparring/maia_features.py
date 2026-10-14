"""Maia-2 input/output handling without PyTorch, for running the exported ONNX model (browser,
or onnxruntime). Mirrors maia2.utils / maia2.inference exactly; tests/test_maia_features.py
checks it against the maia2 package.

Maia-2 always sees the position from White's side: Black-to-move boards are mirrored, and the
predicted moves are mirrored back.
"""
from __future__ import annotations

import math
from functools import lru_cache

import chess

ELO_START, ELO_END, ELO_STEP = 1100, 2000, 100
PLANES = 18           # 12 piece planes + side to move + 4 castling + en passant


@lru_cache(maxsize=1)
def all_moves() -> tuple[str, ...]:
    """The 1880-move vocabulary (maia2.utils.get_all_possible_moves)."""
    moves: list[str] = []
    for rank in range(8):
        for file in range(8):
            sq = chess.square(file, rank)
            for pt in (chess.QUEEN, chess.KNIGHT):
                b = chess.Board(None)
                b.set_piece_at(sq, chess.Piece(pt, chess.WHITE))
                moves.extend(m.uci() for m in b.legal_moves)
    for f in "abcdefgh":
        for target in [f] + ([chr(ord(f) - 1)] if f != "a" else []) + ([chr(ord(f) + 1)] if f != "h" else []):
            for piece in "qrbn":
                moves.append(f"{f}7{target}8{piece}")
    return tuple(moves)


@lru_cache(maxsize=1)
def move_index() -> dict[str, int]:
    return {m: i for i, m in enumerate(all_moves())}


def elo_category(elo: int) -> int:
    """maia2.utils.map_to_category with create_elo_dict(): <1100 → 0, 1100–1199 → 1, … >=2000 → 10."""
    if elo < ELO_START:
        return 0
    if elo >= ELO_END:
        return (ELO_END - ELO_START) // ELO_STEP + 1
    return (elo - ELO_START) // ELO_STEP + 1


def oriented(board: chess.Board) -> tuple[chess.Board, bool]:
    """(board as Maia sees it, mirrored?)"""
    return (board.mirror(), True) if board.turn == chess.BLACK else (board, False)


def planes(board: chess.Board) -> list[float]:
    """maia2.utils.board_to_tensor flattened (18 × 8 × 8, channel-major, row = rank)."""
    out = [0.0] * (PLANES * 64)
    for i, pt in enumerate((chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN, chess.KING)):
        for color, off in ((chess.WHITE, 0), (chess.BLACK, 6)):
            for sq in board.pieces(pt, color):
                out[(i + off) * 64 + sq] = 1.0
    if board.turn == chess.WHITE:
        for s in range(64):
            out[12 * 64 + s] = 1.0
    rights = (board.has_kingside_castling_rights(chess.WHITE), board.has_queenside_castling_rights(chess.WHITE),
              board.has_kingside_castling_rights(chess.BLACK), board.has_queenside_castling_rights(chess.BLACK))
    for k, has in enumerate(rights):
        if has:
            for s in range(64):
                out[(13 + k) * 64 + s] = 1.0
    if board.ep_square is not None:
        out[17 * 64 + board.ep_square] = 1.0
    return out


def mirror_uci(uci: str) -> str:
    return uci[0] + str(9 - int(uci[1])) + uci[2] + str(9 - int(uci[3])) + uci[4:]


def prepare(board: chess.Board) -> tuple[list[float], list[int], list[str], bool]:
    """(planes, legal move indices, legal moves as Maia sees them, mirrored?)"""
    b, mirrored = oriented(board)
    idx = move_index()
    legal = [m.uci() for m in b.legal_moves]
    return planes(b), [idx[m] for m in legal], legal, mirrored


def probs_from_logits(legal_logits: list[float], legal: list[str], mirrored: bool) -> dict[str, float]:
    """Masked softmax over the legal moves, mapped back to the real board's UCI."""
    if not legal_logits:
        return {}
    top = max(legal_logits)
    exps = [math.exp(x - top) for x in legal_logits]
    z = sum(exps)
    return {(mirror_uci(m) if mirrored else m): e / z for m, e in zip(legal, exps)}
