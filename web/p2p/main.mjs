// Peer-to-peer chess page (ADR 0003). Bundled by tools/build_web.py into p2p/p2p.js.
// The game is one Automerge document whose URL is the page's hash; game.mjs derives the position.
import {
  Repo, WebSocketClientAdapter, BroadcastChannelNetworkAdapter, IndexedDBStorageAdapter,
  initializeWasm, isValidAutomergeUrl,
} from "@automerge/vanillajs/slim";
import * as G from "./game.mjs";
import * as R from "./review.mjs";

const RELAY = "wss://sync.automerge.org";
const HEARTBEAT_MS = 4000, ONLINE_MS = 11000;
const GLYPH = { k: "♚", q: "♛", r: "♜", b: "♝", n: "♞", p: "♟" };

const $ = (id) => document.getElementById(id);
const setStatus = (msg) => { $("status").textContent = msg; };

// ------------------------------------------------------------------ identity (per browser)
function stored(key, make) {
  try {
    let v = localStorage.getItem(key);
    if (v == null && make) { v = make(); localStorage.setItem(key, v); }
    return v;
  } catch { return make ? make() : null; }
}
function store(key, v) { try { localStorage.setItem(key, v); } catch { /* private mode */ } }

const me = stored("p2pchess.player", () => crypto.randomUUID());
const savedName = stored("p2pchess.name") || "";
$("name").value = $("join-name").value = savedName;
const nameFrom = (input) => {
  const n = input.value.trim().slice(0, 24);
  store("p2pchess.name", n);
  return n || "Anonymous";
};

// ------------------------------------------------------------------ repo
await initializeWasm(fetch(new URL("automerge.wasm", import.meta.url)));
const repo = new Repo({
  network: [new WebSocketClientAdapter(RELAY), new BroadcastChannelNetworkAdapter()],
  storage: new IndexedDBStorageAdapter("p2p-chess"),
});

function updateNet() {
  const relay = repo.peers.some((p) => String(p).startsWith("storage-server"));
  $("net").textContent = relay ? "Connected to the sync relay." : "Not connected to the sync relay (retrying)…";
  $("net").className = relay ? "ok" : "warn";
}
repo.networkSubsystem.on("peer", updateNet);
repo.networkSubsystem.on("peer-disconnected", updateNet);
setTimeout(updateNet, 4000);

// ------------------------------------------------------------------ game state
let handle = null, cleanup = () => {};
let doc = null, game = null, selected = null, flipped = null;
let viewPly = null, review = null, analysing = false;   // viewPly: null = live position
const lastSeen = new Map();

function resetAnalysis() {
  viewPly = null; review = null;
  $("analysis").hidden = true;
}

function mySeat() { return doc ? G.seatOf(doc, me) : null; }

function change(fn, ...args) {
  if (!handle) return;
  let ok = false;
  handle.change((d) => { ok = fn(d, me, ...args); });
  return ok;
}

async function openGame(url) {
  cleanup();
  handle = null; doc = null; game = null; selected = null; flipped = null;
  resetAnalysis();
  $("lobby").hidden = true;
  $("game").hidden = true;
  render();
  setStatus("Looking for the game…");
  let h;
  try {
    h = await repo.find(url);
  } catch {
    setStatus("Could not find this game. Check the link, or ask your opponent to keep their page open.");
    return;
  }
  if (location.hash.slice(1) !== url) return; // navigated away while loading
  handle = h;
  const onChange = () => { doc = handle.doc(); update(); };
  const onEphemeral = ({ message }) => {
    if (message && message.t === "hb" && typeof message.id === "string") { lastSeen.set(message.id, Date.now()); renderPlayers(); }
  };
  const beat = () => handle.broadcast({ t: "hb", id: me });
  handle.on("change", onChange);
  handle.on("ephemeral-message", onEphemeral);
  const timers = [setInterval(beat, HEARTBEAT_MS), setInterval(renderPlayers, HEARTBEAT_MS)];
  beat();
  cleanup = () => {
    h.off("change", onChange);
    h.off("ephemeral-message", onEphemeral);
    timers.forEach(clearInterval);
  };
  $("game").hidden = false;
  $("link").value = location.href;
  onChange();
}

