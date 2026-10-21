import configparser
import json
import os
from pathlib import Path
import tomllib

import pytest

from fixfirst import diagnosis_cases as dc
from fixfirst import toolchain_cases as tc
from fixfirst.classification import DIAGNOSES
from fixfirst.evaluation import load_rows

DATASET = Path(__file__).resolve().parent.parent / "examples" / "toolchain-dataset"


def test_scenario_table_is_consistent():
    ids = [s.scenario_id for s in tc.TOOL_SCENARIOS]
    assert len(ids) == len(set(ids)) and len(ids) >= 20
    templates = {t.name for t in dc.TEMPLATES}
    for s in tc.TOOL_SCENARIOS:
        assert s.label in DIAGNOSES, s.scenario_id
        assert s.fault_env in tc.ENVS, s.scenario_id
        assert not s.fix_env or s.fix_env in tc.ENVS, s.scenario_id
        assert set(s.templates) <= templates, s.scenario_id
        # every case needs a fix that is run for real: another environment, a project edit or a variable
        assert s.fix_env or s.fix or s.fix_variables, s.scenario_id
        assert s.shows and s.description and s.family


def test_environments_name_real_packages_and_pythons():
    for env in tc.ENV_LIST:
        assert env.python in {"3.11", "3.12"}
        assert env.packages and all(p.split("=")[0].split(">")[0].split("<")[0] for p in env.packages)
    assert tc.HEALTHY_ENV in tc.ENVS


@pytest.mark.parametrize("filename", ["pytest.ini", "setup.cfg", "pyproject.toml"])
def test_error_filter_keeps_the_templates_own_options(tmp_path, filename):
    for index, template in enumerate(dc.TEMPLATES):
        root = tmp_path / filename / template.name
        dc.build_template(root, template)
        before = tc.ini_options(dc.Project(root, template, index))
        project = dc.Project(root, template, index)
        tc.error_filter(project, filename)
        if filename == "pytest.ini":
            parser = configparser.ConfigParser()
            parser.read(root / "pytest.ini")
            options = dict(parser["pytest"])
        elif filename == "setup.cfg":
            assert not (root / "pytest.ini").exists()
            parser = configparser.ConfigParser()
            parser.read(root / "setup.cfg")
            options = dict(parser["tool:pytest"])
        else:
            assert not (root / "pytest.ini").exists()
            data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
            assert data["project"]["name"] == template.name  # the project metadata survives
            options = {k: " ".join(v) for k, v in data["tool"]["pytest"]["ini_options"].items()}
        assert options["filterwarnings"].split() == ["error"]
        for key, value in before.items():
            assert options[key] == value


def test_pin_records_the_environments_packages(tmp_path):
    template = dc.TEMPLATES[0]
    dc.build_template(tmp_path / "t", template)
    tc.pin(dc.Project(tmp_path / "t", template, 0), "t625-py110")
    assert (tmp_path / "t" / "requirements.txt").read_text(encoding="utf-8").split() == ["pytest==6.2.5", "py==1.10.0"]


def test_projects_that_edit_the_service_still_compile(tmp_path):
    for index, template in enumerate(dc.TEMPLATES):
        for scenario in tc.TOOL_SCENARIOS:
            if scenario.templates and template.name not in scenario.templates:
                continue
            root = tmp_path / template.name / scenario.scenario_id
            dc.build_template(root, template)
            scenario.apply(dc.Project(root, template, index))
            for path in root.rglob("*.py"):
                compile(path.read_text(encoding="utf-8"), str(path), "exec")


@pytest.mark.skipif(not DATASET.exists(), reason="the recorded toolchain dataset is not installed")
def test_recorded_dataset_has_a_verified_fix_per_case_and_no_local_paths():
    manifest = json.loads((DATASET / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["suite"] == "toolchain" and manifest["cases"]
    assert all(case["fix"]["passed"] for case in manifest["cases"])
    assert {u["scenario"] for u in manifest["unparsed"]} <= {s.scenario_id for s in tc.TOOL_SCENARIOS}
    for path in DATASET.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            assert "/Users/" not in text and "/private/" not in text and "/var/folders" not in text, path


@pytest.mark.skipif(not DATASET.exists(), reason="the recorded toolchain dataset is not installed")
def test_recorded_dataset_loads_through_both_loaders():
    rows = tc.load_rows(DATASET)
    assert len(rows) >= 100
    assert {r["family"] for r in rows} == {"old_test_tool", "old_library", "setuptools", "django"}
    assert all(r["label"] in DIAGNOSES for r in rows)
    # evaluation.load_rows follows the sub-datasets too, so `fixfirst evaluate` works on the suite
    plain = load_rows(DATASET)
    assert [r["case_id"] for r in plain] == [r["case_id"] for r in rows]


@pytest.mark.skipif(not os.environ.get("FIXFIRST_BUILD_TOOLCHAIN"), reason="builds real environments; needs uv and network")
def test_build_two_scenarios_for_real(tmp_path):
    manifest = tc.build_dataset(tmp_path / "out", work=tmp_path / "work",
                                only={"tt_py_spec_t625", "dj_unset_tox"})
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert len(data["cases"]) == 10 and not data["rejected"]
    assert all(c["fix"]["passed"] for c in data["cases"])
