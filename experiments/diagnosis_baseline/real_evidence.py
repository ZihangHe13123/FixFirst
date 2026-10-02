"""Prepare bounded, label-free B3 evidence from saved A2 pass_tests sessions.

This module only reads the supplied mapping and session JSON files. It never
loads FixFirst conclusions, scans a project, or invokes a model. An ambiguous
history requires observation_cutoff_run_id in its mapping row.
"""

import argparse
import hashlib
import json
import math
import ntpath
from pathlib import Path
import posixpath
import re


PROTOCOL = "b3-real-evidence-v1"
CHECKS = {"environment", "project", "pytest", "pytest_run", "pip_check", "ruff"}
INITIAL_CHECKS = ["environment", "pip_check", "pytest_run", "ruff", "project"]
SCOPES = {"environment": "environment", "project": "declarations:project",
          "pytest": "collect:project", "pytest_run": "tests:project",
          "pip_check": "dependencies:environment", "ruff": "lint:project"}
FOLLOWUPS = {"version_search", "dependency_resolve", "pip_install"}
LIMITS = {"text_chars": 20000, "failure_chars": 32000, "exception_chars": 2000,
          "value_chars": 4000, "list_items": 500, "records": 2000}
POLICY = {"limits": LIMITS, "text": "first and last halves with omission marker",
          "lists": "first and last halves; original record indices retained",
          "mappings": "first entries in saved order", "omissions": "evidence.truncation",
          "fields": "frozen raw snapshot/probe allowlists; unknown fields excluded",
          "redaction": "known project/interpreter/environment paths and source identifiers"}
FIELD_POLICY = {
    "project_omitted": {"conda_mappings": "Curated Conda/PyPI mappings and documentation knowledge, not raw declarations"},
    "session_omitted": "Case labels, issues, facts, actions, events, history, inference_trace and goal_status",
    "run_omitted": "Derived verification/coverage summaries, notes, timing and command bookkeeping",
    "snapshot_storage": "Environment/project stdout is represented by the allowlisted structured snapshot",
    "unknown_fields": "Excluded by the frozen raw-field allowlists; never added from conclusions",
}
SCALAR = None


def fields(names):
    return dict.fromkeys(names.split(), SCALAR)


