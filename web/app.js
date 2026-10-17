// Page: board UI for playing the coached bot. The Python worker and engine/Maia broker live in runtime.js (ADR 0002).
"use strict";

const $ = (id) => document.getElementById(id);
const statusEl = $("status");
const setStatus = (msg) => { statusEl.textContent = msg; };

// ------------------------------------------------------------------ runtime (runtime.js)
let callPy = () => Promise.reject(new Error("not ready"));
if (!self.crossOriginIsolated) {
  setStatus("Enabling cross-origin isolation (the page reloads once)…");
} else {
  const rt = ChessCoachRuntime.start({ onProgress: setStatus, preloadMaia: true });
  callPy = rt.call;
  rt.ready.then(() => { setStatus("Ready. Choose your settings and press Start."); $("start").disabled = false; },
                (err) => setStatus("Failed to start: " + err.message));
}

// ------------------------------------------------------------------ board UI
const GLYPH = { k: "♚", q: "♛", r: "♜", b: "♝", n: "♞", p: "♟" };
let state = null, selected = null, highlight = { squares: [], arrows: [] }, busy = false;

function parseFen(fen) {
  const rows = fen.split(" ")[0].split("/"), board = {};
  rows.forEach((row, i) => {
    let f = 0;
    for (const ch of row) {
      if (/\d/.test(ch)) { f += Number(ch); continue; }
      board["abcdefgh"[f] + (8 - i)] = ch; f++;
    }
  });
  return board;
}

function render() {
  const el = $("board");
  el.innerHTML = "";
  const view = state || { fen: "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", legal: [],
                          player_color: $("color").value, last_move: null };
  const pieces = parseFen(view.fen);
  const flip = view.player_color === "black";
  const targets = selected ? view.legal.filter((m) => m.startsWith(selected)).map((m) => m.slice(2, 4)) : [];
  const last = view.last_move ? [view.last_move.slice(0, 2), view.last_move.slice(2, 4)] : [];
  const hl = new Set([...highlight.squares, ...highlight.arrows.flat()]);
  for (let r = 0; r < 8; r++) {
    for (let c = 0; c < 8; c++) {
      const file = "abcdefgh"[flip ? 7 - c : c], rank = flip ? r + 1 : 8 - r, sq = file + rank;
      const d = document.createElement("div");
      d.className = "sq " + ((r + c) % 2 ? "d" : "l");
      if (last.includes(sq)) d.classList.add("last");
      if (hl.has(sq)) d.classList.add("hl");
      if (sq === selected) d.classList.add("sel");
      if (targets.includes(sq)) d.classList.add("target");
      const p = pieces[sq];
      if (p) {
        const s = document.createElement("span");
        s.className = "pc " + (p === p.toUpperCase() ? "w" : "b");
        s.textContent = GLYPH[p.toLowerCase()];
        d.appendChild(s);
      }
      if (c === 0) { const k = document.createElement("span"); k.className = "coord"; k.textContent = rank; d.appendChild(k); }
      d.onclick = () => onSquare(sq, pieces);
      el.appendChild(d);
    }
  }
}

async function onSquare(sq, pieces) {
  if (!state || busy || !state.legal.length) return;
  if (selected && state.legal.some((m) => m.startsWith(selected + sq))) {
    const uci = state.legal.find((m) => m === selected + sq) || selected + sq + "q";
    selected = null;
    await act("move", uci);
    return;
  }
  selected = state.legal.some((m) => m.startsWith(sq)) ? sq : null;
  render();
}

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
}

async function act(method, ...args) {
  busy = true; updateButtons();
  setStatus("Thinking…");
  try {
    const s = await callPy(method, ...args);
    highlight = { squares: [], arrows: [] };
    if (s.event) coachSay(s.event, s.assessment ? s.assessment.move + ": " + s.assessment.move_class : null);
    state = s;
    if (s.waiting_for_takeback) setStatus("Take back to try again, ask for a hint, or keep your move.");
    else if (s.game_over) setStatus("Game over: " + s.result);
    else setStatus(s.bot_san ? "Bot played " + s.bot_san + ". Your move." : "Your move.");
    if (!s.waiting_for_takeback && !s.game_over && $("mode").value === "guided" && s.legal.length) {
      const pre = await callPy("pre_move_prompt");
      if (pre.event) coachSay(pre.event, "before your move");
    }
  } catch (err) {
    setStatus("Error: " + err.message);
  }
  busy = false; updateButtons(); render();
}

function updateButtons() {
  const waiting = !!(state && state.waiting_for_takeback);
  $("hint").disabled = busy || !state || state.game_over;
  $("takeback").disabled = busy || !waiting;
  $("resume").disabled = busy || !waiting;
  $("start").disabled = busy || !self.crossOriginIsolated;
}

$("setup").onsubmit = async (e) => {
  e.preventDefault();
  $("coach").innerHTML = "";
  selected = null;
  await act("new_game", $("color").value, Number($("rating").value), $("mode").value, $("drafts").checked);
  if (state && !state.concepts_loaded) coachSay({ kind: "note", hint_level: 0, text:
    "No coaching text is approved yet, so the coach stays silent. Tick the developer preview to see the drafts." });
};
$("hint").onclick = async () => {
  const s = await callPy("hint");
  coachSay(s.event || { kind: "hint", hint_level: 0, text: "No hint available here." });
  render();
};
$("takeback").onclick = () => act("takeback");
$("resume").onclick = () => act("resume");
$("color").onchange = () => { if (!state) render(); };
render();
