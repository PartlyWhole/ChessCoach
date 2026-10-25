// Pure game logic for the peer-to-peer page (ADR 0003). No DOM, no network: tested in game.test.mjs.
//
// The Automerge document is an append-only record. Every peer derives the game from it the same
// way, so concurrent edits converge on one game:
//
//   { v: 1, createdAt, white: playerId|null, black: playerId|null, names: { [playerId]: name },
//     moves: [{ uci, by, ply } | { undo: 1|2, by, req, ply }],
//     drawOffer: { by, n }|null, takeback: { by, n }|null,
//     end: { kind: "resign"|"draw", by, n }|null, rematch: automergeUrl|null }
//
// "moves" is an event log. A move counts only if its author holds the seat of the side to move, it
// is legal, and its ply matches the current ply; any other entry (a concurrent duplicate, a move by
// someone who lost a concurrent seat claim, a move made for a position a takeback removed) is
// skipped. An undo entry is an accepted takeback: written by one player for the other's request,
// it removes that player's last move (1 ply, or 2 if the acceptor has already replied).
// Records with "n" refer to the log length when they were made: "end" stops the replay there, so a
// move racing a resignation never counts, and an offer or request lapses once the log grows.
// Documents from before takebacks have plies instead of n (end.ply, drawOffer.ply); both work.
import { Chess } from "chess.js";

export function newGameDoc({ white = null, black = null, names = {}, now = Date.now() } = {}) {
  return { v: 1, createdAt: now, white, black, names: { ...names }, moves: [], drawOffer: null, takeback: null,
           end: null, rematch: null };
}

export function seatOf(doc, playerId) {
  if (doc.white === playerId) return "white";
  if (doc.black === playerId) return "black";
  return null;
}

export const otherColor = (color) => (color === "white" ? "black" : "white");

function toMove(uci) {
  return { from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci.length > 4 ? uci[4] : undefined };
}

export function derive(doc) {
  const chess = new Chess();
  const accepted = [];
  const fens = [chess.fen()];
  const log = doc.moves || [];
  const end = doc.end && (doc.end.by === doc.white || doc.end.by === doc.black) ? doc.end : null;
  const stopAtEntry = end && end.n != null ? end.n : Infinity;
  const stopAtPly = end && end.n == null ? end.ply : Infinity;
  for (let i = 0; i < log.length && i < stopAtEntry; i++) {
    if (accepted.length >= stopAtPly || chess.isGameOver()) break;
    const m = log[i];
    if (!m || (m.ply != null && m.ply !== accepted.length)) continue;
    if (m.undo != null) {
      const req = seatOf(doc, m.req);
      if (!req || seatOf(doc, m.by) !== otherColor(req) || m.undo !== takebackPlies(accepted.length, req)) continue;
      for (let k = 0; k < m.undo; k++) { chess.undo(); accepted.pop(); fens.pop(); }
      continue;
    }
    const color = chess.turn() === "w" ? "white" : "black";
    if (m.by !== doc[color]) continue;
    let mv;
    try { mv = chess.move(toMove(m.uci)); } catch { continue; }
    accepted.push({ uci: m.uci, san: mv.san, by: m.by, captured: mv.captured || null });
    fens.push(chess.fen());
  }
  const turn = chess.turn() === "w" ? "white" : "black";
  const ply = accepted.length;
  let result = null;
  if (chess.isCheckmate()) result = { score: turn === "white" ? "0-1" : "1-0", reason: "checkmate" };
  else if (chess.isStalemate()) result = { score: "½-½", reason: "stalemate" };
  else if (chess.isInsufficientMaterial()) result = { score: "½-½", reason: "insufficient material" };
  else if (chess.isThreefoldRepetition()) result = { score: "½-½", reason: "threefold repetition" };
  else if (chess.isDrawByFiftyMoves()) result = { score: "½-½", reason: "fifty-move rule" };
  else if (end && end.kind === "resign") {
    result = { score: end.by === doc.white ? "0-1" : "1-0", reason: `${seatOf(doc, end.by)} resigned` };
  } else if (end && end.kind === "draw") result = { score: "½-½", reason: "draw agreed" };
  const fresh = (rec) => rec && (rec.n != null ? rec.n === log.length : rec.ply === ply) && seatOf(doc, rec.by);
  const drawOffer = !result && fresh(doc.drawOffer) ? seatOf(doc, doc.drawOffer.by) : null;
  const tb = !result && fresh(doc.takeback) ? seatOf(doc, doc.takeback.by) : null;
  const takeback = tb && takebackPlies(ply, tb) ? tb : null;
  return {
    fen: chess.fen(),
    fens,               // fens[i] = position after i accepted plies
    turn,
    ply,
    moves: accepted,
    lastMove: ply ? accepted[ply - 1].uci : null,
    inCheck: chess.inCheck(),
    legal: result ? [] : chess.moves({ verbose: true }).map((m) => m.from + m.to + (m.promotion || "")),
    result,
    drawOffer,
    takeback,           // colour with a pending takeback request
  };
}

