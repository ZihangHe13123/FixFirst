import csv
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import bugsinpy_case  # noqa: E402
import heldout  # noqa: E402


def test_pytest_summary_line_drops_the_timing():
    output = "collected 3 items\n\n==== 2 failed, 14 errors in 3.21s (0:00:03) ====\n"
    assert heldout.summary_line(output) == "2 failed, 14 errors"
    assert heldout.summary_line("Traceback ...\nImportError: No module named 'imp'\n") == (
        "ImportError: No module named 'imp'"
    )
    first, second = {"exit_code": 2, "summary": "1 warning, 2 errors"}, {"exit_code": 2, "summary": "2 errors"}
    assert heldout.outcome(first) == heldout.outcome(second)


def test_home_folders_are_written_as_home():
    home = Path.home()
    text = f"{home / 'p' / 'x.py'}:1 and pkg @ {(home / 'p').as_uri()}"
    assert heldout.redact(text) == f"{Path('<home>') / 'p' / 'x.py'}:1 and pkg @ file://<home>/p"


def test_kappa_is_one_for_full_agreement_and_undefined_for_a_single_label():
    assert heldout.kappa(["a", "b", "a"], ["a", "b", "a"]) == 1
    assert heldout.kappa(["a", "a"], ["a", "a"]) is None
    # 3 of 4 agree; chance agreement 0.5 -> kappa 0.5
    assert heldout.kappa(["a", "a", "b", "b"], ["a", "b", "b", "b"]) == 0.5


def write_labels(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "root_cause", "first_step"])
        writer.writeheader()
        writer.writerows(rows)


def test_labels_are_compared_and_scored(tmp_path, capsys, monkeypatch):
    labels = tmp_path / "labels.csv"
    write_labels(labels, [
        {"id": "one", "root_cause": "missing_dependency", "first_step": "Install six"},
        {"id": "two", "root_cause": "healthy", "first_step": "Nothing"},
    ])
    review = tmp_path / "review.csv"
    write_labels(review, [
        {"id": "one", "root_cause": "missing_dependency", "first_step": "Install the declared deps"},
        {"id": "two", "root_cause": "code_defect", "first_step": "Fix the test"},
    ])
    monkeypatch.setattr(sys, "argv", ["heldout.py", "agree", str(labels), str(review)])
    assert heldout.main() == 0
    report = capsys.readouterr().out
    assert "Same root_cause: 1 of 2" in report and "two **differs**" in report

    step = {"title": "Install six", "cause": "Missing third-party dependency", "possible": None,
            "suspected": False, "rules": ["D20"], "command": "pip install six"}
    results = tmp_path / "results.json"
    results.write_text(json.dumps([
        {"id": "one", "headline": "1 problem to fix", "steps": [step], "search": None},
        {"id": "two", "headline": "All tests pass", "steps": [], "search": None},
    ]))
    scores = tmp_path / "scores.csv"
    monkeypatch.setattr(sys, "argv", ["heldout.py", "sheet", "--labels", str(labels),
                                      "--results", str(results), "--output", str(scores)])
    assert heldout.main() == 0
    with scores.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["fixfirst_first_step"] == "Install six" and rows[0]["fixfirst_hedged"] == "no"
    assert rows[1]["fixfirst_first_step"] == "(no must-fix step)"
    rows[0]["score"], rows[1]["score"] = "Correct", "correct"
    with scores.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    monkeypatch.setattr(sys, "argv", ["heldout.py", "summary", str(scores)])
    assert heldout.main() == 0
    assert "Correct 2, Partial 0, Generic 0, Wrong 0" in capsys.readouterr().out
    # A second scorer's sheet is compared on the score column.
    rows[1]["score"] = "Wrong"
    other = tmp_path / "scores-2.csv"
    with other.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    monkeypatch.setattr(sys, "argv", ["heldout.py", "agree", str(scores), str(other), "--column", "score"])
    assert heldout.main() == 0
    assert "Same score: 1 of 2" in capsys.readouterr().out


def test_bugsinpy_test_commands_become_pytest_node_ids(tmp_path):
    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "test_utils.py").write_text("")
    script = (
        "pytest -q -s tests/test_chinese.py::test_chinese\n"
        "python3 -m pytest tqdm/tests/tests_tqdm.py::test_si_format\n"
        "tox tests/test_generate_context.py::test_decodes\n"
        "python3 -m unittest -q test.test_utils.TestUtil.test_unified_timestamps\n"
    )
    assert bugsinpy_case.test_nodes(script, tmp_path) == [
        "tests/test_chinese.py::test_chinese",
        "tqdm/tests/tests_tqdm.py::test_si_format",
        "tests/test_generate_context.py::test_decodes",
        "test/test_utils.py::TestUtil::test_unified_timestamps",
    ]


def test_label_check_lists_what_is_missing(tmp_path, capsys, monkeypatch):
    (tmp_path / "projects.toml").write_text(
        '[[project]]\nid = "one"\nrepo = "o/one"\nref = "1"\npython = "3.12"\ninstall = ["."]\n'
        '[[project]]\nid = "two"\nrepo = "o/two"\nref = "1"\npython = "3.12"\ninstall = ["."]\n'
    )
    (tmp_path / "pytest").mkdir()
    runs = [{"exit_code": 1, "seconds": 1, "summary": "1 failed"}] * 2
    (tmp_path / "pytest" / "index.json").write_text(json.dumps({"one": {"same_every_run": True, "runs": runs}}))
    (tmp_path / "environments").mkdir()
    (tmp_path / "environments" / "one.txt").write_text("# Python 3.12\n")
    labels = tmp_path / "labels.csv"
    with labels.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", *heldout.REQUIRED])
        writer.writeheader()
        writer.writerow({"id": "one", "pytest_shows": "1 failed", "root_cause": "code_defect",
                         "first_step": "Fix f()", "checked_by_trying": "Twin: fixed f(), 1 passed",
                         "labelled_by": "A", "labelled_on": "2026-10-01"})
    monkeypatch.setattr(sys, "argv", ["heldout.py", "check", "--manifest", str(tmp_path / "projects.toml"),
                                      "--labels", str(labels)])
    assert heldout.main() == 1
    report = capsys.readouterr().out
    assert "code_defect 1" in report and "two: no label" in report and "one:" not in report
