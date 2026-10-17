// Run: (cd web && npm test)
import { test } from "node:test";
import assert from "node:assert/strict";
import { plural, moveNumber, numberedLine, plyFacts, graphPoints, plyAtX, moments, cacheKey } from "./review.mjs";

// Shape of WebApp.review() output (tests/test_web_bridge.py::test_webapp_review), fool's mate.
const review = {
  depth: 14, engine: "Stockfish 19 lite (wasm)", band: "B2", wp_white_start: 0.52,
  plies: [
    { ply: 0, move: "f2f3", san: "f3", mover: "white", move_class: "inaccuracy", loss: 0.06, wp_before: 0.52,
      wp_after: 0.46, wp_white_after: 0.46, best_move: "e2e4", best_san: "e4", best_line_san: ["e4", "e5"] },
    { ply: 1, move: "e7e5", san: "e5", mover: "black", move_class: "best", loss: 0, wp_before: 0.54,
      wp_after: 0.54, wp_white_after: 0.46, best_move: "e7e5", best_san: "e5", best_line_san: ["e5"] },
    { ply: 2, move: "g2g4", san: "g4", mover: "white", move_class: "blunder", loss: 0.45, wp_before: 0.45,
      wp_after: 0, wp_white_after: 0, best_move: "b1c3", best_san: "Nc3", best_line_san: ["Nc3", "Nc6", "e4"] },
    { ply: 3, move: "d8h4", san: "Qh4#", mover: "black", move_class: "best", loss: 0, wp_before: 1,
      wp_after: 1, wp_white_after: 0, best_move: "d8h4", best_san: "Qh4#", best_line_san: ["Qh4#"] },
  ],
  sides: {
    white: { accuracy: 30, phase_accuracy: {}, counts: { inaccuracy: 1, mistake: 0, blunder: 1 },
             moments: [{ ply: 2, move_class: "blunder", summary: "", concept_id: null, unpunished: false }] },
    black: { accuracy: 100, phase_accuracy: {}, counts: { inaccuracy: 0, mistake: 0, blunder: 0 }, moments: [] },
  },
};

test("move numbers and numbered lines", () => {
  assert.equal(moveNumber(0), "1.");
  assert.equal(moveNumber(3), "2...");
  assert.equal(numberedLine(["Nc3", "Nc6", "e4"], 2), "2. Nc3 Nc6 3. e4");
  assert.equal(numberedLine(["Qxd5", "Nc3", "Qa5"], 9), "5... Qxd5 6. Nc3 Qa5");
});

test("ply facts: bad move shows the engine's best line; best move shows none", () => {
  const f = plyFacts(review, 2);
  assert.equal(f.label, "2. g4??");
  assert.equal(f.chances, "45% → 0%");
  assert.deepEqual(f.best, { san: "Nc3", line: "2. Nc3 Nc6 3. e4" });
  assert.equal(plyFacts(review, 3).best, null);
  assert.equal(plyFacts(review, 3).label, "2... Qh4#");
});

test("graph points: start plus one per ply, White on top", () => {
  const pts = graphPoints(review, 400, 100);
  assert.equal(pts.length, 5);
  assert.deepEqual(pts[0], [0, 48]);
  assert.deepEqual(pts[4], [400, 100]);
  assert.equal(plyAtX(review, 0, 400), 0);
  assert.equal(plyAtX(review, 260, 400), 3);
  assert.equal(plyAtX(review, 999, 400), 4);
});

test("moments from both sides in game order; cache key separates the draft preview", () => {
  assert.deepEqual(moments(review).map((m) => [m.ply, m.color]), [[2, "white"]]);
  assert.notEqual(cacheKey("automerge:x", true), cacheKey("automerge:x", false));
});

test("plural", () => {
  assert.equal(plural(1, "inaccuracy"), "1 inaccuracy");
  assert.equal(plural(0, "inaccuracy"), "0 inaccuracies");
  assert.equal(plural(2, "blunder"), "2 blunders");
});
