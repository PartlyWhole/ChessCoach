// Pyodide worker: runs the unchanged ChessCoach Python (L1–L5) — ADR 0002.
// Python calls the engine and Maia synchronously through rpc_sync(): we post the request to the
// page and block on a SharedArrayBuffer until the page writes the answer.
importScripts("pyodide/pyodide.js");

let py = null;
let app = null;
let ctrl = null;   // Int32Array [flag, length, status, _]
let data = null;   // Uint8Array response buffer
const dec = new TextDecoder();

self.rpc_sync = (kind, payload) => {
  Atomics.store(ctrl, 0, 0);
  self.postMessage({ type: "rpc", kind, payload });
  Atomics.wait(ctrl, 0, 0);
  const text = dec.decode(data.slice(0, ctrl[1]));   // slice: copy out of shared memory
  if (ctrl[2] !== 0) throw new Error(text);
  return text;
};

function progress(msg) { self.postMessage({ type: "progress", msg }); }

async function boot() {
  const base = new URL("./", self.location).href;
  progress("Loading Python runtime…");
  py = await loadPyodide({ indexURL: base + "pyodide/" });
  progress("Loading chess libraries…");
  const wheels = await (await fetch(base + "wheels/index.json")).json();
  await py.loadPackage(wheels.map((w) => base + "wheels/" + w));
  progress("Loading coach…");
  const zip = await (await fetch(base + "app.zip")).arrayBuffer();
  py.unpackArchive(zip, "zip", { extractDir: "/app" });
  // The learner store (ADR 0004): SQLite on a folder that IndexedDB keeps between visits. Private
  // windows and blocked storage fall back to memory; the page is told which it got.
  progress("Opening your saved progress…");
  let storePath = ":memory:";
  try {
    py.FS.mkdirTree("/data");
    py.FS.mount(py.FS.filesystems.IDBFS, {}, "/data");
    await syncfs(true);
    persistent = true;
    storePath = "/data/learner.db";
  } catch (err) {
    persistent = false;
  }
  py.globals.set("store_path", storePath);
  py.runPython(`
import sys
sys.path.insert(0, "/app")
from js import rpc_sync
from chesscoach.web.app import WebApp
app = WebApp(rpc_sync, store_path=store_path)
`);
  app = py.globals.get("app");
}

let persistent = false, syncing = null, syncAgain = false;
function syncfs(populate) {
  return new Promise((resolve, reject) => py.FS.syncfs(populate, (e) => (e ? reject(e) : resolve())));
}
// Write the database back to IndexedDB after a call; calls that land during a sync queue one more.
function persist() {
  if (!persistent) return;
  if (syncing) { syncAgain = true; return; }
  syncing = syncfs(false).catch(() => {}).finally(() => {
    syncing = null;
    if (syncAgain) { syncAgain = false; persist(); }
  });
}

self.onmessage = async (e) => {
  const m = e.data;
  if (m.type === "init") {
    ctrl = new Int32Array(m.sab, 0, 4);
    data = new Uint8Array(m.sab, 16);
    try {
      await boot();
      self.postMessage({ type: "ready", persistent });
    } catch (err) {
      self.postMessage({ type: "fatal", error: String(err) });
    }
  } else if (m.type === "call") {
    try {
      const out = app[m.method](...m.args);
      self.postMessage({ type: "result", id: m.id, json: out });
      persist();
    } catch (err) {
      self.postMessage({ type: "result", id: m.id, error: String(err) });
    }
  }
};
