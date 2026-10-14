"""Export Maia-2 (rapid) to fp16 ONNX for the browser build (ADR 0002).

    python tools/export_maia_onnx.py [--out models/maia2_rapid.fp16.onnx]

Needs the `webbuild` extra (torch via maia2, onnx, onnxconverter-common). fp32 export is ~93 MB;
fp16 is ~47 MB and agreed with fp32 on the top move in 120/120 test positions (max probability
difference 0.001). int8 was rejected: it changed the top move.
"""
from __future__ import annotations

import argparse
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "models" / "maia2_rapid.fp16.onnx"))
    ap.add_argument("--weights", default=str(ROOT / "models" / "maia2"))
    args = ap.parse_args()

    import chess
    import onnx
    import torch
    from maia2 import model
    from onnxconverter_common import float16

    from chesscoach.sparring import maia_features as mf

    m = model.from_pretrained(type="rapid", device="cpu", save_root=args.weights).eval()
    b = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3")
    x = torch.tensor(mf.planes(b), dtype=torch.float32).reshape(1, 18, 8, 8)
    ex = (x, torch.tensor([mf.elo_category(1500)]), torch.tensor([mf.elo_category(1500)]))
    fp32 = Path(args.out).with_suffix(".fp32.tmp.onnx")
    fp32.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(m, ex, str(fp32), input_names=["board", "elo_self", "elo_oppo"],
                      output_names=["policy", "aux", "value"], opset_version=17, dynamo=False)
    onnx.save(float16.convert_float_to_float16(onnx.load(str(fp32)), keep_io_types=True), args.out)
    os.remove(fp32)
    print(f"wrote {args.out} ({os.path.getsize(args.out) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
