// Pure game logic for the peer-to-peer page (ADR 0003). No DOM, no network: tested in game.test.mjs.
//
// The Automerge document is an append-only record. Every peer derives the game from it the same
// way, so concurrent edits converge on one game:
//
//   { v: 1, createdAt, white: playerId|null, black: playerId|null, names: { [playerId]: name },
//     moves: [{ uci, by }], drawOffer: { by, ply }|null,
//     end: { kind: "resign"|"draw", by, ply }|null, rematch: automergeUrl|null }
//
// A move counts only if its author holds the seat of the side to move and it is legal; any other
// entry (a concurrent duplicate, a move by someone who lost a concurrent seat claim) is skipped.
// "end" stops the replay at its ply, so a move racing a resignation never counts.
import { Chess } from "chess.js";

export function newGameDoc({ white = null, black = null, names = {}, now = Date.now() } = {}) {
  return { v: 1, createdAt: now, white, black, names: { ...names }, moves: [], drawOffer: null, end: null, rematch: null };
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
  const end = doc.end && (doc.end.by === doc.white || doc.end.by === doc.black) ? doc.end : null;
  const stopAt = end ? end.ply : Infinity;
  for (const m of doc.moves || []) {
    if (accepted.length >= stopAt || chess.isGameOver()) break;
    const color = chess.turn() === "w" ? "white" : "black";
    if (!m || m.by !== doc[color]) continue;
    let mv;
    try { mv = chess.move(toMove(m.uci)); } catch { continue; }
    accepted.push({ uci: m.uci, san: mv.san, by: m.by });
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
  const offer = doc.drawOffer;
  const drawOffer = !result && offer && offer.ply === ply && seatOf(doc, offer.by) ? seatOf(doc, offer.by) : null;
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
  };
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
  d.moves.push({ uci, by: playerId });
  return true;
}

export function offerDraw(d, playerId) {
  const g = derive(d);
  if (g.result || !seatOf(d, playerId) || g.drawOffer) return false;
  d.drawOffer = { by: playerId, ply: g.ply };
  return true;
}

export function acceptDraw(d, playerId) {
  const g = derive(d);
  const me = seatOf(d, playerId);
  if (g.result || !me || g.drawOffer !== otherColor(me)) return false;
  d.end = { kind: "draw", by: playerId, ply: g.ply };
  return true;
}

export function resign(d, playerId) {
  const g = derive(d);
  if (g.result || !seatOf(d, playerId) || !d.white || !d.black) return false;
  d.end = { kind: "resign", by: playerId, ply: g.ply };
  return true;
}

// Rematch: the same two players with colours swapped.
export function rematchDoc(d) {
  return newGameDoc({ white: d.black, black: d.white, names: d.names });
}

export function pgn(doc, g = derive(doc)) {
  const name = (c) => ((doc[c] && doc.names[doc[c]]) || c).replace(/["\\]/g, "");
  const date = new Date(doc.createdAt).toISOString().slice(0, 10).replace(/-/g, ".");
  const score = g.result ? g.result.score.replace("½-½", "1/2-1/2") : "*";
  let body = "";
  g.moves.forEach((m, i) => { body += (i % 2 ? "" : `${i / 2 + 1}. `) + m.san + " "; });
  return `[Event "Peer-to-peer game"]\n[Date "${date}"]\n[White "${name("white")}"]\n[Black "${name("black")}"]\n` +
    `[Result "${score}"]\n\n${body}${score}\n`;
}
