// Run: (cd web && npm test)
import { test } from "node:test";
import assert from "node:assert/strict";
import { featureLabels, lineRows, lineSummary, lineFens } from "./lines.mjs";

// Shape of chesscoach.analysis.lines.explain_line() output (asdict), fool's mate refutation.
const g4 = {
  perspective: "white", start_fen: "rnbqkbnr/pppp1ppp/8/4p3/8/5P2/PPPPP1PP/RNBQKBNR w KQkq - 0 2",
  steps: [
    { ply: 0, move: "g2g4", san: "g4", mover: "white", captured: null, promotion: null, check: false,
      mate: false, material: 0, feature_ids: [], squares: [] },
    { ply: 1, move: "d8h4", san: "Qh4#", mover: "black", captured: null, promotion: null, check: true,
      mate: true, material: 0, feature_ids: [], squares: [] },
  ],
  material_change: 0, outcome: "mate", decisive_ply: 1, mate_for: "black",
};

test("feature labels drop what a stronger label implies", () => {
  assert.deepEqual(featureLabels(["double_attack", "fork"]), ["Fork"]);
  assert.deepEqual(featureLabels(["discovered_attack", "discovered_check"]), ["Discovered check"]);
  assert.deepEqual(featureLabels(["pin_absolute", "pin_relative", "unknown_id"]), ["Pin"]);
});

test("rows: numbered from the game ply, badges from the step facts, decisive ply marked", () => {
  const rows = lineRows(g4, 2);
  assert.deepEqual(rows.map((r) => r.label), ["2. g4", "2... Qh4#"]);
  assert.deepEqual(rows[1].badges, [{ kind: "mate", text: "mate" }]);
  assert.deepEqual(rows.map((r) => r.decisive), [false, true]);
  const fork = { ...g4, decisive_ply: 2, steps: [
    { ply: 0, move: "d5c7", san: "Nc7+", mover: "white", captured: null, promotion: null, check: true, mate: false,
      material: 0, feature_ids: ["fork", "double_attack"], squares: ["c7", "e8", "a8"] }] };
  const r = lineRows(fork, 20)[0];
  assert.equal(r.label, "11. Nc7+");
  assert.deepEqual(r.badges.map((b) => b.text), ["Fork", "check"]);
  assert.deepEqual(r.squares, ["c7", "e8", "a8"]);
});

test("summary from the perspective side", () => {
  assert.equal(lineSummary(g4).text, "Ends in mate against you");
  assert.equal(lineSummary({ ...g4, mate_for: "white" }).text, "Ends in mate for you");
  assert.deepEqual(lineSummary({ ...g4, outcome: "material", material_change: -3 }),
                   { kind: "loss", text: "Material at the end: −3" });
  assert.equal(lineSummary({ ...g4, outcome: "none" }).kind, "even");
});

test("fens replay the line", () => {
  const f = lineFens(g4);
  assert.equal(f.length, 3);
  assert.equal(f[2].split(" ")[0], "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR");
});