function showLobby() {
  cleanup();
  handle = null; doc = null; game = null; flipped = null;
  resetAnalysis();
  $("game").hidden = true;
  $("lobby").hidden = false;
  render();
  setStatus("Create a game, then send the link to your opponent.");
}

function route() {
  const url = decodeURIComponent(location.hash.slice(1));
  if (isValidAutomergeUrl(url)) openGame(url);
  else showLobby();
}

// ------------------------------------------------------------------ rendering
function update() {
  if (!doc || doc.v !== 1) { setStatus("This link is not a chess game."); return; }
  game = G.derive(doc);
  if (selected && !game.legal.some((m) => m.startsWith(selected))) selected = null;
  render();
  renderPlayers();
  renderMoves();
  renderStatus();
  renderButtons();
  renderAnalysis();
}

function parseFen(fen) {
  const board = {};
  fen.split(" ")[0].split("/").forEach((row, i) => {
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
  const viewing = game && viewPly !== null;
  const fen = viewing ? game.fens[viewPly] : game ? game.fen : "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
  const pieces = parseFen(fen);
  const flip = flipped ?? mySeat() === "black";
  const myTurn = game && game.turn === mySeat();
  const targets = selected && myTurn ? game.legal.filter((m) => m.startsWith(selected)).map((m) => m.slice(2, 4)) : [];
  const lastUci = viewing ? (viewPly > 0 ? game.moves[viewPly - 1].uci : null) : game && game.lastMove;
  const last = lastUci ? [lastUci.slice(0, 2), lastUci.slice(2, 4)] : [];
  const kingInCheck = !viewing && game && game.inCheck ? (game.turn === "white" ? "K" : "k") : null;
  for (let r = 0; r < 8; r++) {
    for (let c = 0; c < 8; c++) {
      const file = "abcdefgh"[flip ? 7 - c : c], rank = flip ? r + 1 : 8 - r, sq = file + rank;
      const d = document.createElement("div");
      d.className = "sq " + ((r + c) % 2 ? "d" : "l");
      d.dataset.sq = sq;
      if (last.includes(sq)) d.classList.add("last");
      if (sq === selected) d.classList.add("sel");
      if (targets.includes(sq)) d.classList.add("target");
      const p = pieces[sq];
      if (p) {
        if (p === kingInCheck) d.classList.add("check");
        const s = document.createElement("span");
        s.className = "pc " + (p === p.toUpperCase() ? "w" : "b");
        s.textContent = GLYPH[p.toLowerCase()];
        d.appendChild(s);
      }
      if (c === 0) { const k = document.createElement("span"); k.className = "coord"; k.textContent = rank; d.appendChild(k); }
      if (r === 7) { const k = document.createElement("span"); k.className = "coord file"; k.textContent = file; d.appendChild(k); }
      d.onclick = () => onSquare(sq);
      el.appendChild(d);
    }
  }
}

function online(id) { return id === me || Date.now() - (lastSeen.get(id) || 0) < ONLINE_MS; }

function renderPlayers() {
  if (!doc) return;
  const seat = mySeat();
  for (const color of ["white", "black"]) {
    const li = $("seat-" + color);
    li.innerHTML = "";
    const id = doc[color];
    const dot = document.createElement("span");
    dot.className = "dot" + (id && online(id) ? " on" : "");
    dot.title = id ? (online(id) ? "online" : "offline") : "empty";
    const piece = document.createElement("span");
    piece.className = "pc " + (color === "white" ? "w" : "b");
    piece.textContent = GLYPH.k;
    const label = document.createElement("span");
    label.textContent = id ? (doc.names[id] || "Anonymous") + (id === me ? " (you)" : "") : "Open seat";
    if (!id) label.className = "muted";
    li.append(piece, label, dot);
    if (game && !game.result && game.turn === color && doc.white && doc.black) li.classList.add("turn");
    else li.classList.remove("turn");
  }
  const open = !seat && !(game && game.result) && (doc.white ? (doc.black ? null : "black") : "white");
  $("join").hidden = !open;
  if (open) $("join-btn").textContent = `Play as ${open}`;
  $("join-btn").dataset.color = open || "";
}

function renderMoves() {
  const ol = $("moves");
  ol.innerHTML = "";
  const browsable = !!game.result;
  const current = viewPly ?? game.moves.length;
  const moveSpan = (i) => {
    const s = document.createElement("span");
    s.className = "mv";
    const r = review && review.plies[i];
    s.textContent = game.moves[i].san + (r ? R.CLASS_SYMBOL[r.move_class] || "" : "");
    if (r && R.CLASS_SYMBOL[r.move_class]) s.classList.add(r.move_class);
    if (browsable) {
      s.classList.add("go");
      if (current === i + 1) s.classList.add("cur");
      s.onclick = () => goTo(i + 1);
    }
    return s;
  };
  for (let i = 0; i < game.moves.length; i += 2) {
    const li = document.createElement("li");
    li.append(moveSpan(i));
    if (game.moves[i + 1]) li.append(moveSpan(i + 1));
    ol.appendChild(li);
  }
  if (game.result) {
    const li = document.createElement("li");
    li.className = "result";
    li.textContent = game.result.score;
    ol.appendChild(li);
  }
  if (viewPly === null) ol.scrollTop = ol.scrollHeight;
}

function renderStatus() {
  const seat = mySeat();
  if (game.result) {
    const { score, reason } = game.result;
    const won = seat && ((score === "1-0" && seat === "white") || (score === "0-1" && seat === "black"));
    const lost = seat && ((score === "0-1" && seat === "white") || (score === "1-0" && seat === "black"));
    setStatus(`${score} · ${reason}${won ? " · you win" : lost ? " · you lose" : ""}`);
    return;
  }
  if (!doc.white || !doc.black) {
    setStatus(seat ? "Waiting for an opponent. Send them the link below." : "A seat is open. Join to play.");
    return;
  }
  const side = game.turn === "white" ? "White" : "Black";
  let msg = game.turn === seat ? "Your move" : seat ? `Waiting for ${side.toLowerCase()}` : `${side} to move`;
  if (game.inCheck) msg += " · check";
  if (game.drawOffer && game.drawOffer !== seat) msg += seat ? " · your opponent offers a draw" : ` · ${game.drawOffer} offers a draw`;
  else if (game.drawOffer) msg += " · draw offered";
  setStatus(msg);
}

function renderButtons() {
  const seat = mySeat();
  const playing = seat && !game.result && doc.white && doc.black;
  const incoming = playing && game.drawOffer === G.otherColor(seat);
  $("draw").disabled = !playing || game.drawOffer === seat;
  $("draw").textContent = incoming ? "Accept draw" : game.drawOffer === seat ? "Draw offered" : "Offer draw";
  $("draw").classList.toggle("primary", !!incoming);
  $("resign").disabled = !playing;
  $("rematch").hidden = !(seat && game.result);
  $("rematch").textContent = doc.rematch ? "Join rematch" : "Rematch";
  $("rematch").classList.toggle("primary", !!doc.rematch);
}

// ------------------------------------------------------------------ post-game analysis
// The review is the Python WebApp.review() (docs/06 §4) run in the browser through runtime.js:
// Pyodide + Stockfish WASM, loaded only when asked for, and only for finished games.
let runtime = null;

function goTo(ply) {
  if (!game || !game.result) return;
  const n = game.moves.length;
  ply = Math.max(0, Math.min(n, ply));
  viewPly = ply === n ? null : ply;
  selected = null;
  render();
  renderMoves();
  renderAnalysis();
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src; s.onload = resolve; s.onerror = () => reject(new Error("could not load " + src));
    document.head.appendChild(s);
  });
}

