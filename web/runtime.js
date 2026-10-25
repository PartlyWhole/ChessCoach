// Shared browser runtime (ADR 0002): Stockfish and Maia workers, the Pyodide worker running the
// ChessCoach Python, and the synchronous RPC broker between them. Used by the main page (app.js)
// and the peer-to-peer page's post-game review (p2p/, ADR 0003).
//
//   const rt = ChessCoachRuntime.start({ base: "../", onProgress, onEngine });
//   await rt.ready;  const json = await rt.call("review", ...args);
//
// Needs cross-origin isolation (SharedArrayBuffer); coi-serviceworker provides it on GitHub Pages.
"use strict";

(() => {
  // ---------------------------------------------------------------- Stockfish (UCI over a worker)
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

  // ---------------------------------------------------------------- start
  function start({ base = "./", onProgress = () => {}, onEngine = () => {}, preloadMaia = false } = {}) {
    if (!self.crossOriginIsolated) throw new Error("cross-origin isolation is not enabled");
    const url = (p) => new URL(p, new URL(base, location.href)).href;

    // Maia worker: created on first use (the review never needs it; the model is ~47 MB).
    let maia = null;
    const maiaPending = new Map();
    let maiaSeq = 0;
    const maiaWorker = () => {
      if (maia) return maia;
      maia = new Worker(url("maia-worker.js"));
      maia.onmessage = (e) => {
        if (e.data.type === "progress") { if (e.data.msg) onProgress(e.data.msg); return; }
        const p = maiaPending.get(e.data.id); maiaPending.delete(e.data.id);
        if (e.data.error) p.reject(new Error(e.data.error)); else p.resolve({ logits: e.data.logits });
      };
      return maia;
    };
    if (preloadMaia) maiaWorker();
    const maiaRun = (req) => new Promise((resolve, reject) => {
      const id = ++maiaSeq; maiaPending.set(id, { resolve, reject }); maiaWorker().postMessage({ id, req });
    });

    const engine = new Stockfish(url("engine/stockfish-19-lite-single.js"));
    const sab = new SharedArrayBuffer(16 + (4 << 20));
    const ctrl = new Int32Array(sab, 0, 4);
    const shared = new Uint8Array(sab, 16);
    const enc = new TextEncoder();
    const py = new Worker(url("py-worker.js"));
    const calls = new Map();
    let callSeq = 0;

    function answer(text, status) {
      const bytes = enc.encode(text);
      shared.set(bytes);
      ctrl[1] = bytes.length; ctrl[2] = status;
      Atomics.store(ctrl, 0, 1);
      Atomics.notify(ctrl, 0);
    }

    let readyResolve, readyReject;
    const ready = new Promise((res, rej) => { readyResolve = res; readyReject = rej; });

    py.onmessage = async (e) => {
      const m = e.data;
      if (m.type === "progress") onProgress(m.msg);
      else if (m.type === "ready") readyResolve({ persistent: !!m.persistent });
      else if (m.type === "fatal") readyReject(new Error(m.error));
      else if (m.type === "rpc") {
        try {
          const req = JSON.parse(m.payload);
          if (m.kind === "engine") onEngine(req);
          const res = m.kind === "engine" ? await engine.analyse(req) : await maiaRun(req);
          answer(JSON.stringify(res), 0);
        } catch (err) { answer(String(err), 1); }
      } else if (m.type === "result") {
        const p = calls.get(m.id); calls.delete(m.id);
        if (m.error) p.reject(new Error(m.error)); else p.resolve(JSON.parse(m.json));
      }
    };
    py.postMessage({ type: "init", sab });

    const call = (method, ...args) => new Promise((resolve, reject) => {
      const id = ++callSeq; calls.set(id, { resolve, reject }); py.postMessage({ type: "call", id, method, args });
    });
    return { ready, call };
  }

  self.ChessCoachRuntime = { start };
})();
