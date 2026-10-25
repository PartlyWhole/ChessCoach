"""Assemble the static site for GitHub Pages (ADR 0002) into _site/.

    (cd web && npm ci)                       # pinned runtime assets
    python tools/export_maia_onnx.py         # once: models/maia2_rapid.fp16.onnx
    python tools/build_web.py

Layout: index.html, app.js, runtime.js, workers, coi-serviceworker, pyodide/ (core), wheels/
(python-chess and fsrs built from source + PyYAML and typing-extensions from the Pyodide CDN,
sha256-checked), app.zip (chesscoach + concepts
+ templates), engine/ (Stockfish 19 lite single-threaded), ort/ (onnxruntime-web), maia/ (model),
p2p/ (peer-to-peer play over Automerge, ADR 0003: page + esbuild bundle + automerge.wasm).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
NM = WEB / "node_modules"
OUT = ROOT / "_site"
MODEL = ROOT / "models" / "maia2_rapid.fp16.onnx"
PYODIDE_CDN = "https://cdn.jsdelivr.net/pyodide/v{v}/full/"


def copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def build_wheel(dist: str, dest: Path) -> str:
    """Pure-Python wheel built from the sdist of the version installed here."""
    from importlib.metadata import version
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-binary", ":all:", "-q",
                        f"{dist}=={version(dist)}", "-w", tmp], check=True)
        whl = next(Path(tmp).glob("*.whl"))
        copy(whl, dest / whl.name)
        return whl.name


def fetch_pyodide_wheel(name: str, dest: Path) -> str:
    lock = json.loads((NM / "pyodide" / "pyodide-lock.json").read_text())
    version = json.loads((NM / "pyodide" / "package.json").read_text())["version"]
    pkg = lock["packages"][name]
    target = dest / pkg["file_name"]
    if not target.exists():
        with urllib.request.urlopen(PYODIDE_CDN.format(v=version) + pkg["file_name"]) as r:
            data = r.read()
        if hashlib.sha256(data).hexdigest() != pkg["sha256"]:
            raise SystemExit(f"sha256 mismatch for {pkg['file_name']}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return pkg["file_name"]


OPENING_TREE = ROOT / "models" / "opening_tree.json"     # tools/build_openings.py


def app_zip(dest: Path) -> None:
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for base, pattern in (("chesscoach", "**/*.py"), ("concepts", "**/*.yaml"), ("templates", "**/*.yaml")):
            for p in sorted((ROOT / base).glob(pattern)):
                if "__pycache__" not in p.parts:
                    z.write(p, p.relative_to(ROOT))
        z.write(OPENING_TREE, "data/opening_tree.json")


def bundle(entry: Path, out: Path) -> None:
    """esbuild an ES module page script; bundled packages' license notices (chess.js is
    BSD-2-Clause, which requires them) go to <name>.LICENSES.txt next to it."""
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(NM / ".bin" / "esbuild"), str(entry), "--bundle", "--format=esm", "--target=es2022",
                    "--minify", "--legal-comments=external", f"--outfile={out}", "--log-level=warning"], check=True)
    legal = out.with_name(out.name + ".LEGAL.txt")
    if legal.exists():
        legal.rename(out.with_name(out.stem + ".LICENSES.txt"))


def build_p2p(dest: Path) -> None:
    copy(WEB / "p2p" / "index.html", dest / "index.html")
    copy(NM / "@automerge" / "automerge" / "dist" / "automerge.wasm", dest / "automerge.wasm")
    bundle(WEB / "p2p" / "main.mjs", dest / "p2p.js")
    (dest / "p2p.LICENSES.txt").rename(dest / "LICENSES.txt")


def main() -> None:
    if not NM.exists():
        raise SystemExit("run `npm ci` in web/ first")
    if not MODEL.exists():
        raise SystemExit(f"missing {MODEL}: run tools/export_maia_onnx.py")
    if not OPENING_TREE.exists():
        raise SystemExit(f"missing {OPENING_TREE}: run tools/build_openings.py")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    for f in ("index.html", "runtime.js", "py-worker.js", "maia-worker.js", "style.css"):
        copy(WEB / f, OUT / f)
    copy(WEB / "shared" / "ui.css", OUT / "shared" / "ui.css")
    copy(WEB / "coach" / "coach.css", OUT / "coach" / "coach.css")
    bundle(WEB / "coach" / "main.mjs", OUT / "coach.js")
    copy(NM / "coi-serviceworker" / "coi-serviceworker.min.js", OUT / "coi-serviceworker.min.js")
    for f in ("pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"):
        copy(NM / "pyodide" / f, OUT / "pyodide" / f)
    for f in ("stockfish-19-lite-single.js", "stockfish-19-lite-single.wasm"):
        copy(NM / "stockfish" / "bin" / f, OUT / "engine" / f)
    for f in ("ort.wasm.min.js", "ort-wasm-simd-threaded.mjs", "ort-wasm-simd-threaded.wasm"):
        copy(NM / "onnxruntime-web" / "dist" / f, OUT / "ort" / f)
    copy(MODEL, OUT / "maia" / MODEL.name)
    # fsrs (+ typing-extensions): chesscoach.learner.review imports the SRS module (p2p review, ADR 0003).
    # sqlite3 is unvendored from Pyodide's stdlib: the learner store needs it (ADR 0004).
    wheels = [fetch_pyodide_wheel("pyyaml", OUT / "wheels"), fetch_pyodide_wheel("typing-extensions", OUT / "wheels"),
              fetch_pyodide_wheel("sqlite3", OUT / "wheels"),
              build_wheel("chess", OUT / "wheels"), build_wheel("fsrs", OUT / "wheels")]
    (OUT / "wheels" / "index.json").write_text(json.dumps(wheels))
    app_zip(OUT / "app.zip")
    build_p2p(OUT / "p2p")
    for f in ("LICENSE", "THIRD_PARTY.md"):
        copy(ROOT / f, OUT / f)
    (OUT / ".nojekyll").write_text("")
    total = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print(f"built {OUT} ({total / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
