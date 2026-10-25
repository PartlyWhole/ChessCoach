// Board drawing shared by the peer-to-peer page and the coach page. Pure DOM, no game logic.
export const GLYPH = { k: "♚", q: "♛", r: "♜", b: "♝", n: "♞", p: "♟" };
export const START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

export function parseFen(fen) {
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

// opts: { fen, flip, last: [from, to], selected, targets: [sq], check: "K"|"k"|null,
//         highlight: [sq], onSquare(sq) }
export function renderBoard(el, opts) {
  const { fen, flip = false, last = [], selected = null, targets = [], check = null, highlight = [], onSquare } = opts;
  el.innerHTML = "";
  const pieces = parseFen(fen);
  for (let r = 0; r < 8; r++) {
    for (let c = 0; c < 8; c++) {
      const file = "abcdefgh"[flip ? 7 - c : c], rank = flip ? r + 1 : 8 - r, sq = file + rank;
      const d = document.createElement("div");
      d.className = "sq " + ((r + c) % 2 ? "d" : "l");
      d.dataset.sq = sq;
      if (last.includes(sq)) d.classList.add("last");
      if (highlight.includes(sq)) d.classList.add("hl");
      if (sq === selected) d.classList.add("sel");
      if (targets.includes(sq)) d.classList.add("target");
      const p = pieces[sq];
      if (p) {
        if (p === check) d.classList.add("check");
        const s = document.createElement("span");
        s.className = "pc " + (p === p.toUpperCase() ? "w" : "b");
        s.textContent = GLYPH[p.toLowerCase()];
        d.appendChild(s);
      }
      if (c === 0) { const k = document.createElement("span"); k.className = "coord"; k.textContent = rank; d.appendChild(k); }
      if (r === 7) { const k = document.createElement("span"); k.className = "coord file"; k.textContent = file; d.appendChild(k); }
      if (onSquare) d.onclick = () => onSquare(sq);
      el.appendChild(d);
    }
  }
}

// Strip above/below the board: name, the pieces `color` has taken, and its material lead.
export function renderCaptureStrip(el, { color, name, taken, lead }) {
  el.innerHTML = "";
  const who = document.createElement("span");
  who.className = "who";
  who.textContent = name;
  const pcs = document.createElement("span");
  pcs.className = "pcs";
  let prev = null;
  for (const p of taken) {
    const g = document.createElement("span");
    g.className = "pc " + (color === "white" ? "b" : "w") + (p === prev ? " same" : "");
    g.textContent = GLYPH[p];
    pcs.append(g);
    prev = p;
  }
  el.append(who, pcs);
  if (lead > 0) {
    const b = document.createElement("span");
    b.className = "lead";
    b.textContent = "+" + lead;
    el.append(b);
  }
  el.setAttribute("aria-label", `${color} has taken ${taken.length ? taken.join(", ") : "nothing"}` +
    (lead > 0 ? `, ahead by ${lead}` : ""));
}
