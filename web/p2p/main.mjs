// Peer-to-peer chess page (ADR 0003). Bundled by tools/build_web.py into p2p/p2p.js.
// The game is one Automerge document whose URL is the page's hash; game.mjs derives the position.
import {
  Repo, WebSocketClientAdapter, BroadcastChannelNetworkAdapter, IndexedDBStorageAdapter,
  initializeWasm, isValidAutomergeUrl,
} from "@automerge/vanillajs/slim";
import * as G from "./game.mjs";

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
const lastSeen = new Map();

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
  const fen = game ? game.fen : "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
  const pieces = parseFen(fen);
  const flip = flipped ?? mySeat() === "black";
  const myTurn = game && game.turn === mySeat();
  const targets = selected && myTurn ? game.legal.filter((m) => m.startsWith(selected)).map((m) => m.slice(2, 4)) : [];
  const last = game && game.lastMove ? [game.lastMove.slice(0, 2), game.lastMove.slice(2, 4)] : [];
  const kingInCheck = game && game.inCheck ? (game.turn === "white" ? "K" : "k") : null;
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
  for (let i = 0; i < game.moves.length; i += 2) {
    const li = document.createElement("li");
    li.textContent = game.moves[i].san + (game.moves[i + 1] ? "  " + game.moves[i + 1].san : "");
    ol.appendChild(li);
  }
  if (game.result) {
    const li = document.createElement("li");
    li.className = "result";
    li.textContent = game.result.score;
    ol.appendChild(li);
  }
  ol.scrollTop = ol.scrollHeight;
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

// ------------------------------------------------------------------ input
async function onSquare(sq) {
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