SYMBOL = {
    **fields("source kind operation module owner name file line static_namespace_checked "
             "requested_member_present dynamic unique argument_count_given argument_count_expected "
             "callee_name positional_count definition_file definition_line"),
    "candidates": [fields("name relation")], "argument_types": [SCALAR],
    "parameters": [fields("name kind required")], "keyword_names": [SCALAR],
    "binding_errors": {"missing": [SCALAR], "unexpected": [SCALAR], "duplicate": [SCALAR],
                       "positional_only_as_keyword": [SCALAR], "too_many_positional": SCALAR},
}
RECORDS = {
    "failure": fields("type stage nodeid message"),
    "outcome": fields("type stage nodeid outcome wasxfail"),
    "finish": {**fields("type exit_code collected collect_only records_dropped"), "nodes": [SCALAR]},
    "exception": {
        **fields("type nodeid stage exception_type exception_message exception_module source_file "
                 "source_line symbol_observation_status"),
        "symbol_observation": SYMBOL,
        "attribute_access": fields("name owner_module owner_name source"),
        "module_attribute": {**fields("module name unique source file line"), "suggestions": [SCALAR]},
        "traceback_frames": [{**fields("file line function"), "array_shapes": {"a": [SCALAR], "b": [SCALAR]}}],
        "warnings": [fields("recorder category message filename lineno")],
        "validation_errors": [{**fields("type field"), "input_keys": [SCALAR]}],
    },
}
ENVIRONMENT = {
    **fields("executable prefix python_version"),
    "packages": [{**fields("name version"), "requires": [SCALAR]}],
    "import_distributions": {"*": [SCALAR]}, "stdlib_modules": [SCALAR],
    "paths": fields("stdlib platstdlib purelib platlib"),
    "markers": fields("implementation_name implementation_version os_name platform_machine "
                      "platform_release platform_system platform_version python_full_version "
                      "platform_python_implementation python_version sys_platform"),
}
PROJECT = {
    "files": [fields("path sha256 bytes")],
    "declarations": [fields("name requirement source group constraint installer installed status selected_from")],
    "conda_declarations": [fields("requirement source")],
    "notes": [SCALAR], "requires_python": [fields("specifier source installed status")],
    "own_names": [SCALAR], "python_hints": [fields("version source")],
    "selected_requirement_group": SCALAR, "environment_run_id": SCALAR,
    "local_modules": [fields("name path")], "python_files": [SCALAR], "defined_names": [SCALAR],
    "imported_names": {"*": SCALAR},
    "source_context": {"calls": {"*": [SCALAR]},
                       "call_bindings": {"*": [fields("name target")]},
                       "class_bases": {"*": [SCALAR]}, "class_members": {"*": [SCALAR]}},
    "validation_settings": fields("complete customized"), "numpy_repr_functions": [SCALAR],
    "pydantic_default_models": [SCALAR],
    "pydantic_optional_models": {"*": {"name": SCALAR, "fields": {"*": fields(
        "nullable nullable_without_default location")}}},
    "generator_consumption": {"*": SCALAR}, "lint_config": fields("ruff other"),
    "tested_versions": [fields("name version source")],
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _json(raw):
    """Reject ambiguous keys and non-JSON numeric values at every nesting level."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON object key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("Non-finite JSON number")

    def number(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError("Non-finite JSON number")
        return value

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant, parse_float=number)


def _object(value, description):
    if not isinstance(value, dict):
        raise ValueError(f"{description} must be an object")
    return value


def _nonempty(value, description):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{description} must be a nonempty string")
    return value


def _saved_path(path, description):
    """Normalize according to the saved path style without opening that path."""
    _nonempty(path, description)
    if ntpath.splitdrive(path)[0] and ntpath.isabs(path):
        return ntpath.normcase(ntpath.normpath(path))
    elif path.startswith("/"):
        return posixpath.normpath(path)
    else:
        raise ValueError(f"{description} must be an absolute saved path")


def _saved_environment_id(python):
    """Reproduce the saved host's identity without resolving or opening its path."""
    return digest(_saved_path(python, "target_python").encode())[:16]


def _select(session, cutoff):
    if session.get("goal") != "pass_tests":
        raise ValueError("Only saved A2 pass_tests sessions are supported")
    runs = session.get("runs")
    if not isinstance(runs, list) or not runs:
        raise ValueError("Saved raw runs are required")
    ids = [_nonempty(_object(r, "run").get("run_id"), "run_id") for r in runs]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate run_id in saved session")
    if cutoff is not None:
        _nonempty(cutoff, "observation_cutoff_run_id")
        if cutoff not in ids:
            raise ValueError("observation_cutoff_run_id is not in the saved session")
        selected = runs[:ids.index(cutoff) + 1]
        if any(r.get("tool") not in CHECKS for r in selected):
            raise ValueError("Cutoff includes a follow-up or unsupported run")
        method = "explicit"
    else:
        first_followup = next((i for i, r in enumerate(runs) if r.get("tool") not in CHECKS), len(runs))
        selected = runs[:first_followup]
        if any(r.get("tool") not in FOLLOWUPS for r in runs[first_followup:]):
            raise ValueError("Cannot infer initial scan; supply observation_cutoff_run_id")
        if [r.get("tool") for r in selected] != INITIAL_CHECKS:
            raise ValueError("Cannot infer A2 initial scan; supply observation_cutoff_run_id")
        method = "a2_default_initial_scan"
    tools = [r.get("tool") for r in selected]
    if len(tools) != len(set(tools)):
        raise ValueError("Repeated checks require an unambiguous observation_cutoff_run_id")
    if not {"environment", "project", "pytest_run"}.issubset(tools):
        raise ValueError("Initial environment, project and pytest_run raw records are required")
    if tools[0] != "environment":
        raise ValueError("Initial environment must precede its checks")
    return selected, method


def _snapshot(run, kind):
    if run.get("status") != "completed" or run.get("exit_code") != 0 or run.get("truncated") is not False:
        raise ValueError(f"{kind} snapshot was not completely recorded")
    try:
        return _object(_json(run["stdout"]), f"{kind} snapshot")
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"Missing raw {kind} snapshot JSON") from error


def _validate(session, selected):
    expected = _saved_environment_id(session.get("target_python"))
    project_root = _saved_path(session.get("project_root"), "project_root")
    for run in selected:
        if run.get("source") != "executed" or run.get("environment_id") != expected:
            raise ValueError("Selected run is not executed in the saved target environment")
        if _saved_path(run.get("cwd"), "run.cwd") != project_root:
            raise ValueError("Selected run belongs to a different project working directory")
        if run.get("scope") != SCOPES[run["tool"]] or run.get("targets"):
            raise ValueError("Selected run does not cover the original full check scope")
        if not isinstance(run.get("stdout"), str) or not isinstance(run.get("stderr"), str):
            raise ValueError("Raw stdout and stderr strings are required")
        if not isinstance(run.get("records"), list) or not all(isinstance(r, dict) for r in run["records"]):
            raise ValueError("Raw records must be a list of objects")
        if run.get("status") not in {"completed", "timeout", "cancelled", "launch_failed", "output_limit"}:
            raise ValueError("Run completion status is missing or unsupported")
        if type(run.get("truncated")) is not bool:
            raise ValueError("Run truncation status is required")
        if run["tool"] in {"pytest", "pytest_run"}:
            if not (run["stdout"] or run["stderr"] or run["records"]):
                raise ValueError("The pytest run has no saved raw evidence")
    env_run = next(r for r in selected if r["tool"] == "environment")
    project_run = next(r for r in selected if r["tool"] == "project")
    environment, project = _snapshot(env_run, "environment"), _snapshot(project_run, "project")
    if not isinstance(environment.get("packages"), list) or not environment.get("python_version"):
        raise ValueError("Incomplete raw environment snapshot")
    if project.get("environment_run_id") != env_run["run_id"]:
        raise ValueError("Project snapshot does not link to the selected environment run")
    stored = _object(session.get("environment"), "saved environment metadata")
    stored_run = next((r for r in session["runs"]
                       if r["run_id"] == stored.get("_run_id") and r.get("tool") == "environment"), None)
    if not stored_run or stored.get("_environment_id") != stored_run.get("environment_id"):
        raise ValueError("Saved environment metadata does not link to its raw environment run")
    return environment, project, expected


