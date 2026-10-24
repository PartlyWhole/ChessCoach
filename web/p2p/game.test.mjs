// Run: (cd web && npm test)
import { test } from "node:test";
import assert from "node:assert/strict";
import { newGameDoc, derive, claimSeat, playMove, offerDraw, acceptDraw, resign, rematchDoc, pgn,
  requestTakeback, acceptTakeback, cancelTakeback, takebackPlies } from "./game.mjs";

const seated = () => newGameDoc({ white: "A", black: "B", names: { A: "Ann", B: "Bo" }, now: 0 });
const play = (d, ...ucis) => ucis.forEach((u, i) => assert.ok(playMove(d, i % 2 ? "B" : "A", u), u));

test("seats: first claim wins, one seat per player", () => {
  const d = newGameDoc();
  assert.ok(claimSeat(d, "A", "white", "Ann"));
  assert.ok(!claimSeat(d, "A", "black"));
  assert.ok(!claimSeat(d, "B", "white"));
  assert.ok(claimSeat(d, "B", "black"));
  assert.equal(d.names.A, "Ann");
});

test("only the side to move can move, and only legally", () => {
  const d = seated();
  assert.ok(!playMove(d, "B", "e7e5"));
  assert.ok(!playMove(d, "A", "e2e5"));
  assert.ok(!playMove(d, "C", "e2e4"));
  assert.ok(playMove(d, "A", "e2e4"));
  assert.deepEqual(derive(d).moves.map((m) => m.san), ["e4"]);
});

test("replay skips foreign, duplicate and illegal entries (concurrent merges)", () => {
  const d = seated();
  d.moves.push({ uci: "e2e4", by: "A" }, { uci: "e2e4", by: "A" }, { uci: "d7d5", by: "C" },
               { uci: "e7e9", by: "B" }, { uci: "e7e5", by: "B" });
  const g = derive(d);
  assert.deepEqual(g.moves.map((m) => m.uci), ["e2e4", "e7e5"]);
  assert.equal(g.turn, "white");
  assert.equal(g.fens.length, 3);
  assert.equal(g.fens[1], "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1");
  assert.equal(g.fens[2], g.fen);
});

test("a move by a player who lost a concurrent seat claim is skipped", () => {
  const d = seated();
  d.moves.push({ uci: "e2e4", by: "A" }, { uci: "c7c5", by: "X" }, { uci: "e7e5", by: "B" });
  assert.deepEqual(derive(d).moves.map((m) => m.san), ["e4", "e5"]);
});

test("checkmate ends the game and stops further moves", () => {
  const d = seated();
  play(d, "f2f3", "e7e5", "g2g4", "d8h4");
  const g = derive(d);
  assert.deepEqual(g.result, { score: "0-1", reason: "checkmate" });
  assert.deepEqual(g.legal, []);
  assert.ok(!playMove(d, "A", "a2a3"));
});

test("promotion needs the piece letter", () => {
  const d = newGameDoc({ white: "A", black: "B" });
  play(d, "h2h4", "g7g5", "h4g5", "h7h6", "g5h6", "g8f6", "h6h7", "f6g8");
  assert.ok(!playMove(d, "A", "h7g8"));
  assert.ok(playMove(d, "A", "h7g8q"));
  assert.equal(derive(d).moves.at(-1).san, "hxg8=Q");
});

test("resignation ends the game at its ply; a racing move does not count", () => {
  const d = seated();
  play(d, "e2e4");
  assert.ok(resign(d, "B"));
  d.moves.push({ uci: "e7e5", by: "B" });
  const g = derive(d);
  assert.equal(g.ply, 1);
  assert.deepEqual(g.result, { score: "1-0", reason: "black resigned" });
});

test("cannot resign before an opponent sits down", () => {
  const d = newGameDoc({ white: "A" });
  assert.ok(!resign(d, "A"));
});

test("draw offers: opponent accepts; the offer lapses after a move", () => {
  const d = seated();
  assert.ok(offerDraw(d, "A"));
  assert.ok(!acceptDraw(d, "A"));
  assert.equal(derive(d).drawOffer, "white");
  play(d, "e2e4");
  assert.equal(derive(d).drawOffer, null);
  assert.ok(!acceptDraw(d, "B"));
  assert.ok(offerDraw(d, "B"));
  assert.ok(acceptDraw(d, "A"));
  assert.deepEqual(derive(d).result, { score: "½-½", reason: "draw agreed" });
});

test("an end record by a non-player is ignored", () => {
  const d = seated();
  d.end = { kind: "resign", by: "C", ply: 0 };
  assert.equal(derive(d).result, null);
});

test("rematch swaps colours and keeps names", () => {
  const r = rematchDoc(seated());
  assert.equal(r.white, "B");
  assert.equal(r.black, "A");
  assert.equal(r.names.A, "Ann");
});

