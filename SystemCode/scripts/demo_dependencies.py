"""Replay one known library defect with an explicitly authored dependency declaration."""

import argparse
from pathlib import Path

from fixfirst.historical_cases import CASES, replay

parser = argparse.ArgumentParser(description="Controlled demo: declared version does not match the installed version")
parser.add_argument("--assets", default="examples/historical-regressions/assets")
parser.add_argument("--output", required=True)
args = parser.parse_args()
case = {
    **CASES[0],
    "id": "declared-version-mismatch",
    "title": "Project declaration does not match the installed version",
    "requirement": "packaging>=24.2",
    "origin": "Authored dependency-mismatch scenario using the already counted Packaging #788 defect; not an additional natural bug",
}
print(replay(Path(args.output), Path(args.assets), [case]))
