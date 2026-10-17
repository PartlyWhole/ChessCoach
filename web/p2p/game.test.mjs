// Run: (cd web && npm test)
import { test } from "node:test";
import assert from "node:assert/strict";
import { newGameDoc, derive, claimSeat, playMove, offerDraw, acceptDraw, resign, rematchDoc, pgn } from "./game.mjs";

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
