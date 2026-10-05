"""Hard scenarios as agent tasks (experiments/agent_baseline/hard_instances.py): what a scenario may add
to the tests, its reference, its identity, and which template each scenario uses. Nothing here runs a
suite or a sandbox; the runs are in experiments/agent_baseline/test_harness.py."""

import dataclasses
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "agent_baseline"))

import hard_instances as hi  # noqa: E402
from fixfirst import diagnosis_cases as dc  # noqa: E402

REGISTRY = hi.load_registry()
YAML, NO_CHECK = "vb_yaml_loader", "ml_renamed_then_alias"


def instance(folder, template="flat-shop", scenario=YAML):
    """The healthy template, the start and the reference of one instance, in folders of their own."""
    t = hi.template(template)
    built = hi.build(folder, t, hi.scenario(scenario))
    problems = hi.make_reference(folder / "reference", built["pristine"], built["start"], t, REGISTRY[scenario])
    return t, built["pristine"], built["start"], folder / "reference", problems


def test_the_registry_is_exactly_the_generators_hard_scenarios():
    assert sorted(REGISTRY) == hi.hard_scenarios() == ["ml_renamed_then_alias", "vb_click_mix_stderr", "vb_numpy_promotion",
                                                       "vb_numpy_repr", "vb_pydantic_coercion", "vb_yaml_loader"]
    assert [name for name, entry in REGISTRY.items() if not entry["check"]] == [NO_CHECK]
    assert REGISTRY[YAML] == {"check": "load_settings", "check_body": '    assert load_settings("rate: 2") == {"rate": 2}',
                              "fails_with": "missing 1 required positional argument: 'Loader'",
                              "repair": [["yaml.load(text)", "yaml.safe_load(text)"]]}


