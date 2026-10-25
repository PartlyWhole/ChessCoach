"""Apply a chess expert's review decisions (exported from the /review/ page) to the concept YAML.

    python tools/apply_review.py decisions.json [--dry-run]

decisions.json:
    {"reviewer": "Name", "date": "YYYY-MM-DD",
     "concepts": {"<concept_id>": {"decision": "approved" | "changes_requested",
                                    "note": "...", "templates": {role: {level: text}} | null},
                  "_fallback": {...same...}}}

Templates are written first (if edited), then `review` is set to {status, by, date, note}; the
original `drafted_by` is kept. Every edited concept is re-validated with the registry's rules
before anything is written; on any error nothing changes. Comments and key order in the YAML are
preserved (ruamel.yaml). Only `approved` ships (AGENTS rule 2): `changes_requested` stays hidden.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DECISIONS = ("approved", "changes_requested")


def main(argv=None) -> int:
    from ruamel.yaml import YAML

    from chesscoach.concepts.registry import CONCEPT_ROOT, Registry
    from chesscoach.concepts.review_tool import check_templates, with_templates
    from chesscoach.policy.policy import FALLBACK_FILE

    ap = argparse.ArgumentParser()
    ap.add_argument("decisions")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--concepts", default=str(CONCEPT_ROOT), help="concept directory (tests use a copy)")
    ap.add_argument("--fallback", default=str(FALLBACK_FILE), help="fallback template file")
    args = ap.parse_args(argv)
    d = json.loads(Path(args.decisions).read_text())
    reviewer, date = d.get("reviewer", "").strip(), d.get("date", "").strip()
    if not reviewer or not date:
        print("decisions need a reviewer name and a date", file=sys.stderr)
        return 2
    reg = Registry.load(Path(args.concepts), allow_unreviewed=True)
    paths = {c.id: c.path for c in reg}
    paths["_fallback"] = Path(args.fallback)
    yml = YAML()
    yml.preserve_quotes = True
    yml.width = 4096
    pending, errors = [], []
    for cid, dec in d.get("concepts", {}).items():
        if cid not in paths:
            errors.append(f"{cid}: unknown concept")
            continue
        if dec.get("decision") not in DECISIONS:
            errors.append(f"{cid}: decision must be one of {DECISIONS}")
            continue
        templates = dec.get("templates")
        if templates and cid != "_fallback":
            errors += check_templates(with_templates(reg.get(cid), templates))
        pending.append((cid, dec))
    if errors:
        for e in errors:
            print("error:", e, file=sys.stderr)
        return 1
    for cid, dec in pending:
        path = Path(paths[cid])
        doc = yml.load(path.read_text())
        if dec.get("templates"):
            for role, lvs in dec["templates"].items():
                for lv, text in lvs.items():
                    doc["templates"][role][int(lv)] = text
        review = doc.get("review") or {}
        review["status"] = dec["decision"]
        review["by"] = reviewer
        review["date"] = date
        if dec.get("note"):
            review["note"] = dec["note"]
        elif "note" in review:
            del review["note"]
        doc["review"] = review
        if args.dry_run:
            print(f"would set {cid}: {dec['decision']}" + (" (templates edited)" if dec.get("templates") else ""))
            continue
        with path.open("w") as f:
            yml.dump(doc, f)
        print(f"{cid}: {dec['decision']}" + (" (templates edited)" if dec.get("templates") else ""))
    if not args.dry_run:
        Registry.load(Path(args.concepts), allow_unreviewed=True)   # the build: every concept still validates
    return 0


if __name__ == "__main__":
    sys.exit(main())
