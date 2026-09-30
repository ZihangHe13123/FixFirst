"""Explicit wheel-only trials of a proposed change to one project's version pin.

The resolver may update dependencies together. Only the named project's version
constraint is relaxed; all other declarations remain inputs. A successful trial
proves installation and metadata consistency, never application correctness.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

from .dependency_context import active_requirement, context
from .models import Run

MAX_REQUIREMENTS = 100
MAX_SECONDS = 300


def fingerprint(environment, project):
    value = {"trial_protocol": 4, "context": context(environment, project)["fingerprint"],
             "files": project.get("files", []), "notes": project.get("notes", []),
             "conda": project.get("conda_declarations", []),
             "python_hints": project.get("python_hints", [])}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def inputs(environment, project, name, direction=""):
    """Produce concrete target-environment requests, or decline incomplete input."""
    name = canonicalize_name(name)
    SpecifierSet(direction)
    notes = [n for n in project.get("notes", []) if not n.startswith("setup.py is not executed;")]
    if notes or project.get("conda_declarations"):
        raise ValueError("Some declarations are not statically understood: " + "; ".join(notes[:3]))
    requests, constraints, edits, extras = [], [], [], {}
    for row in project.get("declarations", []):
        if row.get("group", "required") != "required" and not row.get("constraint"):
            continue
        requirement = active_requirement(row["requirement"], environment.get("markers", {}))
        if not requirement:
            continue
        if requirement.url or row.get("installer", "pip") != "pip":
            raise ValueError(f"{row['source']}: direct references and non-pip installers need manual review")
        target = canonicalize_name(requirement.name)
        extras.setdefault(target, set()).update(requirement.extras)
        extra = "[" + ",".join(sorted(requirement.extras)) + "]" if requirement.extras else ""
        spec = str(requirement.specifier)
        if target == name and spec:
            edits.append({"source": row["source"], "before": str(requirement),
                          "constraint": bool(row.get("constraint")), "extras": sorted(requirement.extras),
                          "marker": str(requirement.marker) if requirement.marker else ""})
            spec = direction
        value = requirement.name + extra + spec
        (constraints if row.get("constraint") else requests).append(value)
    if not edits or not any(canonicalize_name(Requirement(v).name) == name for v in requests):
        raise ValueError("The named distribution must have an active, versioned, required project declaration")
    # Preserve packages outside the declared project dependency graph. Updating a declared
    # root (e.g. alembic) may change its Requires-Dist, so its old metadata must not
    # incorrectly prohibit a joint solution. Unrelated installed packages stay.
    roots = {canonicalize_name(Requirement(v).name) for v in requests}
    dependencies = context(environment, project)
    if dependencies["notes"]:
        raise ValueError("Installed dependency metadata is incomplete: " + "; ".join(dependencies["notes"][:3]))
    graph = {}
    for row in dependencies["requirements"]:
        if row["owner"] != "project":
            graph.setdefault(row["owner"], set()).add(row["name"])
    related, pending = set(roots), list(roots)
    while pending:
        owner = pending.pop()
        for target in graph.get(owner, set()) - related:
            related.add(target)
            pending.append(target)
    own = set(project.get("own_names", []))
    for package in environment.get("packages", []):
        target = canonicalize_name(package.get("name", ""))
        if target and target not in roots | own | {"pip", "setuptools", "wheel"}:
            # pip install does not remove old, now-unused transitive packages.
            # Keep them present in the trial, permitting a related package to
            # update, so an orphan cannot silently disappear from the proof.
            request = target if target in related else target + "==" + package["version"]
            requests.append(str(Requirement(request)))
    if len(requests) + len(constraints) > MAX_REQUIREMENTS:
        raise ValueError(f"More than {MAX_REQUIREMENTS} requirements; use the project's environment manager")
    for row in project.get("requires_python", []):
        if not SpecifierSet(row["specifier"]).contains(environment.get("python_version", "")):
            raise ValueError(f"Selected Python does not satisfy {row['source']}: {row['specifier']}")
    return {"requests": sorted(set(requests)), "constraints": sorted(set(constraints)),
            "edits": edits, "extras": {k: sorted(v) for k, v in extras.items()}}


def latest(session, environment, project, name, direction=""):
    from .runner import environment_id

    identity = fingerprint(environment, project)
    for run in reversed(session.runs):
        if (run.tool != "dependency_resolve" or run.source != "executed"
                or run.environment_id != environment_id(session.target_python)):
            continue
        try:
            data = json.loads(run.stdout)
        except ValueError:
            continue
        if (data.get("context_fingerprint") == identity and data.get("dist") == canonicalize_name(name)
                and data.get("direction", "") == direction):
            return run, data
    return None, None


def collect(session, targets, timeout):
    from .evidence import project_index
    from .runner import environment_id, execute, redact_data

    if (len(targets) not in (1, 2) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", targets[0])):
        raise ValueError("A dependency trial needs one distribution name and an optional version range")
    name = canonicalize_name(targets[0])
    direction = targets[1] if len(targets) == 2 else ""
    SpecifierSet(direction)
    run = Run(tool="dependency_resolve", argv=["dependency-resolve", *targets], targets=targets,
              cwd=session.project_root, scope="dependencies:" + name,
              environment_id=environment_id(session.target_python))
    environment = session.environment
    if environment.get("_environment_id") != run.environment_id:
        run.status, run.stderr = "launch_failed", "Take a current environment snapshot first"
        return run
    _, project = project_index(session)
    result = {"dist": name, "direction": direction, "status": "not_resolved", "checks": [],
              "context_fingerprint": fingerprint(environment, project),
              "python": environment.get("python_version"), "application_verified": False,
              "python_hints": project.get("python_hints", [])}
    started = time.monotonic()
    deadline = started + min(timeout, MAX_SECONDS)
    uv = shutil.which("uv")
    try:
        plan = inputs(environment, project, name, direction)
        result.update(plan)
        with tempfile.TemporaryDirectory(prefix="fixfirst-resolve-") as folder:
            env_dir = Path(folder) / "env"
            python = str(env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))

            def step(label, argv, interpreter=python):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    run.status = "timeout"
                    raise ValueError("The dependency trial reached its total time limit")
                part = execute(argv, folder, "dependency_resolve", run.scope, interpreter,
                               remaining, extra_env={"PYTHONPATH": "", "PIP_CONFIG_FILE": os.devnull})
                result["checks"].append({"step": label, "status": part.status, "exit_code": part.exit_code,
                                         "output": (part.stdout + part.stderr)[-12000:]})
                if part.status != "completed" or part.exit_code != 0:
                    run.status = part.status
                    raise ValueError(f"{label} did not complete successfully; see the recorded output")
                return part.stdout

            create = ([uv, "venv", "--no-config", "--no-python-downloads", "--python", session.target_python,
                       str(env_dir)] if uv else [session.target_python, "-I", "-m", "venv", str(env_dir)])
            step("create environment", create, session.target_python)
            req_file, constraint_file = Path(folder) / "requirements.txt", Path(folder) / "constraints.txt"
            req_file.write_text("\n".join(plan["requests"]) + "\n", encoding="utf-8")
            constraint_file.write_text("\n".join(plan["constraints"]) + "\n", encoding="utf-8")
            install = ([uv, "pip", "install", "--no-config", "--python", python] if uv else
                       [python, "-I", "-m", "pip", "install", "--disable-pip-version-check"])
            step("install declared set", [*install, "--only-binary=:all:", "-r", str(req_file), "-c", str(constraint_file)])
            check = ([uv, "pip", "check", "--no-config", "--python", python] if uv else [python, "-I", "-m", "pip", "check"])
            step("check installed requirements", check)
            listing = ([uv, "pip", "list", "--no-config", "--python", python, "--format=json"] if uv else
                       [python, "-I", "-m", "pip", "list", "--format=json", "--disable-pip-version-check"])
            packages = json.loads(step("record versions", listing))
            chosen = {canonicalize_name(p["name"]): p["version"] for p in packages}
            installed = context(environment, project)["installed"]
            if name not in chosen or chosen[name] == installed.get(name):
                raise ValueError("The resolver did not select a different version of the blocked dependency")
            for edit in result["edits"]:
                req = Requirement(edit["before"])
                extra = "[" + ",".join(edit["extras"]) + "]" if edit["extras"] else ""
                edit["after"] = req.name + extra + "==" + chosen[name] + ("; " + edit["marker"] if edit["marker"] else "")
            result["resolved"] = [{"name": k, "version": v} for k, v in sorted(chosen.items())]
            result["install_requests"] = [
                k + ("[" + ",".join(plan["extras"][k]) + "]" if plan["extras"].get(k) else "") + "==" + v
                for k, v in sorted(chosen.items()) if k not in ("pip", "setuptools", "wheel") or k in plan["extras"]]
            result["status"] = "resolved"
    except (ValueError, OSError, KeyError, TypeError) as error:
        result["error"] = str(error)
    if result["status"] != "resolved" and result["checks"]:
        failure = result["checks"][-1]
        if failure["step"] == "install declared set":
            # uv explicitly distinguishes a missing wheel from unsatisfiable
            # version metadata. Do not turn our trial restriction into a claim
            # about the application or the named package we tried to change.
            plain = " ".join(re.sub(r"(?m)^[ \t│╰─▶]+", "", failure["output"]).split())
            atom = r"(?:===|==|~=|!=|>=|<=|>|<)\s*[A-Za-z0-9*.+!_-]+"
            wheel = re.search(
                r"(?<![\w.<>!=~,-])([A-Za-z0-9][A-Za-z0-9._-]*(?:\[[\w.,-]+\])?"
                + rf"(?:\s*{atom}(?:\s*,\s*{atom})*)?)\s+(?:has|have) no usable wheels\b",
                plain,
            )
            if wheel:
                try:
                    blocked = str(Requirement(wheel[1]))
                except ValueError:
                    blocked = None
            else:
                blocked = None
            if blocked:
                result["trial_restriction"] = "wheels_only"
                result["blocked_requirement"] = blocked
                result["error"] = f"The wheel-only trial cannot install {blocked}"
    # Listing availability uses uv's local catalog, not an interpreter download.
    if result["status"] != "resolved" and run.status == "completed" and uv and deadline - time.monotonic() > 1:
        for hint in result["python_hints"][:3]:
            request = hint["version"]
            if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", request):
                continue
            part = execute([uv, "python", "list", request, "--all-versions", "--output-format=json",
                            "--no-config", "--offline"], tempfile.gettempdir(), "dependency_resolve", run.scope,
                           session.target_python, min(5, max(0.01, deadline - time.monotonic())))
            hint["availability_check"] = {"status": part.status, "exit_code": part.exit_code,
                                          "output": (part.stdout + part.stderr)[-1000:]}
            if part.status == "completed" and part.exit_code == 0:
                try:
                    entries = json.loads(part.stdout)
                    hint["uv_available"] = bool(entries) if isinstance(entries, list) else None
                except ValueError:
                    pass
    run.stdout = json.dumps(redact_data(result), ensure_ascii=False)
    run.exit_code = 0 if run.status == "completed" else None
    run.duration_s = round(time.monotonic() - started, 3)
    return run


def advise(session, action, environment, project, name, direction=""):
    """Attach an explicit trial to a blocked action, or show its recorded result."""
    from .runner import activation_env
    from .workspace import shell

    trial_run, result = latest(session, environment, project, name, direction)
    if result:
        action.kind, action.check, action.targets, action.command = "manual_fix", None, [], []
        if result.get("status") == "resolved":
            edits = "; ".join(f"{e['source']}: replace {e['before']} with {e['after']}" for e in result["edits"])
            action.title = f"Review the tried {name} requirement change, then install the resolved set"
            action.explanation = (
                f"In a temporary environment using Python {result['python']}, the declared set installed "
                f"from wheels and passed the dependency consistency check. Proposed edits: {edits}. "
                "All other project version requirements were kept, and packages outside the declared dependency graph "
                "were held at their recorded versions. Review these edits first. This is an installation "
                "candidate: the application and its tests have NOT run with it; API migration may still be needed. "
                "After making the declaration edits, run the recorded installation below, then Check again "
                "with the original input/tests. Keep the tests unchanged. If this reveals another failure, "
                "handle that new evidence rather than reinstalling the old pin.")
            action.explanation += (
                " The trial ignores pip/uv configuration files; environment index settings still apply. "
                "If your usual installer needs an index or mirror configured in a file, confirm that it "
                "provides this set before applying it.")
            # Never suggest installing project dependencies into system Python.
            if activation_env(session.target_python):
                action.command = [session.target_python, "-m", "pip", "install", "--only-binary=:all:",
                                  *result["install_requests"]]
            else:
                env_dir = Path(session.project_root) / ".fixfirst-candidate-env"
                python = str(env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
                action.explanation += (
                    " Create a new, empty virtual environment: "
                    + shell([session.target_python, "-m", "venv", str(env_dir)])
                    + ". Then install: " + shell([python, "-m", "pip", "install", "--only-binary=:all:",
                                                 *result["install_requests"]])
                    + ". Select that interpreter for Check again. Do not reuse an existing environment directory.")
        else:
            action.title = f"Review why the {name} dependency trial did not complete"
            action.explanation = "The temporary trial did not produce an installation candidate: " + result.get("error", result["status"]) + "."
            if result.get("trial_restriction") == "wheels_only":
                blocked = result["blocked_requirement"]
                action.title = f"The wheel-only trial stopped at {blocked}"
                action.explanation += (
                    f" The immediate blocker is {blocked}, which has no usable wheel in the resolver output. "
                    "FixFirst's trial disables source builds. This result does not establish a version conflict "
                    "or an unsupported Python, and does not justify changing another package's pin. "
                    "Review that dependency's documented source-build or Conda installation route in a separate "
                    "environment, or obtain a supported wheel, before retrying the complete project setup.")
            for hint in result.get("python_hints", []):
                action.explanation += f" {hint['source']} mentions Python {hint['version']} (a documentation hint, not a verified environment)."
                if hint.get("uv_available") is False:
                    action.explanation += " The local uv catalog has no installation/download for that version on this platform; this route cannot be offered as an executable uv repair here."
                elif hint.get("availability_check", {}).get("exit_code") not in (None, 0):
                    action.explanation += " Checking that version with uv returned: " + hint["availability_check"]["output"].strip()
            failed = next((c for c in reversed(result.get("checks", [])) if c["exit_code"] != 0), None)
            if failed:
                action.explanation += " Resolver output: " + failed["output"][-2000:]
            action.explanation += " No declaration changes or installation command have been verified by this trial. Keep the original requirements until a reviewed alternative is available; do not repeat the same unresolved trial."
            action.explanation += " The trial ignores pip/uv configuration files (environment index settings still apply); a configured private index or mirror may give a different result."
        return trial_run
    try:
        inputs(environment, project, name, direction)
    except (ValueError, KeyError, TypeError) as error:
        action.explanation += " An automatic dependency trial is unavailable: " + str(error) + "."
        return None
    for hint in project.get("python_hints", [])[:3]:
        action.explanation += (f" {hint['source']} mentions Python {hint['version']}; "
                               "this is a documentation hint, not a verified or currently available environment.")
    action.kind, action.check, action.targets = "inspect", "dependency_resolve", [name, direction]
    action.explanation += (
        f" Use Try a dependency set (CLI: fixfirst run {session.session_id} {action.action_id}) "
        f"to propose replacing only the {name} version constraint. This explicitly tries a changed declaration "
        "in a temporary environment; it does not accept or edit that declaration. The other required project "
        "constraints stay in force, declared dependencies resolve together, and unrelated installed packages "
        "stay at their current versions. Downloads wheels; at most 5 minutes. Installation success is "
        "separate from running the original program/tests. The trial does not change your project or environment.")
    action.explanation += " The trial ignores pip/uv configuration files; environment index settings still apply."
    return None