function cachedReview(drafts) {
  try {
    const c = JSON.parse(localStorage.getItem(R.cacheKey(handle.url, drafts)) || "null");
    return c && c.moves === game.moves.map((m) => m.uci).join(" ") ? c.review : null;
  } catch { return null; }
}

async function runAnalysis() {
  if (analysing || !game || !game.result) return;
  const drafts = $("an-drafts").checked;
  const cached = cachedReview(drafts);
  if (cached) { review = cached; update(); return; }
  if (!self.crossOriginIsolated) {
    showProgress("Analysis needs cross-origin isolation, which this browser did not enable. Reload the page and try again.");
    return;
  }
  analysing = true;
  $("an-run").disabled = true;
  const ucis = game.moves.map((m) => m.uci);
  const fen4 = (f) => f.split(" ").slice(0, 4).join(" ");
  const plyOf = new Map(game.fens.map((f, i) => [fen4(f), i]));
  let furthest = 0;
  const onEngine = (req) => {
    const i = plyOf.get(fen4(req.fen));
    // Position i is the one before move i + 1.
    if (i !== undefined && i > furthest) { furthest = i; showProgress(`Analysing move ${Math.min(i + 1, ucis.length)} of ${ucis.length}…`); }
  };
  try {
    if (!runtime) {
      showProgress("Loading the analysis engine…");
      await loadScript("../runtime.js");
      runtime = ChessCoachRuntime.start({ base: "../", onProgress: showProgress, onEngine: (r) => runtime.onEngine(r) });
    }
    runtime.onEngine = onEngine;
    await runtime.ready;
    showProgress(`Analysing move 1 of ${ucis.length}…`);
    const url = handle.url, moves = ucis.join(" ");
    const r = await runtime.call("review", JSON.stringify(ucis), 1200, drafts);
    try { localStorage.setItem(R.cacheKey(url, drafts), JSON.stringify({ moves, review: r })); } catch { /* full or private */ }
    if (handle && handle.url === url && game.moves.map((m) => m.uci).join(" ") === moves) review = r;
    $("an-progress").hidden = true;
  } catch (err) {
    showProgress("Analysis failed: " + err.message);
  } finally {
    analysing = false;
    $("an-run").disabled = false;
    update();
  }
}

