"""Classifier schema compatibility and contexts from actual failing programs."""

from copy import deepcopy
import hashlib
from importlib import resources
import json
from pathlib import Path
import sys

import pytest

from fixfirst.classification import default_model, load_model, predict_tree, train_tree
from fixfirst.diagnosis_cases import CHECKS
from fixfirst.evidence import FEATURE_NAMES, LEGACY_FEATURE_NAMES, observations
from fixfirst.service import create_session, scan


# Exact default shipped before the v0.8 promotion, from ff92446. Keep the artifact
# so changing the current default never removes compatibility coverage.
LEGACY_MODEL = Path(__file__).parent / "fixtures/diagnosis_tree_schema3.json"


def test_default_is_the_accepted_base81_artifact():
    directory = resources.files("fixfirst").joinpath("knowledge")
    model = default_model()
    assert hashlib.sha256(directory.joinpath("diagnosis_tree.json").read_bytes()).hexdigest() == (
        "189f712ea75bcb117f96aae879fd0c9bdab9ee6531475d1a95faf01ec2738d30"
    )
    assert hashlib.sha256(directory.joinpath("diagnosis_tree.txt").read_bytes()).hexdigest() == (
        "feb6ef7f082a0a88205c2624898427d53f10aa6d0c0709998d57ee01886d4706"
    )
    assert model["schema_version"] == 8
    assert model["feature_names"] == FEATURE_NAMES
    assert len(model["feature_names"]) == 81
    assert model["training_examples"] == 215
    assert model["hyperparameters"] == {"max_depth": 6, "min_samples_leaf": 2}
    with pytest.raises(ValueError, match="wrong length"):
        predict_tree([0.0] * len(LEGACY_FEATURE_NAMES), model)


def test_frozen_legacy44_artifact_is_still_loadable():
    assert hashlib.sha256(LEGACY_MODEL.read_bytes()).hexdigest() == (
        "4479864358595024a121b57fdb49f66f6d184c096c5a243a11fb5f1efdfb41e3"
    )
    model = load_model(LEGACY_MODEL)
    assert model["schema_version"] == 3
    assert model["feature_names"] == LEGACY_FEATURE_NAMES
    assert len(model["feature_names"]) == 44


@pytest.mark.parametrize("source,configuration,data", [
    ("import os\ndef convert():\n    return os.environ['FIXFIRST_CONTEXT_TEST_DSN']\n", 1, 1),
    ("def convert():\n    return {'count': 1}['absent']\n", 0, 1),
    ("def convert():\n    return [1][8]\n", 0, 1),
    ("def convert():\n    return 1 / 0\n", 0, 1),
])
def test_contexts_preserve_the_difference_between_configuration_and_data(
    tmp_path, monkeypatch, source, configuration, data,
):
    monkeypatch.delenv("FIXFIRST_CONTEXT_TEST_DSN", raising=False)
    (tmp_path / "app.py").write_text(source)
    (tmp_path / "test_app.py").write_text(
        "from app import convert\ndef test_convert():\n    assert convert() == 1\n"
    )
    session = create_session(tmp_path, sys.executable, goal="pass_tests")
    scan(session, CHECKS)
    _, details = observations(session, session.issues)
    vector = next(iter(details.values()))["features"]
    assert len(vector) == len(FEATURE_NAMES)
    assert vector[FEATURE_NAMES.index("context_configuration")] == configuration
    assert vector[FEATURE_NAMES.index("context_data_operation")] == data
    assert predict_tree(vector, default_model())[0] == (
        "config_missing" if configuration else "code_defect"
    )
    # Old exports consume the same stable observation prefix.
    model = load_model(LEGACY_MODEL)
    assert predict_tree(vector, model) == predict_tree(vector[:len(LEGACY_FEATURE_NAMES)], model)


def rows_for(names):
    one, two = [0.0] * len(names), [0.0] * len(names)
    two[names.index("module_local")] = 1.0
    return [{"features": one, "label": "missing_dependency", "group": "first"},
            {"features": two, "label": "local_module", "group": "second"}]


def test_old_export_roundtrip_accepts_only_the_known_extension(tmp_path):
    names = LEGACY_FEATURE_NAMES
    rows = rows_for(names)
    path = tmp_path / "legacy.json"
    trained = train_tree(rows, path, min_samples_leaf=1, feature_names=names)
    model = load_model(path)
    assert model == trained and model["schema_version"] == 3
    assert model["training_groups"] == ["first", "second"]
    for row in rows:
        assert predict_tree(row["features"] + [1.0] * 5, model)[0] == row["label"]
    for width in (len(names) - 1, len(names) + 1, len(FEATURE_NAMES) + 1):
        with pytest.raises(ValueError, match="wrong length"):
            predict_tree([0.0] * width, model)


def test_legacy_node_cannot_read_a_new_context_column():
    model = deepcopy(load_model(LEGACY_MODEL))
    model["nodes"][0]["feature"] = len(LEGACY_FEATURE_NAMES)
    with pytest.raises(ValueError, match="invalid feature index"):
        predict_tree([0.0] * len(FEATURE_NAMES), model)


@pytest.mark.parametrize("change", ["order", "schema", "old_columns"])
def test_incompatible_exports_cannot_silently_reinterpret_columns(tmp_path, change):
    model = train_tree(rows_for(FEATURE_NAMES), min_samples_leaf=1)
    if change == "order":
        model["feature_names"] = list(reversed(FEATURE_NAMES))
    elif change == "schema":
        model["schema_version"] = 3
    else:
        model["feature_names"] = LEGACY_FEATURE_NAMES
    path = tmp_path / "wrong.json"
    path.write_text(json.dumps(model))
    with pytest.raises(ValueError, match="features do not match"):
        load_model(path)


@pytest.mark.parametrize("bad", ["width", "nan", "infinity"])
def test_training_rejects_incomplete_or_nonfinite_observations(bad):
    rows = rows_for(FEATURE_NAMES)
    if bad == "width":
        rows[0]["features"].pop()
    else:
        rows[0]["features"][0] = float("nan" if bad == "nan" else "inf")
    with pytest.raises(ValueError, match="wrong length|finite numbers"):
        train_tree(rows)


@pytest.mark.parametrize("weight", [0, -1, float("nan")])
def test_invalid_sample_weights_cannot_silently_change_training(weight):
    rows = rows_for(FEATURE_NAMES)
    rows[0]["weight"] = weight
    with pytest.raises(ValueError, match="finite and positive"):
        train_tree(rows)
