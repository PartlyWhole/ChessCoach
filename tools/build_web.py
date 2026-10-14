"""Assemble the static site for GitHub Pages (ADR 0002) into _site/.

    (cd web && npm ci)                       # pinned runtime assets
    python tools/export_maia_onnx.py         # once: models/maia2_rapid.fp16.onnx
    python tools/build_web.py

Layout: index.html, app.js, workers, coi-serviceworker, pyodide/ (core), wheels/ (python-chess
built from source + PyYAML from the Pyodide CDN, sha256-checked), app.zip (chesscoach + concepts
+ templates), engine/ (Stockfish 19 lite single-threaded), ort/ (onnxruntime-web), maia/ (model).
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


def build_chess_wheel(dest: Path) -> str:
    import chess
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-binary", ":all:", "-q",
                        f"chess=={chess.__version__}", "-w", tmp], check=True)
        whl = next(Path(tmp).glob("chess-*.whl"))
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


def app_zip(dest: Path) -> None:
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for base, pattern in (("chesscoach", "**/*.py"), ("concepts", "**/*.yaml"), ("templates", "**/*.yaml")):
            for p in sorted((ROOT / base).glob(pattern)):
                if "__pycache__" not in p.parts:
                    z.write(p, p.relative_to(ROOT))


def main() -> None:
    if not NM.exists():
        raise SystemExit("run `npm ci` in web/ first")
    if not MODEL.exists():
        raise SystemExit(f"missing {MODEL}: run tools/export_maia_onnx.py")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    for f in ("index.html", "app.js", "py-worker.js", "maia-worker.js", "style.css"):
        copy(WEB / f, OUT / f)
    copy(NM / "coi-serviceworker" / "coi-serviceworker.min.js", OUT / "coi-serviceworker.min.js")
    for f in ("pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"):
        copy(NM / "pyodide" / f, OUT / "pyodide" / f)
    for f in ("stockfish-19-lite-single.js", "stockfish-19-lite-single.wasm"):
        copy(NM / "stockfish" / "bin" / f, OUT / "engine" / f)
    for f in ("ort.wasm.min.js", "ort-wasm-simd-threaded.mjs", "ort-wasm-simd-threaded.wasm"):
        copy(NM / "onnxruntime-web" / "dist" / f, OUT / "ort" / f)
    copy(MODEL, OUT / "maia" / MODEL.name)
    wheels = [fetch_pyodide_wheel("pyyaml", OUT / "wheels"), build_chess_wheel(OUT / "wheels")]
    (OUT / "wheels" / "index.json").write_text(json.dumps(wheels))
    app_zip(OUT / "app.zip")
    for f in ("LICENSE", "THIRD_PARTY.md"):
        copy(ROOT / f, OUT / f)
    (OUT / ".nojekyll").write_text("")
    total = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print(f"built {OUT} ({total / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