@pytest.mark.parametrize("change,reason", [
    (lambda r: r.pop(YAML), "not registered"),
    (lambda r: r.update(vb_unknown=dict(r[YAML])), "unknown"),
    (lambda r: r[YAML].pop("fails_with"), "exactly"),
    (lambda r: r[YAML].update(note="x"), "exactly"),
    (lambda r: r[YAML].update(check="load settings"), "name of a function"),
    (lambda r: r[YAML].update(fails_with=" "), "fails_with is not empty"),
    (lambda r: r[YAML].update(check_body=""), "has its body"),
    (lambda r: r[YAML].update(repair=[]), "has its body"),
    (lambda r: r[YAML].update(repair=[["yaml.load(text)", "yaml.load(text)"]]), "has its body"),
    (lambda r: r[YAML].update(repair=[["yaml.load(text)"]]), "has its body"),
    (lambda r: r[NO_CHECK].update(repair=[["a", "b"]]), "one without has neither"),
    (lambda r: r[NO_CHECK].update(check_body="    assert True"), "one without has neither"),
])
def test_a_registry_that_does_not_fit_is_refused(tmp_path, change, reason):
    import copy
    registry = copy.deepcopy(REGISTRY)
    change(registry)
    lines = []
    for name, entry in registry.items():
        lines.append(f"[{name}]")
        lines += [f"{key} = {__import__('json').dumps(value)}" for key, value in entry.items()]
    (tmp_path / "hard_cases.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=reason):
        hi.load_registry(tmp_path / "hard_cases.toml")


def test_the_candidate_order_is_the_sorted_templates_rotated_by_the_scenarios_place():
    assert hi.candidates() == {
        "ml_renamed_then_alias": ["fixture-orders", "flat-shop", "pkg-inventory", "src-billing", "unittest-grades"],
        "vb_click_mix_stderr": ["flat-shop", "pkg-inventory", "src-billing", "unittest-grades", "fixture-orders"],
        "vb_numpy_promotion": ["pkg-inventory", "src-billing", "unittest-grades", "fixture-orders", "flat-shop"],
        "vb_numpy_repr": ["src-billing", "unittest-grades", "fixture-orders", "flat-shop", "pkg-inventory"],
        "vb_pydantic_coercion": ["unittest-grades", "fixture-orders", "flat-shop", "pkg-inventory", "src-billing"],
        "vb_yaml_loader": ["fixture-orders", "flat-shop", "pkg-inventory", "src-billing", "unittest-grades"]}


def test_every_template_admits_every_registered_scenario_and_takes_its_repair(tmp_path):
    digests = set()
    for t in dc.TEMPLATES:
        for name, entry in REGISTRY.items():
            _, pristine, start, reference, problems = instance(tmp_path / f"{t.name}--{name}", t.name, name)
            assert problems == [] and hi.admit(pristine, start, t, entry) == []
            changed = {path for path in hi.tree(start) if hi.tree(start)[path] != hi.tree(reference).get(path)}
            if entry["check"]:  # the repair changes the service module and nothing else
                assert changed == {t.service} and set(hi.tree(start)) == set(hi.tree(reference))
                assert hi.required_node(t, entry) == f"{t.test[:-3].replace('/', '.')}::test_{entry['check']}"
            else:  # the reference is the healthy template
                assert hi.tree(reference) == hi.tree(pristine) and hi.required_node(t, entry) is None
            digests.add(hi.digest(hi.manifest(t, name, entry, start, reference, {"python": "3", "interpreter": "i", "sha256": "e"}, {})))
    assert len(digests) == 30


def test_the_appended_check_is_the_generators_own_text(tmp_path):
    t, pristine, start, _, _ = instance(tmp_path / "i", "unittest-grades")
    assert hi.appended_check(t, REGISTRY[YAML]) == (
        'def test_load_settings():\n    from grades import load_settings\n\n    assert load_settings("rate: 2") == {"rate": 2}\n')
    assert (start / t.test).read_text() == (pristine / t.test).read_text() + "\n\n" + hi.appended_check(t, REGISTRY[YAML])
    assert hi.appended_check(t, REGISTRY[NO_CHECK]) is None


def append(text):
    return lambda start, t: (start / t.test).write_text((start / t.test).read_text() + text)


@pytest.mark.parametrize("scenario,tamper,reason", [
    (YAML, lambda start, t: (start / t.test).write_text((start / t.test).read_text().replace('"rate": 2', '"rate": 3')),
     "not the healthy test module followed by exactly the registered check"),
    (YAML, append("\n\ndef test_extra():\n    assert True\n"), "followed by exactly the registered check"),
    (YAML, append("\npytestmark = []\n"), "followed by exactly the registered check"),
    (YAML, lambda start, t: (start / t.test).write_text(
        (start / t.test).read_text().replace("def test_load_settings", "import pytest\n\n\n@pytest.mark.skip\ndef test_load_settings")),
     "followed by exactly the registered check"),
    (YAML, lambda start, t: (start / t.test).write_bytes((start / t.test).read_bytes().replace(b"\n", b"\r\n")),
     "followed by exactly the registered check"),  # the same text with other line endings is another file
    (YAML, lambda start, t: (start / "test_more.py").write_text("def test_more():\n    assert True\n"), "beyond its registered check: test_more.py"),
    (YAML, lambda start, t: (start / t.conftest).write_text("collect_ignore = ['test_app.py']\n"), "beyond its registered check: conftest.py"),
    (YAML, lambda start, t: (start / "pytest.ini").write_text("[pytest]\naddopts = -k order\n"), "beyond its registered check: pytest.ini"),
    (YAML, lambda start, t: (start / "setup.cfg").write_text("[tool:pytest]\npython_functions = check_*\n"),
     "beyond its registered check: setup.cfg:python_functions"),
    (NO_CHECK, append("\n\ndef test_extra():\n    assert True\n"), "beyond its registered check: tests/test_service.py"),
])
def test_a_start_with_anything_but_the_registered_check_is_not_admitted(tmp_path, scenario, tamper, reason):
    t, pristine, start, _, _ = instance(tmp_path / "i", "flat-shop" if scenario == YAML else "fixture-orders", scenario)
    assert hi.admit(pristine, start, t, REGISTRY[scenario]) == []
    tamper(start, t)
    assert any(reason in problem for problem in hi.admit(pristine, start, t, REGISTRY[scenario]))


@pytest.mark.parametrize("addition,healthy,reason", [
    ("@fixture\ndef test_x():\n    assert True\n", "", "not one plain function"),
    ("def test_x(tmp_path):\n    assert True\n", "", "not one plain function"),
    ("def test_x():\n    assert True\n\n\ndef test_y():\n    assert True\n", "", "not one plain function"),
    ("pytestmark = []\n", "", "not one plain function"),
    ("class test_x:\n    pass\n", "", "not one plain function"),
    ("def test_x():\n    assert True\n", "def test_x():\n    assert False\n", "already uses the name test_x"),
    ("def test_x():\n    assert True\n", "class T:\n    def test_x(self):\n        pass\n", "already uses the name test_x"),
    ("def test_x():\n    assert True\n", "from helpers import check as test_x\n", "already uses the name test_x"),
    ("def test_x():\n    assert True\n", "test_x = None\n", "already uses the name test_x"),
    ("def test_x(:\n", "", "does not parse"),
])
def test_a_registered_check_must_be_one_plain_new_test_function(addition, healthy, reason):
    assert hi.check_shape("def test_other():\n    pass\n", "def test_x():\n    assert True\n", "test_x") == []
    assert any(reason in problem for problem in hi.check_shape(healthy, addition, "test_x"))


@pytest.mark.parametrize("repair,reason", [
    ([["yaml.dump(text)", "yaml.safe_load(text)"]], "occurs 0 times in app.py"),
    ([["yaml", "ruamel"]], "occurs 2 times in app.py"),
])
def test_a_repair_that_does_not_apply_exactly_once_gives_no_reference(tmp_path, repair, reason):
    t, pristine, start, _, _ = instance(tmp_path / "i")
    problems = hi.make_reference(tmp_path / "other", pristine, start, t, {**REGISTRY[YAML], "repair": repair})
    assert len(problems) == 1 and reason in problems[0]


def test_a_repair_never_touches_a_test(tmp_path):
    t, pristine, start, _, _ = instance(tmp_path / "i")
    in_the_tests = dataclasses.replace(t, service=t.test)  # a repair aimed at the test module
    entry = {**REGISTRY[YAML], "repair": [['{"rate": 2}', '{"rate": 3}']]}
    assert hi.make_reference(tmp_path / "other", pristine, start, in_the_tests, entry) == [
        "the registered repair changes tests or pytest settings"]


def test_the_digest_is_the_same_for_the_same_instance_and_changes_with_each_of_its_parts(tmp_path):
    env, code = {"python": "3.12", "interpreter": "cpython-3.12.13", "sha256": "e" * 64}, {"agent_baseline/agent_pilot.py": "a" * 64}
    t, _, start, reference, _ = instance(tmp_path / "one")
    _, _, start2, reference2, _ = instance(tmp_path / "two")  # the same instance made again, elsewhere
    entry = REGISTRY[YAML]
    base = hi.digest(hi.manifest(t, YAML, entry, start, reference, env, code))
    assert base == hi.digest(hi.manifest(t, YAML, entry, start2, reference2, env, code)) and len(base) == 64
    variants = [hi.manifest(t, YAML, {**entry, "fails_with": "another failure"}, start, reference, env, code),
                hi.manifest(t, YAML, entry, start, reference, {**env, "sha256": "f" * 64}, code),
                hi.manifest(t, YAML, entry, start, reference, {**env, "interpreter": "cpython-3.12.14"}, code),
                hi.manifest(t, YAML, entry, start, reference, env, {"agent_baseline/agent_pilot.py": "b" * 64})]
    (start2 / "requirements.txt").write_text((start2 / "requirements.txt").read_text() + "# a comment\n")
    variants.append(hi.manifest(t, YAML, entry, start2, reference, env, code))  # a file of the start
    (reference2 / t.service).write_text((reference2 / t.service).read_text() + "# a comment\n")
    variants.append(hi.manifest(t, YAML, entry, start, reference2, env, code))  # a file of the reference
    assert len({base, *map(hi.digest, variants)}) == 7
    manifest = hi.manifest(t, YAML, entry, start, reference, env, code)
    assert manifest["appended_check"] == {"file": "test_app.py", "node": "test_app::test_load_settings",
                                          "sha256": hi.sha256(hi.appended_check(t, entry))}
    assert set(manifest["tests_and_settings"]) == {"test_app.py", "conftest.py"} and "pristine" not in str(manifest)
    assert str(tmp_path) not in str(manifest)  # no folder names: the same instance elsewhere is the same instance


def test_the_code_identity_covers_the_generator_the_harness_and_the_qualification():
    identity = hi.code_identity()
    assert sorted(identity) == ["agent_baseline/_h5_grading_probe.py", "agent_baseline/agent_file_tools.py", "agent_baseline/agent_pilot.py", "agent_baseline/hard_cases.toml",
                                "agent_baseline/hard_instances.py", "agent_baseline/isolation.py",
                                "agent_baseline/pytest_policy.py", "agent_baseline/qualify_hard.py", "agent_baseline/real_cases.py",
                                "fixfirst/diagnosis_cases.py", "fixfirst/hard_cases.py"]
    assert all(len(value) == 64 for value in identity.values())
    assert identity["agent_baseline/qualify_hard.py"] == hi.rc.file_hash(hi.HERE / "qualify_hard.py")


def test_the_environment_is_its_distributions_by_name_and_version_without_paths(tmp_path):
    def venv(root, extra=()):
        site = root / "lib" / "python3.12" / "site-packages"
        for name, version in (("PyYAML", "6.0.3"), ("numpy", "2.5.3"), *extra):
            (site / f"{name}-{version}.dist-info").mkdir(parents=True)
            (site / f"{name}-{version}.dist-info" / "METADATA").write_text(f"Name: {name}\nVersion: {version}\n")
        base = tmp_path / "base" / "cpython-3.12.13-macos" / "bin"
        base.mkdir(parents=True, exist_ok=True)
        (root / "pyvenv.cfg").write_text(f"home = {base}\nversion_info = 3.12.13\n")
        (root / "bin").mkdir()
        return root / "bin" / "python"
    one, two = hi.environment(venv(tmp_path / "a")), hi.environment(venv(tmp_path / "b"))
    assert one == two == {"python": "3.12.13", "interpreter": "cpython-3.12.13-macos", "distributions": ["numpy==2.5.3", "pyyaml==6.0.3"],
                          "sha256": hi.sha256("numpy==2.5.3\npyyaml==6.0.3")}
    assert hi.environment(venv(tmp_path / "c", extra=(("click", "8.5.0"),)))["sha256"] != one["sha256"]


PASSED = {"test_app::test_order_total": "passed", "test_app::test_cart_total": "passed", "test_app::test_load_settings": "passed"}


def reference(**outcomes):
    return {"exit_code": 0, "repair": [], "outcomes": {**PASSED, **outcomes}}


@pytest.mark.parametrize("outcome,reason", [("skipped", "did not actually pass"), ("xfailed", "did not actually pass"),
                                            ("failed", "failed or errored"), (None, "was not run in the reference")])
def test_a_reference_grades_only_if_every_test_actually_passed_the_check_included(outcome, reason):
    t, entry = hi.template("flat-shop"), REGISTRY[YAML]
    assert hi.reference_problems(reference(), t, entry) == []
    data = reference(**{"test_app::test_load_settings": outcome})
    if outcome is None:
        del data["outcomes"]["test_app::test_load_settings"]
    assert any(reason in problem for problem in hi.reference_problems(data, t, entry))
    other = reference(**{"test_app::test_cart_total": "skipped"})  # also a test that is not the check
    assert any("did not actually pass" in problem for problem in hi.reference_problems(other, t, entry))
    assert hi.reference_problems({**reference(), "exit_code": 1}, t, entry) != []


def test_a_reference_without_a_check_needs_every_test_of_the_healthy_template_to_pass():
    t, entry = hi.template("flat-shop"), REGISTRY[NO_CHECK]
    healthy = {"exit_code": 0, "repair": [], "outcomes": {name: "passed" for name in list(PASSED)[:2]}}
    assert hi.reference_problems(healthy, t, entry) == []
    healthy["outcomes"]["test_app::test_cart_total"] = "skipped"
    assert any("did not actually pass" in problem for problem in hi.reference_problems(healthy, t, entry))


TYPE_ERROR = "TypeError: load() missing 1 required positional argument: 'Loader'\napp.py:6: TypeError"


@pytest.mark.parametrize("outcomes,said,reason", [
    ({}, {}, None),
    ({"test_app::test_load_settings": "passed"}, {}, "is passed at the start, not failing"),
    ({"test_app::test_load_settings": None}, {}, "is not run at the start"),
    ({}, {"test_app::test_load_settings": "ModuleNotFoundError: No module named 'yaml'"}, "fails for another reason"),
    ({"test_app::test_cart_total": "failed"}, {}, "other tests do not pass at the start, e.g. test_app::test_cart_total"),
])
def test_a_start_shows_the_registered_fault_and_nothing_else(outcomes, said, reason):
    t, entry = hi.template("flat-shop"), REGISTRY[YAML]
    found = {**PASSED, "test_app::test_load_settings": "failed", **outcomes}
    found = {name: outcome for name, outcome in found.items() if outcome is not None}
    problems = hi.start_problems({"outcomes": found}, {"test_app::test_load_settings": TYPE_ERROR, **said}, t, entry)
    assert problems == [] if reason is None else any(reason in problem for problem in problems)


HELPER = "collection failure\nE   ModuleNotFoundError: No module named 'helper'"


@pytest.mark.parametrize("outcomes,said,reason", [
    ({"::test_app": "error"}, {"::test_app": HELPER}, None),
    ({"::test_app": "error"}, {"::test_app": "collection failure\nE   ModuleNotFoundError: No module named 'numpy'"},
     "does not fail to load with \"No module named 'helper'\""),
    ({"test_app::test_cart_total": "passed"}, {}, "does not fail to load"),
    ({"::test_app": "passed"}, {"::test_app": HELPER}, "does not fail to load"),  # said, but did not fail
    ({"::other": "error"}, {"::other": HELPER}, "does not fail to load"),  # the right words in another module
    # the registered error and a second one that has nothing to do with it (Codex R9-3)
    ({"::test_app": "error", "::unrelated": "error"},
     {"::test_app": HELPER, "::unrelated": "ModuleNotFoundError: No module named 'unrelated_dependency'"},
     "more than that loading error, e.g. ::unrelated (error)"),
    ({"::test_app": "error", "::again": "error"}, {"::test_app": HELPER, "::again": HELPER}, "more than that loading error"),
    ({"::test_app": "error", "test_more::test_x": "passed"}, {"::test_app": HELPER}, "more than that loading error"),
])
def test_a_start_without_a_check_is_exactly_its_test_modules_loading_error(outcomes, said, reason):
    problems = hi.start_problems({"outcomes": outcomes, "summary": "1 error"}, said, hi.template("flat-shop"), REGISTRY[NO_CHECK])
    assert problems == [] if reason is None else len(problems) == 1 and reason in problems[0]
    nested = hi.start_problems({"outcomes": {"::tests.test_service": "error"}},
                               {"::tests.test_service": "E   ModuleNotFoundError: No module named 'orders.tax'"},
                               hi.template("fixture-orders"), REGISTRY[NO_CHECK])
    assert nested == []  # the module's dotted name and the helper's come from the template


@pytest.mark.parametrize("exit_code,stopped,reason", [
    (0, False, None), (1, False, None), (2, False, None), (5, False, None),  # verdicts, whatever they say
    (-9, False, "ended by signal 9"), (-15, False, "ended by signal 15"),  # Codex R9-2
    (124, False, "stopped at its time limit"), (1, True, "stopped at its time limit"),
    (3, False, "pytest exited with 3"), (4, False, "pytest exited with 4"),
    (None, False, "gave no exit code"), (None, None, "gave no exit code"), (True, False, "gave no exit code"),
])
def test_a_suite_that_did_not_run_to_a_verdict_says_nothing_about_the_instance(exit_code, stopped, reason):
    found = hi.not_completed(exit_code, stopped)
    assert found is None if reason is None else reason in found


def test_failures_are_read_from_the_junit_report(tmp_path):
    report = tmp_path / "junit.xml"
    report.write_text('<testsuites><testsuite><testcase classname="test_app" name="test_a"/>'
                      '<testcase classname="test_app" name="test_b"><failure message="TypeError: boom">app.py:6: TypeError</failure></testcase>'
                      '<testcase classname="" name="test_c"><error message="collection failure">No module named x</error></testcase>'
                      '<testcase classname="test_app" name="test_d"><skipped message="why"/></testcase></testsuite></testsuites>')
    assert hi.failures(report) == {"test_app::test_b": "TypeError: boom\napp.py:6: TypeError",
                                   "::test_c": "collection failure\nNo module named x"}
    assert hi.failures(tmp_path / "missing.xml") == {}


ORDER = {"s1": ["a", "b", "c", "d", "e"], "s2": ["b", "c", "d", "e", "a"]}


def scan(results):
    """Run the selection with given results per (template, scenario): a list is used up attempt by attempt."""
    seen = []

    def qualify(template, scenario):
        seen.append((scenario, template))
        result = results.get((template, scenario), "qualified")
        result = result.pop(0) if isinstance(result, list) else result
        return {"result": result, "reason": None if result == "qualified" else "why", "digest": f"{template}-{scenario}"}
    return hi.select(qualify, ORDER), seen


def test_the_first_qualified_instance_is_formal_and_the_next_one_development():
    selection, seen = scan({})
    assert selection["selection"]["s1"] == {"formal": {"template": "a", "candidate": 1, "digest": "a-s1"},
                                            "development": {"template": "b", "candidate": 2, "digest": "b-s1"}}
    assert selection["selection"]["s2"]["formal"]["template"] == "b" and selection["selection"]["s2"]["development"]["template"] == "c"
    assert seen == [("s1", "a"), ("s1", "b"), ("s2", "b"), ("s2", "c")]  # two qualified: the scenario is done
    assert [a["role"] for a in selection["attempts"]] == ["formal", "development", "formal", "development"]
    assert selection["formal_templates"] == {"a": 1, "b": 1} and selection["cannot_run"] == []


def test_a_formal_candidate_that_does_not_qualify_moves_both_roles_on():
    selection, seen = scan({("a", "s1"): "not_qualified", ("c", "s1"): "not_qualified"})
    chosen = selection["selection"]["s1"]
    assert (chosen["formal"]["template"], chosen["development"]["template"]) == ("b", "d")  # never the same instance
    assert [template for scenario, template in seen if scenario == "s1"] == ["a", "b", "c", "d"]
    assert [(a["template"], a["result"], a.get("role")) for a in selection["attempts"][:4]] == [
        ("a", "not_qualified", None), ("b", "qualified", "formal"), ("c", "not_qualified", None), ("d", "qualified", "development")]


def test_one_qualified_instance_is_formal_and_none_means_the_scenario_cannot_run():
    only_last = {(template, "s1"): "not_qualified" for template in "abcd"}
    none = {(template, "s2"): "not_qualified" for template in "abcde"}
    selection, seen = scan({**only_last, **none})
    assert selection["selection"]["s1"] == {"formal": {"template": "e", "candidate": 5, "digest": "e-s1"}, "development": None}
    assert selection["selection"]["s2"] == {"formal": None, "development": None}
    assert selection["cannot_run"] == ["s2"] and selection["without_development_instance"] == ["s1"]
    assert len(seen) == 10 and selection["formal_templates"] == {"e": 1}  # the planned scenarios all stay listed


def test_a_check_that_could_not_be_completed_is_tried_once_more_and_then_counts_as_not_qualified():
    selection, seen = scan({("a", "s1"): ["not_checked", "qualified"], ("b", "s1"): ["not_checked", "not_checked"]})
    assert [template for scenario, template in seen if scenario == "s1"] == ["a", "a", "b", "b", "c"]
    attempts = [(a["template"], a["attempt"], a["result"], a.get("role"), "counts_as" in a) for a in selection["attempts"][:5]]
    assert attempts == [("a", 1, "not_checked", None, False), ("a", 2, "qualified", "formal", False),
                        ("b", 1, "not_checked", None, False), ("b", 2, "not_checked", None, True),
                        ("c", 1, "qualified", "development", False)]
    assert selection["attempts"][3]["counts_as"].startswith("not_qualified")
    with pytest.raises(ValueError, match="qualified, not_qualified or not_checked"):
        hi.select(lambda template, scenario: {"result": "maybe"}, ORDER)


def test_the_real_order_uses_every_template_when_all_qualify():
    selection = hi.select(lambda template, scenario: {"result": "qualified", "reason": None, "digest": "d"})
    assert selection["formal_templates"] == {"fixture-orders": 2, "flat-shop": 1, "pkg-inventory": 1, "src-billing": 1,
                                             "unittest-grades": 1}
    development = {name: chosen["development"]["template"] for name, chosen in selection["selection"].items()}
    assert development == {name: order[1] for name, order in hi.candidates().items()}
    assert all(chosen["formal"]["template"] != chosen["development"]["template"] for chosen in selection["selection"].values())


def test_a_frozen_selection_gives_the_instances_of_one_role():
    selection, _ = scan({(template, "s2"): "not_qualified" for template in "bcde"})
    assert hi.selected(selection, "formal") == {"a:s1": "a-s1", "a:s2": "a-s2"}
    assert hi.selected(selection, "development") == {"b:s1": "b-s1"}  # s2 has no development instance
    with pytest.raises(ValueError, match="formal, development"):
        hi.selected(selection, "smoke")
