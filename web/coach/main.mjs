// Coach page (ADR 0002, 0004): play the Maia sparring bot with live coaching, then review the game
// with line explanations; the learner profile (rating, band, mastery, cards) persists in this
// browser. All chess logic runs in the Python worker (runtime.js); this file draws the board,
// relays clicks and renders what Python returns.
import { START_FEN, renderBoard, renderCaptureStrip } from "../shared/board.mjs";
import * as RP from "../shared/review-panel.mjs";
import * as R from "../shared/review.mjs";
import * as L from "../shared/lines.mjs";
import { captures, materialBalance, replay } from "../shared/replay.mjs";
import { initDrills, refreshDrills } from "./drills.mjs";

const $ = (id) => document.getElementById(id);
const setStatus = (msg) => { $("status").textContent = msg; };
const PIECE_LETTER = { pawn: "p", knight: "n", bishop: "b", rook: "r", queen: "q", king: "k" };

// ------------------------------------------------------------------ runtime
let callPy = () => Promise.reject(new Error("not ready"));
let onEngine = () => {};
let persistent = false, ready = false;
export const py = (method, ...args) => callPy(method, ...args);

// ------------------------------------------------------------------ state
let state = null;          // last state from Python (WebApp._state)
let rp = { moves: [], fens: [START_FEN] };   // replay of state.moves: SAN, captures, FENs
let selected = null, busy = false, flipped = null;
let highlight = { squares: [], arrows: [] };
let viewPly = null;        // null = live position
let variation = null;      // { ply, which, step } while exploring a "Why?" line
let review = null, finished = null, finishing = false;
// Live coaching visibility: per-move ratings (move index → class), ideas noted for the review,
// the latest coach message and the latest move feedback.
let liveClass = {}, noted = [], lastEvent = null, lastFeedback = null;
const optRatings = () => $("opt-ratings").checked;
const optEval = () => $("opt-eval").checked;
const CLASS_TEXT = { best: "best", excellent: "excellent", good: "good", inaccuracy: "an inaccuracy",
                     mistake: "a mistake", blunder: "a blunder", book: "book", forced: "forced" };
let learner = { has_profile: false };

const drafts = () => $("drafts").checked;
const playerColor = () => (state ? state.player_color : $("color").value);
const inGame = () => !!state && !state.game_over;

// ------------------------------------------------------------------ tabs
function showTab(name) {
  for (const t of ["play", "drills", "progress"]) {
    $("view-" + t).hidden = t !== name;
    $("tab-" + t).setAttribute("aria-selected", String(t === name));
  }
  if (name === "progress") refreshLearner();
  if (name === "drills") refreshDrills();
}
document.querySelectorAll(".tabs button").forEach((b) => { b.onclick = () => showTab(b.dataset.tab); });

// ------------------------------------------------------------------ board
const variationLine = () => RP.variationLine(review, variation);

