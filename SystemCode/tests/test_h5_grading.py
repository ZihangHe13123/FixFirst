"""H5 static protection and independent full-suite observations; no model or real task data."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "agent_baseline"))
import compare_arms as ca  # noqa: E402
import pytest_policy as pp  # noqa: E402
import real_cases as rc  # noqa: E402


def write(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


FORMATS = [("pytest.ini", "[pytest]\npythonpath = src\n"), (".pytest.ini", "[pytest]\npythonpath = src\n"),
           ("tox.ini", "[pytest]\npythonpath = src\n"), ("setup.cfg", "[tool:pytest]\npythonpath = src\n"),
           ("pyproject.toml", '[tool.pytest.ini_options]\npythonpath = ["src"]\n'),
           ("pyproject.toml", '[tool.pytest]\npythonpath = ["src"]\n'),
           ("pytest.toml", '[pytest]\npythonpath = ["src"]\n'), (".pytest.toml", '[pytest]\npythonpath = ["src"]\n')]


@pytest.mark.parametrize("name,text", FORMATS)
def test_allow_one_new_location_and_changes_to_allowed_options(tmp_path, name, text):
    empty = pp.snapshot(tmp_path)
    path = write(tmp_path, name, text)
    baseline = pp.snapshot(tmp_path)
    assert not pp.violations(empty, baseline)
    path.write_text(text.replace("src", "source"), encoding="utf-8")
    assert not pp.violations(baseline, pp.snapshot(tmp_path))
    path.unlink()
    assert pp.violations(baseline, pp.snapshot(tmp_path))["configuration_carriers"]["category"] == "configuration_carriers"


@pytest.mark.parametrize("name,text", FORMATS)
def test_every_other_option_is_protected_in_every_format(tmp_path, name, text):
    baseline = pp.snapshot(tmp_path)
    value = '"INFO"' if name.endswith(".toml") else "INFO"
    write(tmp_path, name, text + f"log_level = {value}\n")
    changes = pp.violations(baseline, pp.snapshot(tmp_path))
    assert any(c["category"] == "other_pytest_option" for c in changes.values())


@pytest.mark.parametrize("file", ["tests/helper.txt", "test/helpers.py", "testing/data.bin", "pkg/test_x.py",
                                 "pkg/x_test.py", "conftest.py", "nested/conftest.py"])
def test_test_content_including_new_files_stays_protected(tmp_path, file):
    before = pp.snapshot(tmp_path)
    write(tmp_path, file, "one\n")
    assert {v["category"] for v in pp.violations(before, pp.snapshot(tmp_path)).values()} == {"test_content"}


@pytest.mark.parametrize("key", ["strict_xfail", "filterwarnings", "addopts", "future_pytest_flag", "asyncio_mode"])
def test_file_shadowing_cannot_hide_any_existing_option(tmp_path, key):
    write(tmp_path, "pyproject.toml", f'[tool.pytest.ini_options]\n{key} = "true"\n')
    baseline = pp.snapshot(tmp_path)
    write(tmp_path, "pytest.ini", "[pytest]\npythonpath = src\n")
    assert "configuration_carriers" in pp.violations(baseline, pp.snapshot(tmp_path))


def test_no_config_start_cannot_acquire_two_locations(tmp_path):
    baseline = pp.snapshot(tmp_path)
    write(tmp_path, "pytest.ini", "[pytest]\npythonpath = src\n")
    write(tmp_path, "tox.ini", "[pytest]\nDJANGO_SETTINGS_MODULE = config\n")
    assert "configuration_carriers" in pp.violations(baseline, pp.snapshot(tmp_path))


def test_both_pyproject_tables_protected_even_when_one_masks_the_other(tmp_path):
    path = write(tmp_path, "pyproject.toml", '[tool.pytest]\nlog_level = "INFO"\n'
                                          '[tool.pytest.ini_options]\nlog_level = "WARNING"\n')
    baseline = pp.snapshot(tmp_path)
    path.write_text(path.read_text().replace('"INFO"', '"DEBUG"'), encoding="utf-8")
    assert pp.violations(baseline, pp.snapshot(tmp_path))


def test_case_is_not_folded_and_multiline_semantics_are_not_erased(tmp_path):
    baseline = pp.snapshot(tmp_path)
    path = write(tmp_path, "pytest.ini", "[pytest]\nPythonPath = src\n")
    assert pp.violations(baseline, pp.snapshot(tmp_path))
    path.write_text("[pytest]\nfilterwarnings =\n    error:one two\n    ignore:three\n", encoding="utf-8")
    baseline = pp.snapshot(tmp_path)
    path.write_text("[pytest]\nfilterwarnings = error:one two ignore:three\n", encoding="utf-8")
    assert pp.violations(baseline, pp.snapshot(tmp_path))


def test_addopts_spacing_only_is_allowed_but_quoted_contents_are_not(tmp_path):
    path = write(tmp_path, "pytest.ini", "[pytest]\naddopts = -q   --tb=short\n")
    baseline = pp.snapshot(tmp_path)
    path.write_text("[pytest]\naddopts = -q --tb=short\n", encoding="utf-8")
    assert not pp.violations(baseline, pp.snapshot(tmp_path))
    path.write_text('[pytest]\naddopts = -q "--tb=short extra"\n', encoding="utf-8")
    assert pp.violations(baseline, pp.snapshot(tmp_path))


@pytest.mark.parametrize("kind", ["broken", "duplicate", "directory", "symlink", "fifo"])
def test_unsafe_config_is_rejected_without_blocking(tmp_path, kind):
    baseline = pp.snapshot(tmp_path)
    path = tmp_path / "pytest.ini"
    if kind == "broken":
        path.write_text("[pytest\n", encoding="utf-8")
    elif kind == "duplicate":
        path.write_text("[pytest]\npythonpath=src\npythonpath=lib\n", encoding="utf-8")
    elif kind == "directory":
        path.mkdir()
    elif kind == "symlink":
        try:
            path.symlink_to(write(tmp_path, "regular.ini", "[pytest]\npythonpath=src\n"))
        except OSError as error:
            pytest.skip(f"symlinks unavailable: {error}")
    else:
        if not hasattr(os, "mkfifo"):
            pytest.skip("no named pipes on this platform")
        os.mkfifo(path)
    state = pp.snapshot(tmp_path)
    assert state["errors"] and pp.violations(baseline, state)


def suite(tmp_path, root):
    grader = tmp_path / ("grader-" + str(len(list(tmp_path.glob("grader-*")))))
    grader.mkdir()

    def execute(argv, cwd, env, timeout):
        completed = subprocess.run(argv, cwd=cwd, env={**env, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
                                   capture_output=True, text=True, timeout=min(timeout, 30))
        return completed.returncode, completed.stdout + completed.stderr, False

    return rc.run_suite(root, Path(sys.executable).absolute(), grader, execute, grading_policy=pp.H5)


def reference(tmp_path):
    root = tmp_path / "project"
    write(root, "src/ledger.py", "VALUE=23\n")
    write(root, "test_value.py", "from ledger import VALUE\ndef test_value(): assert VALUE==23\n")
    baseline = pp.snapshot(root)
    write(root, "pytest.ini", "[pytest]\npythonpath=src\n")
    data = suite(tmp_path, root)
    data.update(h5_baseline=baseline, h5_violations={}, repair=[], key="key", commit="commit", problems=[])
    assert not rc.validate_reference(data)
    return root, data


def test_persistent_import_config_works_in_a_clean_fresh_process(tmp_path):
    root, ref = reference(tmp_path)
    result = suite(tmp_path, root)
    assert result["h5_observation"]["nodes"] == ["test_value.py::test_value"]
    assert result["h5_observation"]["outcomes"] == {"test_value.py::test_value": "passed"}
    assert result["h5_observation"]["config"] == {"file": "pytest.ini", "raw": {}, "effective": {}}
    assert rc.judge(result, ref, [])["fixed"]
    # Removing the persisted path cannot be hidden by the grader's own import path.
    (root / "pytest.ini").unlink()
    assert suite(tmp_path, root)["exit_code"] == 2


WARNING_CONFIGS = [
    ("setup.cfg", "[tool:pytest]\npythonpath=src\nfilterwarnings=error\n"),
    ("pytest.ini", "[pytest]\npythonpath=src\nfilterwarnings=error\n"),
    ("pyproject.toml", '[tool.pytest.ini_options]\npythonpath=["src"]\nfilterwarnings=["error"]\n'),
]


def warning_reference(tmp_path, name, text):
    root = tmp_path / "project"
    write(root, "src/ledger.py", "def total(amounts): return round(sum(amounts), 2)\n")
    write(root, "test_value.py", "from ledger import total\ndef test_value(): assert total([10, 13])==23\n")
    write(root, name, text)
    baseline = pp.snapshot(root)
    data = suite(tmp_path, root)
    assert data["exit_code"] == 0
    data.update(h5_baseline=baseline, h5_violations={}, repair=[])
    assert not rc.validate_reference(data)
    return root, data


@pytest.mark.parametrize("name,text", WARNING_CONFIGS)
def test_probe_does_not_turn_its_own_pytest_deprecation_into_a_project_failure(tmp_path, name, text):
    root, ref = warning_reference(tmp_path, name, text)
    observation = ref["h5_observation"]
    assert observation["complete"] and not observation["errors"]
    assert observation["config"]["effective"]["filterwarnings"] == {"registered": True, "value": ["error"]}
    assert rc.judge(suite(tmp_path, root), ref, [])["fixed"]
    assert (root / name).read_text() == text


@pytest.mark.parametrize("category", ["UserWarning", "pytest.PytestDeprecationWarning"])
@pytest.mark.parametrize("phase,code", [("collection", 2), ("call", 1)])
def test_probe_restores_warning_errors_for_project_collection_and_tests(tmp_path, category, phase, code):
    root, ref = warning_reference(tmp_path, *WARNING_CONFIGS[0])
    warning = f'warnings.warn("project warning must fail", {category})\n'
    imports = "import warnings\nimport pytest\n"
    body = "def total(amounts):\n"
    body += "    " + warning if phase == "call" else ""
    body += "    return round(sum(amounts), 2)\n"
    write(root, "src/ledger.py", imports + (warning if phase == "collection" else "") + body)
    result = suite(tmp_path, root)
    assert result["exit_code"] == code
    assert result["h5_observation"]["complete"] and not result["h5_observation"]["errors"]
    assert result["h5_observation"]["config"] == ref["h5_observation"]["config"]
    assert rc.judge(result, ref, [])["fixed"] is False


def test_project_cannot_replace_the_grader_probe_by_module_name(tmp_path):
    root, ref = reference(tmp_path)
    write(root, "_h5_grading_probe.py", 'raise RuntimeError("project probe loaded")\n')
    assert rc.judge(suite(tmp_path, root), ref, [])["fixed"]


def test_exact_nodes_cannot_be_swapped_even_with_same_junit_ids(tmp_path):
    root, ref = reference(tmp_path)
    candidate = deepcopy(ref)
    candidate["h5_observation"]["nodes"] = ["elsewhere/test_value.py::test_value"]
    candidate["h5_observation"]["outcomes"] = {"elsewhere/test_value.py::test_value": "passed"}
    verdict = rc.judge(candidate, ref, [])
    assert not verdict["fixed"] and any("collected test nodes" in r for r in verdict["reasons"])


@pytest.mark.parametrize("mutation", ["missing", "unfinished", "exit", "nodes", "duplicates", "outcomes", "config",
                                     "effective", "policy", "identity", "state", "unknown_option", "stopped"])
def test_unusable_observations_never_count_as_success(tmp_path, mutation):
    root, ref = reference(tmp_path)
    result = deepcopy(ref)
    obs = result["h5_observation"]
    if mutation == "missing":
        result.pop("h5_observation")
    elif mutation == "unfinished":
        obs["complete"] = False
    elif mutation == "exit":
        obs["exit_code"] = 1
    elif mutation == "nodes":
        obs["nodes"] = None
    elif mutation == "duplicates":
        obs["nodes"] *= 2
    elif mutation == "outcomes":
        obs["outcomes"] = {}
    elif mutation == "config":
        obs["config"] = None
    elif mutation == "effective":
        obs["config"]["effective"] = {"log_level": []}
        obs["config"]["raw"] = {"log_level": "INFO"}
    elif mutation == "policy":
        result["grading_policy"] = pp.LEGACY
    elif mutation == "identity":
        result["grading_policy_sha256"] = "0" * 64
    elif mutation == "state":
        result["h5_state"] = {"carriers": []}
    elif mutation == "stopped":
        result["h5_process_stopped"] = True
    else:
        obs["config"]["effective"] = {"log_level": {"registered": False, "value": "INFO"}}
        obs["config"]["raw"] = {"log_level": "INFO"}
    with pytest.raises(ValueError):
        rc.judge(result, ref, [])


def test_reference_repair_is_subject_to_the_same_rule_and_cache_identity(tmp_path):
    root, ref = reference(tmp_path)
    bad = deepcopy(ref)
    bad["h5_violations"] = {"other_option": {"category": "other_pytest_option"}}
    assert rc.validate_reference(bad)
    bad["h5_violations"] = {}
    bad["h5_baseline"]["carriers"] = ["tox.ini"]
    bad["h5_baseline"]["tables"] = {"tox.ini": {"pytest": {}}}
    assert rc.validate_reference(bad)
    cache = tmp_path / "cache.json"
    rc.write_json(cache, ref)
    assert rc.read_reference_cache(cache, "key", "one", pp.H5)[0] == ref
    assert rc.read_reference_cache(cache, "key", "two", pp.LEGACY)[0] is None
    old = {k: ref[k] for k in rc.REFERENCE_KEYS}
    rc.write_json(cache, old)
    assert rc.read_reference_cache(cache, "key", "three", pp.H5)[0] is None


def test_known_policy_violation_is_a_failure_even_when_observation_is_missing(tmp_path):
    root, ref = reference(tmp_path)
    result = deepcopy(ref)
    result.pop("h5_observation")
    assert rc.judge(result, ref, ["options:pytest.ini:pytest:unknown_option"])["fixed"] is False


@pytest.mark.parametrize("code", [1, 2, 3, 4, 5])
def test_pytest_loading_and_usage_failures_are_counted_as_failures(tmp_path, code):
    root, ref = reference(tmp_path)
    result = deepcopy(ref)
    result.update(exit_code=code, counts={}, outcomes={})
    result["h5_observation"] = {"schema": 1, "policy": pp.H5, "started": True, "complete": False}
    assert rc.judge(result, ref, [])["fixed"] is False
    result["h5_observation"].pop("started")
    with pytest.raises(ValueError):
        rc.judge(result, ref, [])


def test_failed_process_is_not_lost_when_junit_is_malformed(tmp_path):
    root, ref = reference(tmp_path)
    result = deepcopy(ref)
    result.update(exit_code=1, counts={}, outcomes={}, h5_junit_error="broken XML")
    result["h5_observation"]["exit_code"] = 1
    assert not rc.judge(result, ref, [])["fixed"]
    result["exit_code"] = 0
    with pytest.raises(ValueError):
        rc.judge(result, ref, [])


def test_effective_settings_and_reference_passing_outcomes_are_protected(tmp_path):
    root, ref = reference(tmp_path)
    path = write(root, "pytest.ini", "[pytest]\npythonpath=src\nlog_level=INFO\n")
    state = pp.snapshot(root)
    ref = suite(tmp_path, root)
    ref.update(h5_baseline=state, h5_violations={}, repair=[])
    assert not rc.validate_reference(ref)
    path.write_text("[pytest]\npythonpath=src\nlog_level=ERROR\n", encoding="utf-8")
    candidate = suite(tmp_path, root)
    verdict = rc.judge(candidate, ref, list(pp.violations(state, pp.snapshot(root))))
    assert not verdict["fixed"] and any("actual protected" in r for r in verdict["reasons"])
    candidate = deepcopy(ref)
    candidate["h5_observation"]["outcomes"] = {"test_value.py::test_value": "xpassed"}
    assert not rc.judge(candidate, ref, [])["fixed"]


def test_unknown_option_shadow_probe_on_pytest_9(tmp_path):
    import pytest as installed
    if int(installed.__version__.split(".")[0]) < 9:
        pytest.skip("native strict_xfail needs pytest 9")
    root = tmp_path / "project"
    write(root, "test_value.py", "import pytest\n@pytest.mark.xfail\ndef test_value(): assert True\n")
    write(root, "pyproject.toml", "[tool.pytest]\nstrict_xfail=true\n")
    baseline = pp.snapshot(root)
    original = suite(tmp_path, root)
    write(root, "pytest.ini", "[pytest]\npythonpath=src\n")
    changed = suite(tmp_path, root)
    assert original["exit_code"] == 1 and changed["exit_code"] == 0
    assert original["h5_observation"]["nodes"] == changed["h5_observation"]["nodes"]
    assert "configuration_carriers" in pp.violations(baseline, pp.snapshot(root))


def test_protocol_separates_h5_implementations_without_changing_old_ids():
    row = {"settings": {"max_turns": 20, "run_timeout": 900.0}, "harness_commit": "source", "network": "off"}
    old = {k: row["settings"].get(k) for k in ca.PROTOCOL_SETTINGS}
    old.update(call_policy="server", network="off", harness="source", uncommitted=False)
    expected = hashlib.sha256(json.dumps(old, sort_keys=True, default=str).encode()).hexdigest()[:8]
    assert ca.protocol(row) == ca.protocol({**row, "grading_policy": pp.LEGACY}) == expected
    h5 = {**row, "grading_policy": pp.H5, "grading_policy_sha256": pp.identity()}
    assert ca.protocol(h5) != expected
    assert ca.protocol(h5) != ca.protocol({**h5, "grading_policy_sha256": "0" * 64})