class Rendering:
    def __init__(self, session, environment, expected, selected, case_id):
        self.omissions = []
        aliases = []
        self.windows = bool(ntpath.splitdrive(session["target_python"])[0])
        replacements = {session["project_root"]: "/project", session["target_python"]: "/environment/python",
                        expected: "environment-1"}
        prefix = environment.get("prefix")
        if isinstance(prefix, str) and prefix:
            replacements[prefix] = "/environment"
        executable = environment.get("executable")
        if isinstance(executable, str) and executable:
            replacements[executable] = "/environment/python"
        for key, path in environment.get("paths", {}).items():
            if isinstance(path, str) and path:
                replacements[path] = "/environment/" + ("site-packages" if key in {"purelib", "platlib"} else "stdlib")
        for index, run in enumerate(selected):
            replacements[run["run_id"]] = f"run-{index + 1}"
        for key in (session.get("session_id"), session.get("name"), case_id):
            if isinstance(key, str) and key:
                replacements.setdefault(key, "case")
        for private, public in sorted(replacements.items(), key=lambda item: -len(item[0])):
            variants = {private, private.replace("\\", "/"), private.replace("\\", "\\\\")}
            for variant in sorted(variants, key=len, reverse=True):
                # Token boundaries avoid changing module names merely containing a short case id.
                pattern = re.escape(variant)
                if variant[0].isalnum() and "/" not in variant and "\\" not in variant:
                    pattern = r"(?<![\w])" + pattern + r"(?![\w])"
                elif variant[-1].isalnum():
                    pattern += r"(?![\w.-])"
                aliases.append((pattern, public))
        self.pattern = re.compile("|".join(f"(?P<a{i}>{p})" for i, (p, _) in enumerate(aliases)),
                                  re.I if self.windows else 0)
        self.aliases = {f"a{i}": public for i, (_, public) in enumerate(aliases)}

    def redact(self, value):
        return self.pattern.sub(lambda match: self.aliases[match.lastgroup], value)

    def text(self, value, path, limit):
        value = self.redact(value)
        if len(value) <= limit:
            return value
        half = limit // 2
        self.omissions.append({"path": path, "unit": "characters", "original": len(value), "kept": 2 * half})
        return value[:half] + f"\n[... {len(value) - 2 * half} characters omitted ...]\n" + value[-half:]

    def indices(self, length, limit, path):
        if length <= limit:
            return list(range(length))
        half = limit // 2
        self.omissions.append({"path": path, "unit": "items", "original": length, "kept": 2 * half})
        return [*range(half), *range(length - half, length)]

    def render(self, value, schema, path):
        if schema is None:
            if isinstance(value, str):
                limit = LIMITS["failure_chars"] if path.endswith(".message") and ".records[" in path else LIMITS["value_chars"]
                if path.endswith(".exception_message"):
                    limit = LIMITS["exception_chars"]
                return self.text(value, path, limit)
            if value is None or type(value) in (int, float, bool):
                return value
            raise ValueError(f"Expected a scalar at {path}")
        if isinstance(schema, list):
            if not isinstance(value, list):
                raise ValueError(f"Expected a list at {path}")
            return [self.render(value[i], schema[0], f"{path}[{i}]")
                    for i in self.indices(len(value), LIMITS["list_items"], path)]
        _object(value, path)
        result = {}
        allowed = [(k, v) for k, v in value.items() if k in schema or "*" in schema]
        if len(allowed) > LIMITS["list_items"]:
            self.omissions.append({"path": path, "unit": "entries", "original": len(allowed), "kept": LIMITS["list_items"]})
        for key, item in allowed[:LIMITS["list_items"]]:
            public_key = key if key in schema else self.redact(key)
            if public_key in result:
                raise ValueError(f"Redaction creates duplicate mapping keys at {path}")
            result[public_key] = self.render(item, schema.get(key, schema.get("*")), f"{path}.{public_key}")
        return result


