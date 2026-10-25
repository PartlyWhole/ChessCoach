// Post-game review panel shared by the p2p page and the coach page (ADR 0003, 0004): accuracy
// rows, White-win-probability graph, the selected move's facts with its "Why?" lines, key
// moments. The page owns the state (which ply is shown, which line is explored); these functions
// only draw it and report clicks through the callbacks in `ctx`.
import * as R from "./review.mjs";
import * as L from "./lines.mjs";

const SVG = "http://www.w3.org/2000/svg";
const W = 400, H = 100;

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function svgEl(name, attrs) {
  const e = document.createElementNS(SVG, name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
}

// names: { white, black } labels for the accuracy rows.
export function renderAccuracy(box, review, names) {
  box.innerHTML = "";
  for (const c of ["white", "black"]) {
    const side = review.sides[c];
    const row = el("div", "acc-row");
    const num = el("strong", null, side.accuracy == null ? "–" : `${Math.round(side.accuracy)}%`);
    num.title = "Accuracy (Lichess formula, from win-probability loss)";
    row.append(el("span", "who", `${c === "white" ? "White" : "Black"} · ${names[c]}`), num,
               el("span", "counts", R.BAD.map((k) => R.plural(side.counts[k], k)).join(" · ")));
    box.append(row);
  }
}

export function renderGraph(svg, review, cur) {
  svg.innerHTML = "";
  const pts = R.graphPoints(review, W, H);
  const line = pts.map((p) => p.join(",")).join(" ");
  svg.append(svgEl("rect", { class: "g-bg", x: 0, y: 0, width: W, height: H }));
  svg.append(svgEl("polygon", { class: "g-white", points: `0,${H} ${line} ${W},${H}` }));
  svg.append(svgEl("line", { class: "g-mid", x1: 0, y1: H / 2, x2: W, y2: H / 2 }));
  svg.append(svgEl("polyline", { class: "g-line", points: line }));
  review.plies.forEach((p, i) => {
    if (p.move_class === "mistake" || p.move_class === "blunder") {
      const [x, y] = pts[i + 1];
      // A zero-length round-capped line: a dot that the stretched viewBox does not distort.
      svg.append(svgEl("line", { class: "g-dot " + p.move_class, x1: x, y1: y, x2: x, y2: y + 0.01 }));
    }
  });
  const x = pts[Math.min(cur, pts.length - 1)][0];
  svg.append(svgEl("line", { class: "g-cur", x1: x, y1: 0, x2: x, y2: H }));
}

// The game position (0..n) under a click on the graph.
export function graphClickPly(e, review) {
  const r = e.currentTarget.getBoundingClientRect();
  return R.plyAtX(review, (e.clientX - r.left) / r.width * W, W);
}

// ctx: { variation: {ply, which, step} | null, open(ply, which, step), step(d), exit() }
export function renderDetail(box, review, cur, ctx) {
  box.innerHTML = "";
  if (cur === 0) { box.textContent = "Starting position."; return; }
  const f = R.plyFacts(review, cur - 1);
  const head = el("div", "d-head");
  head.append(el("strong", null, f.label), el("span", "tag cls " + f.moveClass, f.moveClass));
  box.append(head, el("div", null, `${f.mover === "white" ? "White" : "Black"}'s winning chances: ${f.chances}`));
  const why = review.plies[cur - 1].why;
  if (why) box.append(renderWhy(review, cur - 1, why, ctx));
  else if (f.best) box.append(el("div", null, `Engine's best: ${f.best.san}. Line: ${f.best.line}`));
  const m = R.moments(review).find((x) => x.ply === cur - 1 && x.summary);
  if (m) {
    const t = el("div", "draft", m.summary);
    t.prepend(el("span", "tag", "unreviewed draft"), " ");
    box.append(t);
  }
}

function renderWhy(review, ply, why, ctx) {
  const v = ctx.variation;
  const active = v && v.ply === ply ? v.which : null;
  const box = el("div", "why");
  const tabs = el("div", "why-tabs");
  const p = review.plies[ply];
  for (const [which, label] of [["played", `After ${p.san}`], ["best", `Best: ${p.best_san || "–"}`]]) {
    const b = el("button", which === (active || "played") ? "on" : "", label);
    b.setAttribute("aria-pressed", String(which === active));
    b.onclick = () => ctx.open(ply, which, 1);
    tabs.append(b);
  }
  box.append(tabs);
  const ex = why[active || "played"];
  const sum = L.lineSummary(ex);
  box.append(el("p", "why-sum " + sum.kind, sum.text));
  const ol = el("ol", "why-line");
  for (const row of L.lineRows(ex, ply)) {
    const li = el("li", (row.decisive ? "decisive " : "") + (active && v.step === row.step + 1 ? "cur" : ""));
    const mv = el("button", "link mv-label", row.label);
    mv.onclick = () => ctx.open(ply, active || "played", row.step + 1);
    li.append(mv);
    for (const bdg of row.badges) li.append(el("span", "badge " + bdg.kind, bdg.text));
    const mat = el("span", "mat", row.material);
    mat.title = "Material since the move, for the side that played it";
    li.append(mat);
    ol.append(li);
  }
  box.append(ol);
  const nav = el("div", "why-nav");
  if (active) {
    const prev = el("button", null, "◀"); prev.ariaLabel = "Previous move in the line";
    prev.onclick = () => ctx.step(-1); prev.disabled = v.step === 0;
    const next = el("button", null, "▶"); next.ariaLabel = "Next move in the line";
    next.onclick = () => ctx.step(1); next.disabled = v.step >= ex.steps.length;
    const back = el("button", null, "Back to the game"); back.onclick = () => ctx.exit();
    nav.append(prev, next, back);
  } else {
    const show = el("button", "primary", "Show on the board");
    show.onclick = () => ctx.open(ply, "played", 1);
    nav.append(show);
  }
  box.append(nav);
  return box;
}

export function renderMoments(ol, review, goTo) {
  ol.innerHTML = "";
  const ms = R.moments(review);
  for (const m of ms) {
    const li = document.createElement("li");
    const f = R.plyFacts(review, m.ply);
    const a = el("button", "link", `${f.label} (${m.color}, ${m.move_class})`);
    a.onclick = () => goTo(m.ply + 1);
    li.append(a);
    if (m.summary) li.append(el("div", "draft", m.summary));
    else if (f.best) li.append(el("div", "muted", `Best was ${f.best.san}.`));
    ol.append(li);
  }
  if (!ms.length) ol.append(el("li", "muted", "No inaccuracies, mistakes or blunders."));
}

// The explanation for a variation being explored, or null.
export function variationLine(review, variation) {
  if (!variation || !review) return null;
  const p = review.plies[variation.ply];
  return p && p.why ? p.why[variation.which] : null;
}
