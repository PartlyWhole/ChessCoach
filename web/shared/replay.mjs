// Helpers over a list of moves, shared by the p2p and coach pages.
import { Chess } from "chess.js";

// Pieces each side has taken in the first `ply` moves (lowercase piece letters, most valuable
// first), and the material balance on the board in pawns (positive = White ahead; counts
// promotions, which the captured lists alone would miss).
export const PIECE_VALUE = { q: 9, r: 5, b: 3, n: 3, p: 1 };

export function captures(moves, ply = moves.length) {
  const out = { white: [], black: [] };
  moves.slice(0, ply).forEach((m, i) => { if (m.captured) out[i % 2 ? "black" : "white"].push(m.captured); });
  const order = "qrbnp";
  for (const c of ["white", "black"]) out[c].sort((a, b) => order.indexOf(a) - order.indexOf(b));
  return out;
}

export function materialBalance(fen) {
  let bal = 0;
  for (const ch of fen.split(" ")[0]) {
    const v = PIECE_VALUE[ch.toLowerCase()];
    if (v) bal += ch === ch.toUpperCase() ? v : -v;
  }
  return bal;
}

// Replays UCI moves from a FEN: SAN and captured piece per move, and the FEN after each
// (fens[0] = start). Stops at the first illegal move.
export function replay(startFen, ucis) {
  const c = new Chess(startFen);
  const moves = [], fens = [c.fen()];
  for (const u of ucis) {
    let mv;
    try { mv = c.move({ from: u.slice(0, 2), to: u.slice(2, 4), promotion: u[4] }); } catch { break; }
    moves.push({ uci: u, san: mv.san, captured: mv.captured || null });
    fens.push(c.fen());
  }
  return { moves, fens };
}
