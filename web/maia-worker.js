// Maia-2 (fp16 ONNX export of the MIT-licensed rapid model) on onnxruntime-web — ADR 0002.
// Input planes, Elo categories and the legal-move indices come from Python (maia_features.py);
// we return the policy logits for those indices only.
importScripts("ort/ort.wasm.min.js");

const base = new URL("./", self.location).href;
ort.env.wasm.wasmPaths = base + "ort/";
ort.env.wasm.numThreads = 1;
let session = null;

async function load() {
  self.postMessage({ type: "progress", msg: "Loading the human-like bot (Maia-2, ~47 MB, cached after the first visit)…" });
  session = await ort.InferenceSession.create(base + "maia/maia2_rapid.fp16.onnx", { executionProviders: ["wasm"] });
  self.postMessage({ type: "progress", msg: "" });
}

self.onmessage = async (e) => {
  const { id, req } = e.data;
  try {
    if (!session) await load();
    const feeds = {
      board: new ort.Tensor("float32", Float32Array.from(req.planes), [1, 18, 8, 8]),
      elo_self: new ort.Tensor("int64", BigInt64Array.from([BigInt(req.elo_self)]), [1]),
      elo_oppo: new ort.Tensor("int64", BigInt64Array.from([BigInt(req.elo_oppo)]), [1]),
    };
    const out = await session.run(feeds);
    const policy = out.policy.data;
    self.postMessage({ id, logits: req.legal.map((i) => policy[i]) });
  } catch (err) {
    self.postMessage({ id, error: String(err) });
  }
};
