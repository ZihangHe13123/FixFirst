#!/usr/bin/env python3
"""B9: make a regenerated grouping dataset publishable, the way the stored one was. No model.

    publish.py RAW_DATASET OUT_DIR CHECKOUT

CHECKOUT is the FixFirst checkout the data were generated in (its .venv is the interpreter). Its path is
written as <checkout>. Then every saved session (baseline.json, input.json, restored.json) goes through the
product's own public_data(): project folder -> <project>, interpreter -> <python>, home folders -> <home>.
The disposable runtime/ environments of the dependency cases are not copied (the stored dataset has none).
"""
import json
import sys
from pathlib import Path

from fixfirst.models import Session
from fixfirst.report import public_data

raw, out, checkout = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), str(Path(sys.argv[3]).resolve())
if out.exists():
    raise SystemExit("output folder exists")
NEUTRAL = "/fixfirst-checkout"  # a path none of the product's redaction patterns touch
count = {"sessions": 0, "copied": 0}
for path in sorted(p for p in raw.rglob("*") if p.is_file()):
    relative = path.relative_to(raw)
    if "runtime" in relative.parts:
        continue
    text = path.read_text(encoding="utf-8")
    for private in (checkout, checkout.replace("/private/tmp/", "/tmp/")):
        text = text.replace(private, NEUTRAL)
    if path.name in ("baseline.json", "input.json", "restored.json"):
        text = json.dumps(public_data(Session.model_validate_json(text)), ensure_ascii=False, indent=2) + "\n"
        count["sessions"] += 1
    else:
        count["copied"] += 1
    target = out / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text.replace(NEUTRAL, "<checkout>"), encoding="utf-8")
print(count)
