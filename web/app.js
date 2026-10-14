// Page: board UI + the RPC broker between the Python worker and the engine/Maia workers (ADR 0002).
"use strict";

const $ = (id) => document.getElementById(id);
const statusEl = $("status");
const setStatus = (msg) => { statusEl.textContent = msg; };

// ------------------------------------------------------------------ Stockfish (UCI over a worker)
class Stockfish {
  constructor(url) {
    this.w = new Worker(url);
    this.listeners = [];
    this.w.onmessage = (e) => {
      const line = typeof e.data === "string" ? e.data : String(e.data);
      for (const l of [...this.listeners]) l(line);
    };
    this.queue = Promise.resolve();
    this.ready = this.cmdUntil(["uci"], (l) => l === "uciok").then(() => this.cmdUntil(["isready"], (l) => l === "readyok"));
  }
  cmdUntil(cmds, done) {
    return new Promise((resolve) => {
      const seen = [];
      const fn = (line) => { seen.push(line); if (done(line)) { this.listeners = this.listeners.filter((x) => x !== fn); resolve(seen); } };
      this.listeners.push(fn);
      for (const c of cmds) this.w.postMessage(c);
    });
  }
  // One search at a time (Python is blocked while it waits anyway).
  analyse({ fen, depth, multipv, movetime_ms }) {
    const run = async () => {
      await this.ready;
      const go = "go depth " + depth + (movetime_ms ? " movetime " + movetime_ms : "");
      const out = await this.cmdUntil(
        ["setoption name MultiPV value " + multipv, "position fen " + fen, go],
        (l) => l.startsWith("bestmove"));
      return parseInfo(out, multipv);
    };
    this.queue = this.queue.then(run, run);
    return this.queue;
  }
}

// Latest complete "info" per multipv index. Scores are side-to-move POV (Python converts).
function parseInfo(lines, multipv) {
  const best = {};
  for (const l of lines) {
    if (!l.startsWith("info ") || !l.includes(" pv ") || l.includes("bound")) continue;
    const t = l.split(" ");
    const get = (k) => { const i = t.indexOf(k); return i >= 0 ? t[i + 1] : null; };
    const k = Number(get("multipv") || 1);
    const si = t.indexOf("score");
    const rec = { depth: Number(get("depth")), pv: t.slice(t.indexOf("pv") + 1), cp: null, mate: null };
    if (t[si + 1] === "cp") rec.cp = Number(t[si + 2]); else rec.mate = Number(t[si + 2]);
    if (!best[k] || rec.depth >= best[k].depth) best[k] = rec;
  }
  const res = [];
  for (let k = 1; k <= multipv; k++) if (best[k]) res.push(best[k]);
  return { lines: res };
}

// ------------------------------------------------------------------ Maia worker
const maia = new Worker("maia-worker.js");
const maiaPending = new Map();
let maiaSeq = 0;
maia.onmessage = (e) => {
  if (e.data.type === "progress") { if (e.data.msg) setStatus(e.data.msg); return; }
  const p = maiaPending.get(e.data.id); maiaPending.delete(e.data.id);
  if (e.data.error) p.reject(new Error(e.data.error)); else p.resolve({ logits: e.data.logits });
};
const maiaRun = (req) => new Promise((resolve, reject) => {
  const id = ++maiaSeq; maiaPending.set(id, { resolve, reject }); maia.postMessage({ id, req });
});

// ------------------------------------------------------------------ Python worker + broker
const engine = new Stockfish("engine/stockfish-19-lite-single.js");
const sab = new SharedArrayBuffer(16 + (4 << 20));
const ctrl = new Int32Array(sab, 0, 4);
const shared = new Uint8Array(sab, 16);
const enc = new TextEncoder();
const py = new Worker("py-worker.js");
const calls = new Map();
let callSeq = 0;

function answer(text, status) {
  const bytes = enc.encode(text);
  shared.set(bytes);
  ctrl[1] = bytes.length; ctrl[2] = status;
  Atomics.store(ctrl, 0, 1);
  Atomics.notify(ctrl, 0);
}

py.onmessage = async (e) => {
  const m = e.data;
  if (m.type === "progress") setStatus(m.msg);
  else if (m.type === "ready") { setStatus("Ready. Choose your settings and press Start."); $("start").disabled = false; }
  else if (m.type === "fatal") setStatus("Failed to start: " + m.error);
  else if (m.type === "rpc") {
    try {
      const req = JSON.parse(m.payload);
      const res = m.kind === "engine" ? await engine.analyse(req) : await maiaRun(req);
      answer(JSON.stringify(res), 0);
    } catch (err) { answer(String(err), 1); }
  } else if (m.type === "result") {
    const p = calls.get(m.id); calls.delete(m.id);
    if (m.error) p.reject(new Error(m.error)); else p.resolve(JSON.parse(m.json));
  }
};
const callPy = (method, ...args) => new Promise((resolve, reject) => {
  const id = ++callSeq; calls.set(id, { resolve, reject }); py.postMessage({ type: "call", id, method, args });
});

if (!self.crossOriginIsolated) {
  setStatus("Enabling cross-origin isolation (the page reloads once)…");
} else {
  py.postMessage({ type: "init", sab });
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