def _evidence(session, selected, environment, project, expected, case_id):
    render = Rendering(session, environment, expected, selected, case_id)
    evidence = {"protocol": PROTOCOL, "goal": "pass_tests", "runs": [],
                "environment": render.render(environment, ENVIRONMENT, "environment"),
                "project": render.render(project, PROJECT, "project")}
    for index, run in enumerate(selected):
        path = f"runs[{index}]"
        item = {"run_id": f"run-{index + 1}", "tool": run["tool"], "environment_id": "environment-1"}
        item.update(render.render(run, fields("scope source status exit_code truncated tool_version"), path))
        if run["tool"] in {"environment", "project"}:
            item["snapshot"] = run["tool"]
            item["stderr"] = render.text(run["stderr"], path + ".stderr", LIMITS["text_chars"])
        else:
            for stream in ("stdout", "stderr"):
                item[stream] = render.text(run[stream], path + "." + stream, LIMITS["text_chars"])
        item["records"] = []
        allowed = [(i, r) for i, r in enumerate(run["records"]) if r.get("type") in RECORDS]
        if len(allowed) != len(run["records"]):
            render.omissions.append({"path": path + ".records", "unit": "records_outside_allowlist",
                                     "original": len(run["records"]), "kept": len(allowed)})
        for kept in render.indices(len(allowed), LIMITS["records"], path + ".records"):
            record_index, record = allowed[kept]
            item["records"].append({"record_index": record_index,
                                    **render.render(record, RECORDS[record["type"]], f"{path}.records[{record_index}]")})
        evidence["runs"].append(item)
    evidence["truncation"] = render.omissions
    return evidence


def prepare(mapping_path: Path, sessions_root: Path, output: Path) -> dict:
    """Validate and prepare a fresh evidence batch, returning its manifest."""
    mapping_path, sessions_root, output = Path(mapping_path), Path(sessions_root), Path(output)
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    raw_mapping = mapping_path.read_bytes()
    mapping = _json(raw_mapping)
    mapping = mapping.get("results") if isinstance(mapping, dict) else mapping
    if not isinstance(mapping, list) or not mapping:
        raise ValueError("Mapping must be a nonempty list or an object with results")
    cases, provenance, case_ids, session_ids = [], [], set(), set()
    for row in mapping:
        row = _object(row, "mapping row")
        case_id = _nonempty(row.get("id"), "id")
        session_id = _nonempty(row.get("session_id"), "session_id")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", session_id):
            raise ValueError("session_id must be a single safe directory name")
        if case_id in case_ids or session_id in session_ids:
            raise ValueError("Duplicate id or session_id in mapping")
        case_ids.add(case_id)
        session_ids.add(session_id)
        path = sessions_root / session_id / "session.json"
        if not path.resolve().is_relative_to(sessions_root.resolve()):
            raise ValueError("Session path escapes sessions_root")
        raw = path.read_bytes()
        session = _object(_json(raw), "session")
        if session.get("session_id") != session_id:
            raise ValueError("Mapping session_id does not match saved session")
        selected, method = _select(session, row.get("observation_cutoff_run_id"))
        environment, project, expected = _validate(session, selected)
        evidence = _evidence(session, selected, environment, project, expected, case_id)
        source_sha256 = digest(raw)
        cases.append({"case_id": case_id, "evidence": evidence, "evidence_sha256": digest(canonical(evidence)),
                      "source_sha256": source_sha256})
        provenance.append({"case_id": case_id, "session_id": session_id, "source_sha256": source_sha256,
                           "observation_cutoff_run_id": selected[-1]["run_id"], "cutoff_method": method,
                           "selected_run_ids": [r["run_id"] for r in selected],
                           "excluded_run_count": len(session["runs"]) - len(selected)})
    cases_bytes = b"".join(canonical(case) + b"\n" for case in cases)
    manifest = {"schema_version": 1, "protocol": PROTOCOL, "cases_file": "cases.jsonl",
                "cases_sha256": digest(cases_bytes), "case_ids": [r["case_id"] for r in cases],
                "builder": {"name": "experiments/diagnosis_baseline/real_evidence.py",
                            "sha256": digest(Path(__file__).read_bytes())},
                "input_provenance": {"mapping_sha256": digest(raw_mapping), "sessions": provenance},
                "truncation_policy": POLICY, "evidence_field_policy": FIELD_POLICY}
    output.mkdir(parents=True, exist_ok=False)
    with (output / "cases.jsonl").open("xb") as stream:
        stream.write(cases_bytes)
    with (output / "manifest.json").open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mapping", type=Path)
    parser.add_argument("sessions_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = prepare(args.mapping, args.sessions_root, args.output)
    except (OSError, ValueError) as error:
        parser.exit(2, f"{error}\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
