// Expert review page (AGENTS rule 2): every concept's text on its test positions, editable, with
// an approve / request-changes decision per concept. Decisions stay in this browser until the
// reviewer downloads them; tools/apply_review.py writes them into the concept YAML.
import { renderBoard } from "../shared/board.mjs";

const $ = (id) => document.getElementById(id);
const setStatus = (t) => { $("status").textContent = t; };
const KEY = "chesscoach.review.decisions.v1";

let callPy = () => Promise.reject(new Error("not ready"));
let concepts = [], fallback = null, current = null, detail = null, busy = false;
let decisions = load();

function load() {
  try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch { return {}; }
}
function save() {
  try { localStorage.setItem(KEY, JSON.stringify(decisions)); } catch { /* private window */ }
  renderList(); renderExport();
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

// ------------------------------------------------------------------ list
function renderList() {
  const ul = $("list");
  ul.innerHTML = "";
  let cat = null;
  const items = [...concepts, { id: "_fallback", title: "Fallback texts", category: "fallback",
                                status: fallback ? fallback.review.status || "draft" : "draft" }];
  for (const c of items) {
    if (c.category !== cat) { cat = c.category; ul.append(el("li", "cat", cat)); }
    const li = el("li");
    const b = el("button", c.id === current ? "cur" : "", c.title);
    const dec = decisions[c.id];
    const st = el("span", "st " + (dec ? dec.decision : c.status), dec ? `${label(dec.decision)} (you)` : label(c.status));
    b.append(st);
    b.onclick = () => open(c.id);
    li.append(b);
    ul.append(li);
  }
}
const label = (s) => ({ approved: "approved", changes_requested: "changes", draft: "draft" }[s] || s);

function renderExport() {
  const n = Object.keys(decisions).length;
  $("decided").textContent = n ? `${n} decision${n === 1 ? "" : "s"} in this browser` : "";
  $("export").disabled = !n || !$("reviewer").value.trim();
}

// ------------------------------------------------------------------ detail
async function open(id, edits = null) {
  if (busy) return;
  current = id;
  renderList();
  const box = $("detail");
  if (id === "_fallback") { detail = fallback; renderFallback(); return; }
  busy = true;
  box.innerHTML = "";
  box.append(el("div", "card", "Running the test positions through the coach…"));
  setStatus(`Analysing ${id}…`);
  try {
    detail = await callPy("review_concept", id, JSON.stringify(edits || (decisions[id] && decisions[id].templates) || null));
    setStatus("");
  } catch (err) {
    setStatus("Error: " + err.message);
    busy = false;
    return;
  }
  busy = false;
  renderDetail();
}

function templateEditor(templates, original, onChange) {
  const wrap = el("div");
  for (const [role, lvs] of Object.entries(templates)) {
    const r = el("div", "tpl-role");
    r.append(el("h3", null, role));
    for (const [lv, text] of Object.entries(lvs)) {
      const row = el("div", "tpl-row");
      row.append(el("span", "lv", `L${lv}`));
      const ta = el("textarea");
      ta.value = text;
      ta.dataset.role = role; ta.dataset.lv = lv;
      const orig = original && original[role] ? original[role][lv] : text;
      ta.classList.toggle("edited", ta.value !== orig);
      ta.oninput = () => { ta.classList.toggle("edited", ta.value !== orig); onChange(); };
      row.append(ta);
      r.append(row);
    }
    wrap.append(r);
  }
  return wrap;
}

function collectEdits(root, original) {
  const edits = {};
  root.querySelectorAll("textarea[data-role]").forEach((ta) => {
    const o = original[ta.dataset.role] && original[ta.dataset.role][ta.dataset.lv];
    if (ta.value !== o) (edits[ta.dataset.role] ||= {})[ta.dataset.lv] = ta.value;
  });
  return Object.keys(edits).length ? edits : null;
}

let originals = {};      // concept id → templates as shipped (before this reviewer's edits)

function renderDetail() {
  const d = detail;
  const box = $("detail");
  box.innerHTML = "";
  if (!originals[d.id]) originals[d.id] = JSON.parse(JSON.stringify(d.templates));
  const orig = originals[d.id];
  const head = el("div", "card");
  head.append(el("h2", null, `${d.title}`),
              el("p", "note", `${d.id} · ${d.category} · bands ${d.bands.join(", ")} · shipped status: ${d.review.status || "draft"}` +
                 (d.review.by ? ` (by ${d.review.by}, ${d.review.date})` : "")));
  const rules = el("ul", "note");
  for (const r of d.rules) rules.append(el("li", null, r));
  head.append(rules, el("p", "note", `Slots this concept can fill: ${Object.keys(d.slots).join(", ") || "none"}` +
                                      " (plus move_san at level 3)."));
  box.append(head);

  const tpl = el("div", "card");
  tpl.append(el("h2", null, "Text"));
  const editor = templateEditor(d.templates, orig, () => {});
  tpl.append(editor);
  if (d.errors.length) {
    const er = el("div", "errors");
    for (const e of d.errors) er.append(el("p", null, e));
    tpl.append(er);
  }
  const check = el("button", null, "Check my edits on the positions");
  check.onclick = () => open(d.id, collectEdits(editor, orig) || {});
  tpl.append(check);
  box.append(tpl);

  const cs = el("div", "card");
  cs.append(el("h2", null, "On its test positions"),
            el("p", "note", `Computed with ${d.engine}. Automated tests check the same positions with full Stockfish 19.`));
  const grid = el("div", "cases");
  for (const c of d.cases) grid.append(renderCase(c));
  if (!d.cases.length && !d.errors.length) grid.append(el("p", "muted", "No test positions found."));
  cs.append(grid);
  box.append(cs);

  box.append(decisionCard(d.id, () => collectEdits(editor, orig)));
}

function renderCase(c) {
  const card = el("div", "case");
  const side = c.fen.split(" ")[1] === "w" ? "white" : "black";
  card.append(el("h4", null, c.id));
  const b = el("div", "board");
  renderBoard(b, { fen: c.fen, flip: side === "black",
                   highlight: c.hit ? c.hit.highlight.squares : [],
                   last: c.hit && c.hit.highlight.arrows.length ? c.hit.highlight.arrows[0] : [] });
  card.append(b);
  const exp = c.expect_present ? `expects a "${c.role}" hit` : `expects no "${c.role}" hit (near miss)`;
  card.append(el("p", "exp", `${side === "white" ? "White" : "Black"} to move${c.move_san ? `, then ${c.move_san}` : ""} · ${exp}`));
  if (!c.ok) card.append(el("p", "bad", "Not matched as expected with the browser engine; check this one with the maintainers."));
  if (c.hit) {
    const ol = el("ol");
    for (const [lv, t] of Object.entries(c.texts)) {
      const li = el("li", null, t == null ? "(this level can't be filled here)" : t);
      li.value = Number(lv) || 1;
      ol.append(li);
    }
    card.append(ol);
  }
  if (c.note) card.append(el("p", "note", c.note));
  return card;
}

function decisionCard(id, getEdits) {
  const card = el("div", "card");
  card.append(el("h2", null, "Your decision"));
  const prev = decisions[id];
  if (prev) card.append(el("p", "dec " + prev.decision, `Saved: ${label(prev.decision)}${prev.templates ? " with edits" : ""}.`));
  const row = el("div", "decision");
  const note = el("textarea");
  note.placeholder = "Note for the maintainers (required when asking for changes)";
  note.value = prev ? prev.note || "" : "";
  const approve = el("button", "primary", "Approve");
  const changes = el("button", null, "Request changes");
  const clear = el("button", null, "Clear my decision");
  approve.onclick = () => { decide(id, "approved", note.value, getEdits()); };
  changes.onclick = () => {
    if (!note.value.trim()) { note.focus(); setStatus("Add a note saying what should change."); return; }
    decide(id, "changes_requested", note.value, getEdits());
  };
  clear.onclick = () => { delete decisions[id]; save(); id === "_fallback" ? renderFallback() : renderDetail(); };
  row.append(note, approve, changes);
  if (prev) row.append(clear);
  card.append(row);
  card.append(el("p", "note", "Approving means: every sentence above is correct for every position where the coach " +
    "would say it, and suitable for the listed bands."));
  return card;
}

function decide(id, decision, note, templates) {
  decisions[id] = { decision, note: note.trim(), templates: templates || null };
  save();
  setStatus(`${id}: ${label(decision)} (saved in this browser)`);
  id === "_fallback" ? renderFallback() : renderDetail();
}

function renderFallback() {
  const d = fallback;
  const box = $("detail");
  box.innerHTML = "";
  if (!originals._fallback) originals._fallback = JSON.parse(JSON.stringify(d.templates));
  const head = el("div", "card");
  head.append(el("h2", null, d.title),
              el("p", "note", "Used when no concept explains a move. Slots are filled from the engine line: " +
                 "{best_san} / {pv_san} / {reply_san} (level 3 only), {best_from} / {reply_from} (squares)."),
              el("p", "note", `Shipped status: ${d.review.status || "draft"}`));
  box.append(head);
  const tpl = el("div", "card");
  const current = decisions._fallback && decisions._fallback.templates;
  const shown = JSON.parse(JSON.stringify(d.templates));
  if (current) for (const [r, lvs] of Object.entries(current)) Object.assign(shown[r], lvs);
  const editor = templateEditor(shown, originals._fallback, () => {});
  tpl.append(el("h2", null, "Text"), editor);
  box.append(tpl);
  box.append(decisionCard("_fallback", () => collectEdits(editor, originals._fallback)));
}

// ------------------------------------------------------------------ export
$("reviewer").value = (() => { try { return localStorage.getItem("chesscoach.review.name") || ""; } catch { return ""; } })();
$("reviewer").oninput = () => {
  try { localStorage.setItem("chesscoach.review.name", $("reviewer").value); } catch { /* ignore */ }
  renderExport();
};
$("export").onclick = () => {
  const out = { reviewer: $("reviewer").value.trim(), date: new Date().toISOString().slice(0, 10), concepts: decisions };
  const blob = new Blob([JSON.stringify(out, null, 2)], { type: "application/json" });
  const a = el("a");
  a.href = URL.createObjectURL(blob);
  a.download = `chesscoach-review-${out.date}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
};

// ------------------------------------------------------------------ boot
if (!self.crossOriginIsolated) {
  setStatus("Enabling cross-origin isolation (the page reloads once)…");
} else {
  const rt = ChessCoachRuntime.start({ base: "../", onProgress: setStatus });
  callPy = rt.call;
  rt.ready.then(async () => {
    const r = await callPy("review_concepts");
    concepts = r.concepts;
    fallback = r.fallback;
    setStatus(`${concepts.length} concepts. Pick one to review.`);
    renderList(); renderExport();
  }, (err) => setStatus("Failed to start: " + err.message));
}
