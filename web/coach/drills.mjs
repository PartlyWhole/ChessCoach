// Drills tab (docs/06 §5, ADR 0004): today's queue (due cards, new cards from recent games,
// puzzles), one attempt at a time. Python checks moves, plays the replies, builds hints from the
// solution and grades the attempt; this file draws it.
import { renderBoard } from "../shared/board.mjs";

const $ = (id) => document.getElementById(id);
let api = null;            // { py, refreshLearner, drafts }
let queue = [], current = null, st = null, selected = null, busy = false, marks = { squares: [], last: [] };

export function initDrills(a) {
  api = a;
  $("drill-hint").onclick = () => act("drill_hint");
  $("drill-show").onclick = () => act("drill_show");
  $("drill-next").onclick = () => next();
  render();
}

export async function refreshDrills() {
  if (!api) return;
  let q;
  try { q = await api.py("drill_queue", api.drafts()); } catch (err) { status("Could not load drills: " + err.message); return; }
  queue = q.cards;
  renderQueue();
  if (!current || (st && st.done)) {
    if (queue.length) start(queue[0]);
    else { current = null; st = null; $("drill-card").hidden = true; render(); status(emptyText()); }
  }
}

function emptyText() {
  return "No drills right now. Positions where you went wrong in a game come here after the review.";
}

const status = (t) => { $("drill-status").textContent = t; };

function sourceText(c) {
  if (c.source.puzzle_id) return `Puzzle ${c.source.puzzle_id}${c.source.rating ? ` · rated ${c.source.rating}` : ""}`;
  if (c.source.ply != null) return `From your game, move ${Math.floor(c.source.ply / 2) + 1}`;
  return "From your game";
}

function renderQueue() {
  const ol = $("drill-queue");
  ol.innerHTML = "";
  if (!queue.length) {
    const li = document.createElement("li"); li.className = "muted"; li.textContent = emptyText(); ol.append(li);
    return;
  }
  for (const c of queue) {
    const li = document.createElement("li");
    if (current && c.card_id === current.card_id) li.className = "cur";
    const b = document.createElement("button");
    b.className = "link";
    b.textContent = sourceText(c);
    b.onclick = () => start(c);
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = c.source.puzzle_id ? "puzzle" : c.is_new ? "new" : "review";
    li.append(b, " ", tag);
    if (c.concept_titles && c.concept_titles.length) {
      const t = document.createElement("div"); t.className = "muted"; t.textContent = c.concept_titles.join(", "); li.append(t);
    }
    ol.append(li);
  }
}

async function start(c) {
  current = c; selected = null; marks = { squares: [], last: [] };
  $("drill-feedback").innerHTML = "";
  $("drill-card").hidden = false;
  $("drill-title").textContent = `Find the best move for ${c.side === "white" ? "White" : "Black"}`;
  $("drill-source").textContent = sourceText(c) + (c.concept_titles && c.concept_titles.length ? ` · ${c.concept_titles.join(", ")}` : "");
  renderQueue();
  busy = true; buttons();
  try { st = await api.py("drill_start", c.card_id, api.drafts()); } catch (err) { status("Error: " + err.message); busy = false; return; }
  busy = false;
  status(st.player_moves > 1 ? `${st.player_moves} moves to find.` : "One move to find.");
  render(); buttons();
}

function say(text, cls) {
  const li = document.createElement("li");
  if (cls) li.className = cls;
  li.textContent = text;
  $("drill-feedback").prepend(li);
}

async function act(method, ...args) {
  if (!st || st.done || busy) return;
  busy = true; buttons();
  let s;
  try { s = await api.py(method, ...args); } catch (err) { status("Error: " + err.message); busy = false; buttons(); return; }
  busy = false;
  const prevPlayed = st.played.length;
  st = s;
  marks = { squares: [], last: [] };
  const newSans = s.played.slice(prevPlayed);
  if (s.result === "correct" || s.result === "alternative") {
    say(`✓ ${newSans[0]}` + (s.reply_san ? ` — reply ${s.reply_san}` : "") +
        (s.result === "alternative" ? " (the engine's choice too)" : ""), "ok");
  } else if (s.result === "wrong") {
    say(s.done ? "✗ Not this one." : `✗ Not this one. Tries left: ${s.tries_left}.`, "bad");
  } else if (s.result === "illegal") {
    say("That move isn't legal here.", "bad");
  }
  if (s.hint) {
    const h = s.hint;
    if (h.level === 1) say(`Hint: a ${h.piece} move.`);
    if (h.level === 2) { say(`Hint: the ${h.piece} on ${h.square}.`); marks.squares = [h.square]; }
    if (h.text) say(h.text + (api.drafts() ? "  (unreviewed draft)" : ""), "draft");
    if (h.level === 3 && h.move) marks.last = [h.move.slice(0, 2), h.move.slice(2, 4)];
  }
  if (s.done) {
    if (s.solved) status("Solved.");
    else status(`Solution: ${(s.solution_san || []).join(" ")}`);
    const g = s.graded;
    if (g) {
      const days = Math.max(0, Math.round((new Date(g.due) - Date.now()) / 864e5));
      say(`Graded ${g.grade}. Next review ${days === 0 ? "later today" : days === 1 ? "tomorrow" : `in ${days} days`}.`, "meta");
    }
    api.refreshLearner();
  } else if (s.result === "correct") {
    status(s.moves_left > 1 ? `${s.moves_left} moves left.` : "One more move.");
  }
  render(); buttons();
}

async function next() {
  await refreshDrills();
  const i = queue.findIndex((c) => !current || c.card_id !== current.card_id);
  if (i >= 0) start(queue[i]);
}

function buttons() {
  const active = !!st && !st.done && !busy;
  $("drill-hint").disabled = !active;
  $("drill-show").disabled = !active;
  $("drill-next").disabled = !st || !st.done || busy;
}

function render() {
  const fen = st ? st.fen : "8/8/8/8/8/8/8/8 w - - 0 1";
  const legal = st && !st.done ? st.legal : [];
  renderBoard($("drill-board"), {
    fen, flip: current ? current.side === "black" : false, highlight: marks.squares, last: marks.last,
    selected, targets: selected ? legal.filter((m) => m.startsWith(selected)).map((m) => m.slice(2, 4)) : [],
    onSquare,
  });
}

function onSquare(sq) {
  if (!st || st.done || busy) return;
  const legal = st.legal;
  if (selected && legal.some((m) => m.startsWith(selected + sq))) {
    const choices = legal.filter((m) => m.startsWith(selected + sq));
    const uci = choices.find((m) => m.endsWith("q")) || choices[0];
    selected = null;
    act("drill_move", uci);
    return;
  }
  selected = selected !== sq && legal.some((m) => m.startsWith(sq)) ? sq : null;
  render();
}