// Plies a takeback by `color` removes at `ply`: its own last move, plus the reply if there is one.
// 0 when it has no move to take back.
export function takebackPlies(ply, color) {
  const moverOf = (i) => (i % 2 === 0 ? "white" : "black");
  if (ply >= 1 && moverOf(ply - 1) === color) return 1;
  if (ply >= 2) return 2;
  return 0;
}

// --- Mutations. Each takes the Automerge draft (or a plain object in tests) and returns whether it
// changed anything; callers pass them to handle.change(). They refuse what derive() would ignore.

export function claimSeat(d, playerId, color, name) {
  if (seatOf(d, playerId) || d[color]) return false;
  d[color] = playerId;
  if (name) d.names[playerId] = name;
  return true;
}

export function playMove(d, playerId, uci) {
  const g = derive(d);
  if (g.result || d[g.turn] !== playerId || !g.legal.includes(uci)) return false;
  d.moves.push({ uci, by: playerId, ply: g.ply });
  return true;
}

export function offerDraw(d, playerId) {
  const g = derive(d);
  if (g.result || !seatOf(d, playerId) || g.drawOffer) return false;
  d.drawOffer = { by: playerId, n: d.moves.length };
  return true;
}

export function acceptDraw(d, playerId) {
  const g = derive(d);
  const me = seatOf(d, playerId);
  if (g.result || !me || g.drawOffer !== otherColor(me)) return false;
  d.end = { kind: "draw", by: playerId, n: d.moves.length };
  return true;
}

export function resign(d, playerId) {
  const g = derive(d);
  if (g.result || !seatOf(d, playerId) || !d.white || !d.black) return false;
  d.end = { kind: "resign", by: playerId, n: d.moves.length };
  return true;
}

export function requestTakeback(d, playerId) {
  const g = derive(d);
  const me = seatOf(d, playerId);
  if (g.result || !me || !d.white || !d.black || g.takeback || !takebackPlies(g.ply, me)) return false;
  d.takeback = { by: playerId, n: d.moves.length };
  return true;
}

export function acceptTakeback(d, playerId) {
  const g = derive(d);
  const me = seatOf(d, playerId);
  if (!me || g.takeback !== otherColor(me)) return false;
  d.moves.push({ undo: takebackPlies(g.ply, g.takeback), by: playerId, req: d.takeback.by, ply: g.ply });
  d.takeback = null;
  return true;
}

// Either player: the opponent declines, or the requester withdraws.
export function cancelTakeback(d, playerId) {
  const g = derive(d);
  if (!g.takeback || !seatOf(d, playerId)) return false;
  d.takeback = null;
  return true;
}

// Rematch: the same two players with colours swapped.
export function rematchDoc(d) {
  return newGameDoc({ white: d.black, black: d.white, names: d.names });
}

// Captured pieces and material balance moved to ../shared/replay.mjs (used by the coach page too).
export { PIECE_VALUE, captures, materialBalance } from "../shared/replay.mjs";

export function pgn(doc, g = derive(doc)) {
  const name = (c) => ((doc[c] && doc.names[doc[c]]) || c).replace(/["\\]/g, "");
  const date = new Date(doc.createdAt).toISOString().slice(0, 10).replace(/-/g, ".");
  const score = g.result ? g.result.score.replace("½-½", "1/2-1/2") : "*";
  let body = "";
  g.moves.forEach((m, i) => { body += (i % 2 ? "" : `${i / 2 + 1}. `) + m.san + " "; });
  return `[Event "Peer-to-peer game"]\n[Date "${date}"]\n[White "${name("white")}"]\n[Black "${name("black")}"]\n` +
    `[Result "${score}"]\n\n${body}${score}\n`;
}
