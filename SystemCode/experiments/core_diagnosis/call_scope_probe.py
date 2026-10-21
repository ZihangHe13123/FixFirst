"""Small executable before/after probe for removed-keyword ownership."""

import argparse
import json
from pathlib import Path
import sys
import tempfile

from fixfirst.diagnosis_cases import CHECKS
from fixfirst.service import create_session, scan
from fixfirst.workspace import build_view

CASES = {
    "numpy_unrelated_squared": "import numpy\ndef convert():\n    return numpy.array([1], squared=False)\n",
    "sklearn_unrelated_squared": "from sklearn.preprocessing import StandardScaler\n"
        "def convert():\n    return StandardScaler(squared=False)\n",
    "sklearn_removed_alias": "from sklearn.metrics import mean_squared_error as error\n"
        "def convert():\n    return error([1], [2], squared=False)\n",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = []
    with tempfile.TemporaryDirectory(prefix="fixfirst-call-scope-") as folder:
        for name, source in CASES.items():
            root = Path(folder) / name
            root.mkdir()
            (root / "app.py").write_text(source)
            (root / "test_app.py").write_text("from app import convert\ndef test_convert():\n    convert()\n")
            session = create_session(root, sys.executable, goal="pass_tests")
            session.use_classifier = False
            scan(session, CHECKS)
            issues = [i for i in session.issues if i.tool == "pytest_run" and i.status == "open"]
            results.append({"case": name, "source": source,
                            "diagnoses": [{"label": i.diagnosis, "rule": i.diagnosis_rule,
                                           "source": i.diagnosis_source} for i in issues],
                            "first_step": (build_view(session)["steps"] or [{}])[0].get("title")})
    with args.output.open("x") as stream:
        stream.write(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(results, ensure_ascii=False))


if __name__ == "__main__":
    main()