function render() {
  const flip = flipped ?? playerColor() === "black";
  const line = variationLine();
  const n = rp.moves.length;
  let fen, lastUci = null, hl = [], movesForCaptures, arrows = [];
  if (line) {
    const fens = L.lineFens(line);
    const k = Math.min(variation.step, line.steps.length);
    fen = fens[k];
    const st = k > 0 ? line.steps[k - 1] : null;
    lastUci = st ? st.move : (variation.ply > 0 ? rp.moves[variation.ply - 1].uci : null);
    hl = st ? st.squares : [];
    movesForCaptures = [...rp.moves.slice(0, variation.ply),
                        ...line.steps.slice(0, k).map((s) => ({ captured: s.captured ? PIECE_LETTER[s.captured] : null }))];
  } else if (viewPly !== null) {
    fen = rp.fens[viewPly];
    lastUci = viewPly > 0 ? rp.moves[viewPly - 1].uci : null;
    movesForCaptures = rp.moves.slice(0, viewPly);
  } else {
    fen = state ? state.fen : START_FEN;
    lastUci = n ? rp.moves[n - 1].uci : null;
    hl = [...highlight.squares, ...highlight.arrows.flat()];
    movesForCaptures = rp.moves;
    arrows = highlight.arrows;
  }
  const live = !line && viewPly === null;
  const legal = live && state ? state.legal : [];
  renderBoard($("board"), {
    fen, flip, highlight: hl, arrows,
    last: lastUci ? [lastUci.slice(0, 2), lastUci.slice(2, 4)] : [],
    selected: live ? selected : null,
    targets: selected && live ? legal.filter((m) => m.startsWith(selected)).map((m) => m.slice(2, 4)) : [],
    check: live && /[+#]$/.test(n ? rp.moves[n - 1].san : "") ? (fen.split(" ")[1] === "w" ? "K" : "k") : null,
    onSquare,
  });
  renderEvalBar(flip, live);
  const taken = captures(movesForCaptures);
  const bal = materialBalance(fen);
  const me = playerColor();
  for (const [pos, color] of [["top", flip ? "white" : "black"], ["bottom", flip ? "black" : "white"]]) {
    renderCaptureStrip($("caps-" + pos), {
      color, taken: taken[color], lead: color === "white" ? bal : -bal,
      name: !state ? (color === "white" ? "White" : "Black") : color === me ? "You" : `Bot${state.bot_elo ? ` (${state.bot_elo})` : ""}`,
    });
  }
}

async function onSquare(sq) {
  if (variationLine()) return;
  if (viewPly !== null) { if (inGame()) goTo(rp.moves.length); return; }
  if (!state || busy || !state.legal.length) return;
  if (selected && state.legal.some((m) => m.startsWith(selected + sq))) {
    const choices = state.legal.filter((m) => m.startsWith(selected + sq));
    const uci = choices.length > 1 ? await choosePromotion(choices) : choices[0];
    selected = null;
    if (uci) await act("move", uci); else render();
    return;
  }
  selected = selected !== sq && state.legal.some((m) => m.startsWith(sq)) ? sq : null;
  render();
}

function choosePromotion(choices) {
  return new Promise((resolve) => {
    const dlg = $("promo"), box = dlg.querySelector(".promo");
    box.innerHTML = "";
    const color = playerColor() === "white" ? "w" : "b";
    const GL = { q: "♛", r: "♜", b: "♝", n: "♞" };
    for (const p of ["q", "r", "b", "n"]) {
      const uci = choices.find((m) => m.endsWith(p));
      if (!uci) continue;
      const b = document.createElement("button");
      b.className = "pc " + color;
      b.textContent = GL[p];
      b.ariaLabel = { q: "Queen", r: "Rook", b: "Bishop", n: "Knight" }[p];
      b.onclick = () => { dlg.close(); resolve(uci); };
      box.appendChild(b);
    }
    dlg.onclose = () => resolve(null);
    dlg.showModal();
  });
}

// ------------------------------------------------------------------ move list and history
function renderMoves() {
  const ol = $("moves");
  ol.innerHTML = "";
  const cur = viewPly ?? rp.moves.length;
  const span = (i) => {
    const s = document.createElement("span");
    const r = review && review.plies[i];
    const cls = r ? r.move_class : optRatings() ? liveClass[i] : null;
    s.className = "mv go" + (cur === i + 1 ? " cur" : "") + (cls ? " " + cls : "");
    s.textContent = rp.moves[i].san + (cls ? R.CLASS_SYMBOL[cls] || "" : "");
    if (cls) s.title = cls;
    s.onclick = () => goTo(i + 1);
    return s;
  };
  for (let i = 0; i < rp.moves.length; i += 2) {
    const li = document.createElement("li");
    li.append(span(i));
    if (rp.moves[i + 1]) li.append(span(i + 1));
    ol.appendChild(li);
  }
  if (state && state.game_over) {
    const li = document.createElement("li");
    li.className = "result";
    li.textContent = state.result;
    ol.appendChild(li);
  }
  if (viewPly === null) ol.scrollTop = ol.scrollHeight;
}

function goTo(ply) {
  const n = rp.moves.length;
  ply = Math.max(0, Math.min(n, ply));
  viewPly = ply === n ? null : ply;
  selected = null;
  variation = null;
  render(); renderMoves(); renderNav(); renderAnalysis();
  const cur = $("moves").querySelector(".cur");
  if (cur) cur.scrollIntoView({ block: "nearest" });
}

function renderNav() {
  const n = rp.moves.length, cur = viewPly ?? n;
  $("nav-first").disabled = $("nav-prev").disabled = cur === 0;
  $("nav-next").disabled = $("nav-last").disabled = cur === n;
  const v = $("viewing");
  v.innerHTML = "";
  const line = variationLine();
  if (!line && viewPly === null) { v.hidden = true; return; }
  v.hidden = false;
  const back = document.createElement("button");
  back.className = "link";
  back.textContent = line || inGame() ? "Back to the game" : "Final position";
  back.onclick = () => (line ? exitVariation() : goTo(n));
  const what = line ? `Exploring ${variation.which === "played" ? `after ${rp.moves[variation.ply].san}` : "the engine's best line"}` +
    ` · move ${variation.step} of ${line.steps.length}` : `Viewing move ${viewPly} of ${n}`;
  v.append(what + " · ", back);
}

$("nav-first").onclick = () => goTo(0);
$("nav-prev").onclick = () => goTo((viewPly ?? rp.moves.length) - 1);
$("nav-next").onclick = () => goTo((viewPly ?? rp.moves.length) + 1);
$("nav-last").onclick = () => goTo(rp.moves.length);
document.addEventListener("keydown", (e) => {
  if ($("view-play").hidden || e.target.closest?.("input, select, textarea, dialog")) return;
  if (variationLine()) {
    const d = { ArrowLeft: -1, ArrowRight: 1 }[e.key];
    if (d) { stepVariation(d); e.preventDefault(); return; }
    if (e.key === "Escape") { exitVariation(); e.preventDefault(); return; }
  }
  const cur = viewPly ?? rp.moves.length;
  const to = { ArrowLeft: cur - 1, ArrowRight: cur + 1, Home: 0, End: rp.moves.length }[e.key];
  if (to !== undefined && state) { goTo(to); e.preventDefault(); }
});

// ------------------------------------------------------------------ "Why?" lines
function openVariation(ply, which, step) {
  variation = { ply, which, step };
  viewPly = ply + 1;
  render(); renderMoves(); renderNav(); renderAnalysis();
}
function stepVariation(d) {
  const line = variationLine();
  if (!line) return;
  variation.step = Math.max(0, Math.min(line.steps.length, variation.step + d));
  render(); renderNav(); renderAnalysis();
}
function exitVariation() {
  if (!variation) return;
  const ply = variation.ply;
  variation = null;
  goTo(ply + 1);
}

// ------------------------------------------------------------------ coach messages and play
function coachSay(ev, meta) {
  if (!ev) return;
  const li = document.createElement("li");
  const k = document.createElement("div");
  k.className = "k " + ev.kind;
  k.textContent = ev.kind + (ev.hint_level ? " · level " + ev.hint_level : "");
  const t = document.createElement("div"); t.textContent = ev.text;
  li.append(k, t);
  if (meta) { const m = document.createElement("div"); m.className = "meta"; m.textContent = meta; li.append(m); }
  $("coach").prepend(li);
  highlight = ev.highlight || { squares: [], arrows: [] };
  lastEvent = ev;
  renderCoachNow();
}

// ------------------------------------------------------------------ live coaching panel
function renderCoachNow() {
  const box = $("coach-now");
  box.hidden = !state;
  if (!state) return;
  const ev = lastEvent;
  const kind = $("cn-kind"), ladder = $("cn-ladder"), text = $("cn-text");
  kind.hidden = !ev;
  ladder.hidden = !ev || !ev.hint_level;
  if (ev) {
    kind.textContent = { interrupt: "Wait!", comment: "Comment", praise: "Nice", hint: "Hint", note: "Note" }[ev.kind] || ev.kind;
    kind.className = "tag " + ev.kind;
    ladder.textContent = ev.hint_level ? "●".repeat(ev.hint_level) + "○".repeat(3 - ev.hint_level) : "";
    ladder.title = ev.hint_level ? `Hint level ${ev.hint_level} of 3` : "";
    text.textContent = ev.text;
    text.className = "cn-text";
  } else {
    text.className = "cn-text quiet";
    text.textContent = state.game_over ? "Game over. The review is below."
      : state.concepts_loaded ? "Watching. The coach speaks when something important happens; ask for a hint any time."
      : "Watching quietly: no coaching text is approved yet (turn on the developer preview to see drafts). Move ratings and the review still work.";
  }
  const mv = $("cn-move");
  const f = lastFeedback;
  mv.hidden = !f || !optRatings();
  if (f && optRatings()) {
    mv.innerHTML = "";
    const cls = document.createElement("span");
    cls.className = "cls " + f.move_class;
    cls.textContent = CLASS_TEXT[f.move_class] || f.move_class;
    const pct = (x) => `${Math.round(x * 100)}%`;
    mv.append(`Your move ${f.san} was `, cls, `. Your winning chances: ${pct(f.win_prob_before)} → ${pct(f.win_prob_after)}.`);
  }
  renderTally();
  renderNoted();
}

function renderTally() {
  const t = $("tally");
  const vals = Object.values(liveClass);
  t.hidden = !optRatings() || !vals.length;
  if (t.hidden) return;
  const order = ["best", "excellent", "good", "book", "forced", "inaccuracy", "mistake", "blunder"];
  const counts = order.map((k) => [k, vals.filter((v) => v === k).length]).filter(([, n]) => n);
  t.textContent = "Your moves: " + counts.map(([k, n]) => `${n} ${k}`).join(" · ");
}

function renderNoted() {
  const box = $("noted-box");
  box.hidden = !noted.length;
  $("noted-count").textContent = noted.length;
  const ul = $("noted");
  ul.innerHTML = "";
  for (const x of noted) {
    const li = document.createElement("li");
    li.textContent = `Move ${Math.floor(x.ply / 2) + 1}: ${x.title}`;
    ul.append(li);
  }
}

function renderEvalBar(flip, live) {
  const bar = $("evalbar");
  const wp = state && state.eval_white;
  bar.hidden = !optEval() || wp == null || !live;
  if (bar.hidden) return;
  bar.classList.toggle("flip", flip);
  bar.querySelector(".fill").style.height = `${Math.round(wp * 100)}%`;
  const lead = wp >= 0.5 ? `White ${Math.round(wp * 100)}%` : `Black ${Math.round((1 - wp) * 100)}%`;
  bar.querySelector(".lbl").textContent = lead;
  bar.setAttribute("aria-label", `Engine evaluation: ${lead} winning chances`);
}

function setState(s) {
  state = s;
  rp = replay(s.start_fen, s.moves);
  if (viewPly !== null && viewPly >= rp.moves.length) viewPly = null;
}

async function act(method, ...args) {
  busy = true; updateButtons();
  setStatus("Thinking…");
  try {
    const s = await callPy(method, ...args);
    highlight = { squares: [], arrows: [] };
    if (s.event) coachSay(s.event, s.assessment ? s.assessment.san + ": " + s.assessment.move_class : null);
    setState(s);
    const n = s.moves.length;
    for (const k of Object.keys(liveClass)) if (Number(k) >= n) delete liveClass[k];
    noted = noted.filter((x) => x.ply < n);
    if (s.assessment) {
      const idx = s.bot_move ? n - 2 : n - 1;           // index of the player's move in the game
      liveClass[idx] = s.assessment.move_class;
      lastFeedback = { ...s.assessment, ply: idx };
      for (const q of s.queued || []) noted.push({ ply: idx, title: q.title, concept_id: q.concept_id });
    }
    if (s.waiting_for_takeback) setStatus("Take back to try again, ask for a hint, or keep your move.");
    else if (s.game_over) setStatus(`Game over: ${s.result}${s.resigned ? " (you resigned)" : ""}`);
    else setStatus(s.bot_san ? "Bot played " + s.bot_san + ". Your move." : "Your move.");
    if (!s.waiting_for_takeback && !s.game_over && $("mode").value === "guided" && s.legal.length) {
      const pre = await callPy("pre_move_prompt");
      if (pre.event) coachSay(pre.event, "before your move");
    }
  } catch (err) {
    setStatus("Error: " + err.message);
  }
  busy = false; updateButtons(); render(); renderMoves(); renderNav(); renderCoachNow();
  if (state && state.game_over && !finished && !finishing) finishGame();
}

function updateButtons() {
  const waiting = !!(state && state.waiting_for_takeback);
  $("hint").disabled = busy || !inGame();
  $("takeback").disabled = busy || !waiting;
  $("resume").disabled = busy || !waiting;
  $("resign").disabled = busy || !inGame();
  $("start").disabled = busy || !ready;
  $("setup").hidden = inGame() || finishing;
  $("game-card").hidden = !state;
}

// ------------------------------------------------------------------ after the game
async function finishGame() {
  finishing = true;
  updateButtons();
  $("analysis").hidden = false;
  $("an-result").hidden = true;
  $("an-summary").innerHTML = "";
  $("again").hidden = true;
  const fen4 = (f) => f.split(" ").slice(0, 4).join(" ");
  const plyOf = new Map(rp.fens.map((f, i) => [fen4(f), i]));
  let furthest = 0;
  const total = rp.moves.length;
  const show = (msg) => { $("an-progress").hidden = false; $("an-progress").textContent = msg; };
  onEngine = (req) => {
    const i = plyOf.get(fen4(req.fen));
    if (i !== undefined && i > furthest) { furthest = i; show(`Reviewing move ${Math.min(i + 1, total)} of ${total}…`); }
  };
  show(`Reviewing the game (${total} moves)…`);
  try {
    finished = await callPy("finish_game");
    review = finished.review;
    $("an-progress").hidden = true;
  } catch (err) {
    show("Review failed: " + err.message);
  } finally {
    onEngine = () => {};
    finishing = false;
    $("again").hidden = false;
    updateButtons();
    renderMoves(); renderAnalysis();
    refreshLearner();
  }
}

function renderSummary() {
  const box = $("an-summary");
  box.innerHTML = "";
  if (!finished) return;
  const sum = finished.summary;
  const res = document.createElement("p");
  res.className = "result-line";
  res.textContent = { 1: "You won.", 0.5: "Draw.", 0: "You lost." }[finished.score] + ` (${finished.result})`;
  box.append(res);
  if (!sum) return;
  const d = sum.rating_after - sum.rating_before;
  const lines = [
    `Rating ${sum.rating_before} → ${sum.rating_after} (${d >= 0 ? "+" : "−"}${Math.abs(d)})`,
    sum.band_after !== sum.band_before ? `Band ${sum.band_before} → ${sum.band_after}` : `Band ${sum.band_after}`,
    `Next bot: ${sum.next_bot_elo}`,
  ];
  if (sum.cards_saved) lines.push(`${sum.cards_saved} position${sum.cards_saved === 1 ? "" : "s"} saved to your drills`);
  for (const c of sum.mastery_changes) lines.push(`${c.concept_id}: ${c.from} → ${c.to}`);
  const ul = document.createElement("ul");
  for (const t of lines) { const li = document.createElement("li"); li.textContent = t; ul.append(li); }
  box.append(ul);
}

function renderAnalysis() {
  $("analysis").hidden = !finished && !finishing;
  renderSummary();
  $("an-result").hidden = !review;
  if (!review) return;
  const cur = viewPly ?? review.plies.length;
  const me = playerColor();
  RP.renderAccuracy($("an-acc"), review, { white: me === "white" ? "You" : "Bot", black: me === "black" ? "You" : "Bot" });
  RP.renderGraph($("an-graph"), review, cur);
  RP.renderDetail($("an-detail"), review, cur, { variation, open: openVariation, step: stepVariation, exit: exitVariation });
  RP.renderMoments($("an-moments"), review, goTo);
  $("an-meta").textContent = `${review.engine}, depth ${review.depth}. Its evaluations differ slightly from full ` +
    "Stockfish, so treat close calls with care.";
}
$("an-graph").onclick = (e) => { if (review) goTo(RP.graphClickPly(e, review)); };

$("again").onclick = () => {
  state = null; rp = { moves: [], fens: [START_FEN] }; review = null; finished = null; viewPly = null; variation = null;
  liveClass = {}; noted = []; lastEvent = null; lastFeedback = null;
  renderCoachNow();
  highlight = { squares: [], arrows: [] };
  $("coach").innerHTML = "";
  $("analysis").hidden = true;
  updateButtons(); render(); renderMoves(); renderNav();
  setStatus("Choose your settings and press Start.");
};

// ------------------------------------------------------------------ controls
$("setup").onsubmit = async (e) => {
  e.preventDefault();
  $("coach").innerHTML = "";
  selected = null; review = null; finished = null; viewPly = null; variation = null;
  liveClass = {}; noted = []; lastEvent = null; lastFeedback = null;
  $("analysis").hidden = true;
  await act("new_game", $("color").value, Number($("rating").value), $("mode").value, drafts());
  if (!state) return;
  const lesson = $("lesson-line");
  lesson.hidden = !state.lesson_title;
  lesson.textContent = state.lesson_title ? `This game's lesson: ${state.lesson_title}. The bot may steer toward it.` : "";
  if (!state.concepts_loaded) coachSay({ kind: "note", hint_level: 0, text:
    "No coaching text is approved yet, so the coach stays silent. Tick the developer preview to see the drafts." });
  refreshLearner();
};
$("hint").onclick = async () => {
  const s = await callPy("hint");
  coachSay(s.event || { kind: "hint", hint_level: 0, text: "No hint available here." });
  render();
};
$("takeback").onclick = () => act("takeback");
$("resume").onclick = () => act("resume");
$("resign").onclick = () => { if (confirm("Resign this game?")) act("resign"); };
$("flip").onclick = () => { flipped = !(flipped ?? playerColor() === "black"); render(); };
$("color").onchange = () => { if (!state) render(); };

// ------------------------------------------------------------------ progress
const METRIC_LABEL = {
  tactics_found: ["Tactics found", (v) => `${Math.round(v * 100)}%`],
  tactics_allowed: ["Tactics allowed (per 100 moves)", (v) => v.toFixed(1)],
  opening: ["Opening: average loss per move", (v) => `${(v * 100).toFixed(1)}%`],
  conversion: ["Winning positions converted", (v) => `${Math.round(v * 100)}%`],
  resourcefulness: ["Lost positions saved", (v) => `${Math.round(v * 100)}%`],
  endgame: ["Endgame: average loss per move", (v) => `${(v * 100).toFixed(1)}%`],
  accuracy_opening: ["Accuracy in the opening", (v) => `${Math.round(v)}%`],
  accuracy_middlegame: ["Accuracy in the middlegame", (v) => `${Math.round(v)}%`],
  accuracy_endgame: ["Accuracy in the endgame", (v) => `${Math.round(v)}%`],
};

export async function refreshLearner() {
  if (!ready) return;
  try { learner = await callPy("learner_state", drafts()); } catch { return; }
  const has = learner.has_profile;
  $("rating-row").hidden = has;
  $("profile-line").hidden = !has;
  if (has) $("profile-line").textContent = `Your rating: ${learner.rating} (${learner.band}). Next bot: ${learner.bot_elo}.`;
  $("progress-empty").hidden = has;
  $("progress").hidden = !has;
  const due = has ? learner.cards.due + Math.min(learner.cards.new, 5) : 0;
  $("drill-count").hidden = !due;
  $("drill-count").textContent = due;
  if (!has) return;
  $("p-rating").textContent = learner.rating;
  $("p-rd").textContent = `± ${learner.rd}`;
  $("p-band").textContent = learner.band;
  $("p-bot").textContent = learner.bot_elo;
  $("p-games").textContent = learner.games;
  $("p-results").textContent = learner.recent_results.length
    ? "recent: " + learner.recent_results.map((r) => ({ 1: "W", 0.5: "D", 0: "L" }[r])).join(" ") : "";
  $("p-drill").textContent = learner.drill_rating;
  $("p-cards").textContent = learner.cards.total;
  $("p-cards-due").textContent = `${learner.cards.due} due · ${learner.cards.new} new`;
  const worst = learner.worst_metric && METRIC_LABEL[learner.worst_metric];
  $("p-focus").textContent = (worst ? `Weakest area so far: ${worst[0].toLowerCase()}. ` : "Not enough games yet to find a weak area. ") +
    (learner.lesson_focus ? `Next game's lesson: ${learner.lesson_focus}.` : "");
  const tb = $("p-metrics");
  tb.innerHTML = "";
  for (const [k, [label, fmt]] of Object.entries(METRIC_LABEL)) {
    const v = learner.weakness[k];
    const tr = document.createElement("tr");
    if (k === learner.worst_metric) tr.className = "worst";
    const a = document.createElement("td"); a.textContent = label;
    const b = document.createElement("td"); b.textContent = v == null ? "–" : fmt(v);
    tr.append(a, b); tb.append(tr);
  }
  const c = learner.mastery.counts;
  $("p-mastery-counts").textContent = learner.mastery.concepts.length
    ? `${c.mastered} mastered · ${c.practised} practised · ${c.learning} learning`
    : "No concepts tracked yet. Concepts are tracked when approved coaching text exists (or with the developer preview).";
  const ul = $("p-concepts");
  ul.innerHTML = "";
  for (const m of learner.mastery.concepts) {
    const li = document.createElement("li");
    li.innerHTML = "";
    const t = document.createElement("span"); t.textContent = m.title;
    const s = document.createElement("span"); s.className = "tag state " + m.state; s.textContent = m.state;
    const o = document.createElement("span"); o.className = "muted"; o.textContent = ` ${m.opportunities} seen`;
    li.append(t, " ", s, o);
    ul.append(li);
  }
  $("p-persist").textContent = learner.persistent
    ? "Saved in this browser (IndexedDB). Other browsers and devices don't see it. Clearing site data deletes it."
    : "This browser isn't letting the page store data (private window or blocked storage), so progress lasts only until you close the tab.";
}

$("p-reset").onclick = async () => {
  if (!confirm("Delete your rating, games, concepts and drills from this browser?")) return;
  await callPy("reset_progress");
  refreshLearner();
};
$("drafts").onchange = () => refreshLearner();
$("opt-ratings").onchange = () => { renderMoves(); renderCoachNow(); };
$("opt-eval").onchange = () => render();

// ------------------------------------------------------------------ boot
if (!self.crossOriginIsolated) {
  setStatus("Enabling cross-origin isolation (the page reloads once)…");
} else {
  const rt = ChessCoachRuntime.start({ onProgress: setStatus, preloadMaia: true, onEngine: (r) => onEngine(r) });
  callPy = rt.call;
  rt.ready.then((info) => {
    ready = true;
    persistent = info && info.persistent;
    setStatus("Ready. Choose your settings and press Start.");
    updateButtons();
    refreshLearner();
    initDrills({ py, refreshLearner, drafts });
  }, (err) => setStatus("Failed to start: " + err.message));
}
updateButtons(); render(); renderNav();
