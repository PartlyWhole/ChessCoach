// Formatting for line explanations (docs/02 §6.6) in the "Why?" explorer. The explanation is
// computed in Python (chesscoach.analysis.lines); these helpers only turn its fields into labels.
// Every label states a computed fact (a capture, check, mate, material count or a detector id),
// never a reason. Tested in lines.test.mjs.
import { Chess } from "chess.js";

// Detector ids (02 §6.1) as short labels. A fork implies a double attack, so that is dropped.
export const FEATURE_LABEL = {
  fork: "Fork", double_attack: "Double attack", discovered_attack: "Discovered attack",
  discovered_check: "Discovered check", double_check: "Double check", pin_absolute: "Pin",
  pin_relative: "Pin", skewer: "Skewer", trapped_piece: "Trapped piece",
  overloaded_defender: "Overloaded defender", removing_defender: "Removes the defender",
  hanging_piece: "Hanging piece", back_rank_weakness: "Back rank", mate_threat: "Mate threat",
};

export function featureLabels(ids) {
  const set = new Set(ids);
  if (set.has("fork")) set.delete("double_attack");
  if (set.has("discovered_check")) set.delete("discovered_attack");
  const out = [];
  for (const id of set) { const l = FEATURE_LABEL[id]; if (l && !out.includes(l)) out.push(l); }
  return out;
}

const moveNo = (ply) => `${Math.floor(ply / 2) + 1}.${ply % 2 ? ".." : ""}`;
const signed = (n) => (n > 0 ? `+${n}` : n < 0 ? `−${-n}` : "0");

// Rows for a line that starts at game ply `startPly` (0-based ply of the line's first move).
export function lineRows(ex, startPly) {
  return ex.steps.map((s) => {
    const p = startPly + s.ply;
    const badges = [];
    if (s.captured) badges.push({ kind: "capture", text: `takes ${s.captured}` });
    if (s.promotion) badges.push({ kind: "promotion", text: `promotes to ${s.promotion}` });
    for (const l of featureLabels(s.feature_ids)) badges.push({ kind: "feature", text: l });
    if (s.mate) badges.push({ kind: "mate", text: "mate" });
    else if (s.check) badges.push({ kind: "check", text: "check" });
    return {
      step: s.ply, label: `${moveNo(p)} ${s.san}`, mover: s.mover, badges,
      material: signed(s.material), decisive: ex.decisive_ply === s.ply, squares: s.squares,
    };
  });
}

// One-line result of a line, from the perspective side's point of view.
export function lineSummary(ex) {
  if (ex.outcome === "mate") {
    return { kind: "mate", text: ex.mate_for === ex.perspective ? "Ends in mate for you" : "Ends in mate against you" };
  }
  if (ex.outcome === "material") {
    const n = ex.material_change;
    return { kind: n > 0 ? "gain" : "loss", text: `Material at the end: ${signed(n)}` };
  }
  return { kind: "even", text: ex.steps.length ? "Material stays level" : "No line available" };
}

// FEN after each step: fens[0] is the start, fens[i + 1] after step i.
export function lineFens(ex) {
  const c = new Chess(ex.start_fen);
  const fens = [c.fen()];
  for (const s of ex.steps) {
    c.move({ from: s.move.slice(0, 2), to: s.move.slice(2, 4), promotion: s.move[4] });
    fens.push(c.fen());
  }
  return fens;
}