test("pgn", () => {
  const d = seated();
  play(d, "f2f3", "e7e5", "g2g4", "d8h4");
  assert.equal(pgn(d), '[Event "Peer-to-peer game"]\n[Date "1970.01.01"]\n[White "Ann"]\n[Black "Bo"]\n' +
    '[Result "0-1"]\n\n1. f3 e5 2. g4 Qh4# 0-1\n');
});

const sans = (d) => derive(d).moves.map((m) => m.san);
const clone = (d) => structuredClone(d);

test("takeback plies: own last move, plus the reply if one was made", () => {
  assert.equal(takebackPlies(0, "white"), 0);
  assert.equal(takebackPlies(1, "white"), 1);
  assert.equal(takebackPlies(1, "black"), 0);
  assert.equal(takebackPlies(2, "white"), 2);
  assert.equal(takebackPlies(2, "black"), 1);
});

test("takeback of the mover's last move", () => {
  const d = seated();
  play(d, "e2e4");
  assert.ok(!requestTakeback(d, "B"));                 // black has nothing to take back
  assert.ok(requestTakeback(d, "A"));
  assert.equal(derive(d).takeback, "white");
  assert.ok(!acceptTakeback(d, "A"));                  // not your own request
  assert.ok(acceptTakeback(d, "B"));
  const g = derive(d);
  assert.deepEqual(g.moves, []);
  assert.equal(g.turn, "white");
  assert.equal(g.takeback, null);
  assert.equal(g.fens.length, 1);
  assert.ok(playMove(d, "A", "d2d4"));
  assert.deepEqual(sans(d), ["d4"]);
});

test("takeback after the opponent replied removes two plies", () => {
  const d = seated();
  play(d, "e2e4", "e7e5");
  assert.ok(requestTakeback(d, "A"));
  assert.ok(acceptTakeback(d, "B"));
  assert.deepEqual(sans(d), []);
  assert.equal(derive(d).turn, "white");
});

test("a request lapses when a move is made instead; decline and withdraw clear it", () => {
  const d = seated();
  play(d, "e2e4");
  assert.ok(requestTakeback(d, "A"));
  assert.ok(playMove(d, "B", "e7e5"));
  assert.equal(derive(d).takeback, null);
  assert.ok(!acceptTakeback(d, "B"));
  assert.ok(requestTakeback(d, "B"));
  assert.ok(cancelTakeback(d, "A"));                   // declined
  assert.equal(derive(d).takeback, null);
  assert.ok(requestTakeback(d, "B"));
  assert.ok(cancelTakeback(d, "B"));                   // withdrawn
  assert.deepEqual(sans(d), ["e4", "e5"]);
});

test("accept racing the requester's own move: either merge order gives one consistent game", () => {
  const base = seated();
  play(base, "e2e4", "e7e5");
  assert.ok(requestTakeback(base, "A"));               // would undo 2 plies
  const accepted = clone(base), moved = clone(base);
  assert.ok(acceptTakeback(accepted, "B"));
  assert.ok(playMove(moved, "A", "g1f3"));
  const undo = accepted.moves.at(-1), move = moved.moves.at(-1);
  const undoFirst = clone(base); undoFirst.moves.push(undo, move);
  const moveFirst = clone(base); moveFirst.moves.push(move, undo);
  assert.deepEqual(sans(undoFirst), []);               // the Nf3 was for a position that no longer exists
  assert.deepEqual(sans(moveFirst), ["e4", "e5", "Nf3"]); // the undo was for ply 2; we are at ply 3
});

test("undo entries that are self-written or for the wrong ply count are ignored", () => {
  const d = seated();
  play(d, "e2e4", "e7e5");
  d.moves.push({ undo: 2, by: "A", req: "A", ply: 2 });
  d.moves.push({ undo: 1, by: "B", req: "A", ply: 2 });  // white needs 2 here
  assert.deepEqual(sans(d), ["e4", "e5"]);
});

test("game end after a takeback stops at the right point in the log", () => {
  const d = seated();
  play(d, "e2e4", "e7e5");
  assert.ok(requestTakeback(d, "A"));
  assert.ok(acceptTakeback(d, "B"));
  play(d, "d2d4", "d7d5");                              // back to ply 2, as before the takeback
  assert.ok(resign(d, "A"));
  d.moves.push({ uci: "c2c4", by: "A", ply: 2 });
  const g = derive(d);
  assert.deepEqual(g.moves.map((m) => m.san), ["d4", "d5"]);
  assert.deepEqual(g.result, { score: "0-1", reason: "white resigned" });
  assert.ok(!requestTakeback(d, "A"));
});

test("documents from before takebacks (moves without ply, end with ply) still replay", () => {
  const d = seated();
  d.moves.push({ uci: "e2e4", by: "A" }, { uci: "e7e5", by: "B" });
  d.drawOffer = { by: "A", ply: 2 };
  assert.equal(derive(d).drawOffer, "white");
  d.end = { kind: "resign", by: "B", ply: 1 };
  assert.deepEqual(derive(d).moves.map((m) => m.san), ["e4"]);
});
