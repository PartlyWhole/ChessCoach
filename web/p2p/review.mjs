// Pure helpers for the post-game analysis panel (ADR 0003). The review itself comes from the
// Python WebApp.review() (classification, accuracy and moments are not recomputed here); these
// functions only format it. Tested in review.test.mjs.

export const CLASS_SYMBOL = { inaccuracy: "?!", mistake: "?", blunder: "??" };
export const BAD = ["inaccuracy", "mistake", "blunder"];
export const plural = (n, word) => `${n} ${n === 1 ? word : word === "inaccuracy" ? "inaccuracies" : word + "s"}`;

// "5." before White's move, "5..." before Black's (ply is 0-based).
export const moveNumber = (ply) => `${Math.floor(ply / 2) + 1}.${ply % 2 ? ".." : ""}`;

// SAN line starting at `ply`, numbered: "5... Qxd5 6. Nc3 Qa5".
export function numberedLine(sans, ply) {
  return sans.map((san, i) => {
    const p = ply + i;
    if (i === 0) return `${moveNumber(p)} ${san}`;
    return p % 2 === 0 ? `${moveNumber(p)} ${san}` : san;
  }).join(" ");
}

export const pct = (x) => `${Math.round(x * 100)}%`;

// Facts for one ply of the review, all straight from the engine data.
export function plyFacts(review, ply) {
  const p = review.plies[ply];
  const facts = {
    label: `${moveNumber(ply)} ${p.san}${CLASS_SYMBOL[p.move_class] || ""}`,
    mover: p.mover,
    moveClass: p.move_class,
    chances: `${pct(p.wp_before)} → ${pct(p.wp_after)}`,
    best: null,
  };
  if (!["best", "forced", "book"].includes(p.move_class) && p.best_san && p.best_move !== p.move) {
    facts.best = { san: p.best_san, line: numberedLine(p.best_line_san, ply) };
  }
  return facts;
}

// Points for the White-win-probability graph: one per position (start + after each ply).
export function graphPoints(review, width, height) {
  const wps = [review.wp_white_start, ...review.plies.map((p) => p.wp_white_after)];
  const n = Math.max(1, wps.length - 1);
  return wps.map((wp, i) => [+(i * width / n).toFixed(2), +((1 - wp) * height).toFixed(2)]);
}

// Nearest position index for a click at x on a graph `width` wide.
export function plyAtX(review, x, width) {
  const n = review.plies.length;
  return Math.max(0, Math.min(n, Math.round(x / width * n)));
}

// Key moments of both players in game order.
export function moments(review) {
  return ["white", "black"].flatMap((c) => review.sides[c].moments.map((m) => ({ ...m, color: c })))
    .sort((a, b) => a.ply - b.ply);
}

// v2: reviews carry line explanations ("why").
export const cacheKey = (docUrl, drafts) => `p2pchess.review.v2.${docUrl}.${drafts ? "drafts" : "approved"}`;