function showProgress(msg) {
  $("an-progress").hidden = !msg;
  $("an-progress").textContent = msg || "";
}

const SVG = "http://www.w3.org/2000/svg";
function svgEl(name, attrs) {
  const e = document.createElementNS(SVG, name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
}

function renderGraph() {
  const g = $("an-graph"), W = 400, H = 100;
  g.innerHTML = "";
  const pts = R.graphPoints(review, W, H);
  const line = pts.map((p) => p.join(",")).join(" ");
  g.append(svgEl("rect", { class: "g-bg", x: 0, y: 0, width: W, height: H }));
  g.append(svgEl("polygon", { class: "g-white", points: `0,${H} ${line} ${W},${H}` }));
  g.append(svgEl("line", { class: "g-mid", x1: 0, y1: H / 2, x2: W, y2: H / 2 }));
  g.append(svgEl("polyline", { class: "g-line", points: line }));
  review.plies.forEach((p, i) => {
    if (p.move_class === "mistake" || p.move_class === "blunder") {
      const [x, y] = pts[i + 1];
      // A zero-length round-capped line: a dot that the stretched viewBox does not distort.
      g.append(svgEl("line", { class: "g-dot " + p.move_class, x1: x, y1: y, x2: x, y2: y + 0.01 }));
    }
  });
  const cur = viewPly ?? review.plies.length;
  const x = pts[cur][0];
  g.append(svgEl("line", { class: "g-cur", x1: x, y1: 0, x2: x, y2: H }));
}

function renderAnalysis() {
  const done = !!(game && game.result);
  $("analysis").hidden = !done;
  if (!done) return;
  if (!review) review = cachedReview($("an-drafts").checked);
  if (review && review.plies.length !== game.moves.length) review = null;
  $("an-start").hidden = !!review;
  $("an-result").hidden = !review;
  if (!review) return;

  const acc = $("an-acc");
  acc.innerHTML = "";
  for (const c of ["white", "black"]) {
    const side = review.sides[c];
    const row = document.createElement("div");
    row.className = "acc-row";
    const who = document.createElement("span");
    who.className = "who";
    who.textContent = `${c === "white" ? "White" : "Black"} · ${(doc[c] && doc.names[doc[c]]) || "Anonymous"}`;
    const num = document.createElement("strong");
    num.textContent = side.accuracy == null ? "–" : `${Math.round(side.accuracy)}%`;
    num.title = "Accuracy (Lichess formula, from win-probability loss)";
    const counts = document.createElement("span");
    counts.className = "counts";
    counts.textContent = R.BAD.map((k) => R.plural(side.counts[k], k)).join(" · ");
    row.append(who, num, counts);
    acc.append(row);
  }

  renderGraph();

  const detail = $("an-detail");
  detail.innerHTML = "";
  const cur = viewPly ?? review.plies.length;
  if (cur === 0) {
    detail.textContent = "Starting position.";
  } else {
    const f = R.plyFacts(review, cur - 1);
    const head = document.createElement("div");
    head.className = "d-head";
    const lab = document.createElement("strong");
    lab.textContent = f.label;
    const cls = document.createElement("span");
    cls.className = "tag cls " + f.moveClass;
    cls.textContent = f.moveClass;
    head.append(lab, cls);
    const ch = document.createElement("div");
    ch.textContent = `${f.mover === "white" ? "White" : "Black"}'s winning chances: ${f.chances}`;
    detail.append(head, ch);
    if (f.best) {
      const b = document.createElement("div");
      b.textContent = `Engine's best: ${f.best.san}. Line: ${f.best.line}`;
      detail.append(b);
    }
    const m = R.moments(review).find((x) => x.ply === cur - 1 && x.summary);
    if (m) {
      const t = document.createElement("div");
      t.className = "draft";
      t.textContent = m.summary;
      const d = document.createElement("span");
      d.className = "tag";
      d.textContent = "unreviewed draft";
      t.prepend(d, " ");
      detail.append(t);
    }
  }
  $("an-first").disabled = $("an-prev").disabled = cur === 0;
  $("an-next").disabled = $("an-last").disabled = cur === review.plies.length;

  const ol = $("an-moments");
  ol.innerHTML = "";
  const ms = R.moments(review);
  for (const m of ms) {
    const li = document.createElement("li");
    const a = document.createElement("button");
    a.className = "link";
    const f = R.plyFacts(review, m.ply);
    a.textContent = `${f.label} (${m.color}, ${m.move_class})`;
    a.onclick = () => goTo(m.ply + 1);
    li.append(a);
    if (m.summary) { const s = document.createElement("div"); s.className = "draft"; s.textContent = m.summary; li.append(s); }
    else if (f.best) { const s = document.createElement("div"); s.className = "muted"; s.textContent = `Best was ${f.best.san}.`; li.append(s); }
    ol.append(li);
  }
  if (!ms.length) { const li = document.createElement("li"); li.className = "muted"; li.textContent = "No inaccuracies, mistakes or blunders."; ol.append(li); }

  $("an-meta").textContent = `${review.engine}, depth ${review.depth}. Its evaluations differ slightly from full ` +
    "Stockfish, so treat close calls with care. The analysis stays in this browser; your opponent runs their own.";
}

$("an-run").onclick = runAnalysis;
$("an-drafts").onchange = () => { review = null; update(); };
$("an-first").onclick = () => goTo(0);
$("an-prev").onclick = () => goTo((viewPly ?? game.moves.length) - 1);
$("an-next").onclick = () => goTo((viewPly ?? game.moves.length) + 1);
$("an-last").onclick = () => goTo(game.moves.length);
$("an-graph").onclick = (e) => {
  if (!review) return;
  const r = e.currentTarget.getBoundingClientRect();
  goTo(R.plyAtX(review, (e.clientX - r.left) / r.width * 400, 400));
};
document.addEventListener("keydown", (e) => {
  if (!game || !game.result || e.target.closest("input, select, textarea")) return;
  if (e.key === "ArrowLeft") { goTo((viewPly ?? game.moves.length) - 1); e.preventDefault(); }
  else if (e.key === "ArrowRight") { goTo((viewPly ?? game.moves.length) + 1); e.preventDefault(); }
});

// ------------------------------------------------------------------ input
async function onSquare(sq) {
  if (viewPly !== null) return;
  if (!game || game.turn !== mySeat() || !doc.white || !doc.black) return;
  if (selected && game.legal.some((m) => m.startsWith(selected + sq))) {
    const choices = game.legal.filter((m) => m.startsWith(selected + sq));
    const uci = choices.length > 1 ? await choosePromotion(choices) : choices[0];
    selected = null;
    if (uci) change(G.playMove, uci); else render();
    return;
  }
  selected = selected !== sq && game.legal.some((m) => m.startsWith(sq)) ? sq : null;
  render();
}

function choosePromotion(choices) {
  return new Promise((resolve) => {
    const dlg = $("promo"), box = dlg.querySelector(".promo");
    box.innerHTML = "";
    const color = mySeat() === "white" ? "w" : "b";
    for (const p of ["q", "r", "b", "n"]) {
      const uci = choices.find((m) => m.endsWith(p));
      if (!uci) continue;
      const b = document.createElement("button");
      b.className = "pc " + color;
      b.textContent = GLYPH[p];
      b.ariaLabel = { q: "Queen", r: "Rook", b: "Bishop", n: "Knight" }[p];
      b.onclick = () => { dlg.close(); resolve(uci); };
      box.appendChild(b);
    }
    dlg.onclose = () => resolve(null);
    dlg.showModal();
  });
}

$("lobby").addEventListener("submit", (e) => {
  e.preventDefault();
  let color = $("color").value;
  if (color === "random") color = Math.random() < 0.5 ? "white" : "black";
  const h = repo.create(G.newGameDoc({ [color]: me, names: { [me]: nameFrom($("name")) } }));
  location.hash = h.url;
});

$("join-btn").onclick = () => {
  const color = $("join-btn").dataset.color;
  if (color) change(G.claimSeat, color, nameFrom($("join-name")));
};

$("draw").onclick = () => {
  if (game.drawOffer === G.otherColor(mySeat())) change(G.acceptDraw);
  else change(G.offerDraw);
};

$("resign").onclick = () => {
  if (confirm("Resign this game?")) change(G.resign);
};

$("flip").onclick = () => { flipped = !(flipped ?? mySeat() === "black"); render(); };

$("rematch").onclick = () => {
  if (!doc.rematch) {
    const r = repo.create(G.rematchDoc(doc));
    handle.change((d) => { if (!d.rematch) d.rematch = r.url; });
  }
  location.hash = handle.doc().rematch;
};

async function copy(text, btn) {
  const was = btn.textContent;
  try { await navigator.clipboard.writeText(text); btn.textContent = "Copied"; }
  catch { btn.textContent = "Copy failed"; }
  setTimeout(() => { btn.textContent = was; }, 1500);
}
$("copy").onclick = () => copy(location.href, $("copy"));
$("link").onfocus = () => $("link").select();
$("pgn").onclick = () => copy(G.pgn(doc, game), $("pgn"));

window.addEventListener("hashchange", route);
route();
