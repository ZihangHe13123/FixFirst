"""Static Django test-configuration leads and narrowly attributed failures.

Configuration presence is not execution or precedence. No project module is
imported. The two error mechanisms are documented in Django's settings and
application-registry docs; an early import during setup is a different cause.
"""

import ast
import configparser
import json
from pathlib import Path
import re
import shlex

from packaging.utils import canonicalize_name

from .pytest_settings import CONFIGS, _read, tomllib
from .runner import environment_id
from .tool_compatibility import _context, _normal, _package_file


MAX_ROWS = 50
MODULE = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", re.ASCII)
SETTING = "DJANGO_SETTINGS_MODULE"
SETTINGS_SOURCE = "https://docs.djangoproject.com/en/5.2/topics/settings/"
APPS_SOURCE = "https://docs.djangoproject.com/en/5.2/ref/applications/#troubleshooting"
PLUGIN_SOURCE = "https://pytest-django.readthedocs.io/en/latest/configuring_django.html"
UNCONFIGURED = re.compile(
    r"Requested (?:setting [A-Za-z_]\w*|settings), but settings are not configured\. "
    r"You must either define the environment variable DJANGO_SETTINGS_MODULE "
    r"or call settings\.configure\(\) before accessing settings\."
)


def _ini(text):
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read_string(text)
    parser.defaults().clear()
    return parser


def recorded_configuration(root: Path) -> dict:
    """Bounded literal candidates, never a claim about effective settings.

    Unsupported substitutions and malformed/unsafe files remain unknown. The
    reader is shared with warning-filter snapshots and rejects symlinks,
    nonregular files, paths outside root and inputs over 128 KB.
    """
    result = {"candidates": [], "unknown_sources": []}
    root = Path(root)
    try:
        if root.is_symlink() or not root.is_dir():
            return result
        root = root.resolve(strict=True)
    except (OSError, RuntimeError):
        return result

    def unknown(source):
        source = source[:300]
        if source not in result["unknown_sources"] and len(result["unknown_sources"]) < MAX_ROWS:
            result["unknown_sources"].append(source)

    def add(value, source, entrypoint):
        if (not isinstance(value, str) or len(value) > 200 or not MODULE.fullmatch(value.strip())
                or len(source) > 300 or len(entrypoint) > 300):
            unknown(source)
            return
        row = {"module": value.strip(), "source": source, "entrypoint": entrypoint}
        if row not in result["candidates"]:
            if len(result["candidates"]) < MAX_ROWS:
                result["candidates"].append(row)
            else:
                unknown("additional configuration candidates exceed the snapshot limit")

    configs = (*CONFIGS, ("pytest.toml", "pytest"), (".pytest.toml", "pytest"))
    texts = {}
    for name in dict.fromkeys([n for n, _ in configs] + ["Makefile", "runtests.py"]):
        text = _read(root, name)
        if text is None:
            if (root / name).exists() or (root / name).is_symlink():
                unknown(name + " (unreadable or unsafe)")
            continue
        texts[name] = text

    for name, section in configs:
        if name not in texts:
            continue
        try:
            if name in {"pytest.toml", ".pytest.toml"}:
                tables = [(section, tomllib.loads(texts[name]).get("pytest", {}))]
            elif name == "pyproject.toml":
                options = tomllib.loads(texts[name]).get("tool", {}).get("pytest", {})
                # Preserve both forms as separate sources; do not infer the
                # installed pytest version's selected configuration format.
                tables = [("tool.pytest", options),
                          (section, options.get("ini_options", {}) if isinstance(options, dict) else {})]
            else:
                parser = _ini(texts[name])
                tables = [(section, dict(parser[section]) if parser.has_section(section) else {})]
            for table, options in tables:
                if isinstance(options, dict) and SETTING in options:
                    add(options[SETTING], f"{name} [{table}]", "pytest-django configuration")
                if not isinstance(options, dict):
                    continue
                if "DJANGO_CONFIGURATION" in options:
                    unknown(f"{name} [{table}] DJANGO_CONFIGURATION (configuration class)")
                addopts = options.get("addopts", [])
                tokens = shlex.split(addopts) if isinstance(addopts, str) else addopts
                if isinstance(tokens, list) and all(isinstance(t, str) for t in tokens):
                    for index, token in enumerate(tokens):
                        if token == "--ds" or token.startswith("--ds="):
                            value = (tokens[index + 1] if index + 1 < len(tokens) else "") if token == "--ds" else token[5:]
                            add(value, f"{name} [{table}] addopts --ds", "pytest-django configuration")
                        elif token == "--dc" or token.startswith("--dc="):
                            unknown(f"{name} [{table}] addopts --dc (configuration class)")
        except (configparser.Error, ValueError, TypeError, AttributeError, RecursionError):
            unknown(name + " (parse error)")

    if "tox.ini" in texts:
        try:
            parser = _ini(texts["tox.ini"])
            for section in parser.sections()[:MAX_ROWS]:
                if section != "testenv" and not section.startswith("testenv:"):
                    continue
                for line in parser.get(section, "setenv", fallback="").splitlines():
                    if SETTING not in line:
                        continue
                    match = re.fullmatch(r"\s*DJANGO_SETTINGS_MODULE\s*=\s*(.*?)\s*", line)
                    source = f"tox.ini [{section}] setenv"
                    if match:
                        add(match[1], source, f"tox [{section}]")
                    else:
                        unknown(source)
        except (configparser.Error, ValueError, TypeError):
            unknown("tox.ini (parse error)")

    if "Makefile" in texts:
        target = ""
        for number, line in enumerate(texts["Makefile"].splitlines(), 1):
            match = re.fullmatch(r"([A-Za-z_][\w-]*):[^=]*", line)
            if match:
                target = match[1]
            elif line and not line[0].isspace() and not line.startswith("#"):
                target = ""
            if not line.startswith("\t") or not target or SETTING not in line:
                continue
            source = f"Makefile:{number} ({target})"
            try:
                tokens = shlex.split(line.lstrip("\t@-"), comments=True)
                # Only leading shell environment assignments. Embedded shell
                # programs, make expansions and exported variables are unknown.
                found = False
                for token in tokens:
                    if "=" not in token:
                        break
                    key, value = token.split("=", 1)
                    if key == SETTING:
                        add(value, source, "make " + target)
                        found = True
                if not found:
                    unknown(source)
            except ValueError:
                unknown(source)

    if "runtests.py" in texts:
        try:
            tree = ast.parse(texts["runtests.py"])
            # Restrict binding names; aliases/dynamic helpers remain unknown.
            has_os = any(isinstance(n, ast.Import) and any(a.name == "os" and a.asname in (None, "os")
                         for a in n.names) for n in tree.body)
            found = False
            for node in ast.walk(tree):
                value = None
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if ast.unparse(node.func) == "os.environ.setdefault" and len(node.args) >= 2:
                        if isinstance(node.args[0], ast.Constant) and node.args[0].value == SETTING:
                            value = node.args[1]
                elif isinstance(node, ast.Assign):
                    if any(isinstance(t, ast.Subscript) and ast.unparse(t.value) == "os.environ"
                           and isinstance(t.slice, ast.Constant) and t.slice.value == SETTING for t in node.targets):
                        value = node.value
                if value is not None:
                    found = True
                    add(value.value if has_os and isinstance(value, ast.Constant) else None,
                        f"runtests.py:{node.lineno}", "runtests.py")
            if SETTING in texts["runtests.py"] and not found:
                unknown("runtests.py (dynamic settings)")
        except (SyntaxError, ValueError, TypeError, RecursionError):
            unknown("runtests.py (parse error)")
    return result


def _signature(session, issue, run, environment):
    """Match one referenced failure, including its terminal Django operation."""
    context = _context(session, issue, run)
    if not context:
        return None
    text, paths, refs, events = context
    if len(events) != 1:
        return None
    event = events[0]
    # Typed exception metadata gives the terminal class/message and frame; a
    # matching string in an earlier chained error is never sufficient.
    records = [run.records[int(ref.rsplit(":", 1)[1])] for ref in refs if ":probe:" in ref]
    exceptions = [r for r in records if r.get("type") == "exception"]
    if len(exceptions) != 1:
        return None
    record = exceptions[0]
    if record.get("exception_module") != "django.core.exceptions":
        return None
    frames = record.get("traceback_frames", [])
    if not frames or not all(isinstance(f, dict) for f in frames):
        return None
    last = frames[-1]
    if last.get("file") != record.get("source_file"):
        return None
    message = record.get("exception_message", "")
    if (event.code == record.get("exception_type") == "ImproperlyConfigured"
            and isinstance(message, str) and UNCONFIGURED.fullmatch(message)
            and last.get("function") == "_setup"
            and _package_file(last.get("file", ""), "django/conf/__init__.py", session.project_root, environment)):
        return "settings_unconfigured", refs
    if (event.code == record.get("exception_type") == "AppRegistryNotReady"
            and message == "Apps aren't loaded yet." and last.get("function") == "check_apps_ready"
            and _package_file(last.get("file", ""), "django/apps/registry.py", session.project_root, environment)):
        registry = record.get("django_registry", {})
        if (not isinstance(registry, dict) or registry.get("global_registry") is not True
                or any(registry.get(key) is not False for key in ("apps_ready", "loading", "ready"))):
            return None  # Old snapshots and custom/in-progress registries remain unknown.
        if any((_package_file(f.get("file", ""), "django/__init__.py", session.project_root, environment)
                and f.get("function") == "setup")
               or (_package_file(f.get("file", ""), "django/apps/registry.py", session.project_root, environment)
                   and f.get("function") == "populate") for f in frames):
            return None
        return "apps_not_ready", refs
    return None


def observations(session, issues):
    from .evidence import current_environment, observed, project_index

    environment = current_environment(session)
    project_run, project = project_index(session)
    current = environment_id(session.target_python)
    env_run = next((r for r in session.runs if r.run_id == environment.get("_run_id")), None)
    if not (project_run and env_run and env_run.source == "executed" and env_run.environment_id == current
            and env_run.scope == "environment" and project_run.scope == "declarations:project"
            and all(r.cwd and _normal(r.cwd, session.project_root) == _normal(session.project_root, session.project_root)
                    for r in (env_run, project_run))
            and all(r.status == "completed" and r.exit_code == 0 and not r.truncated
                    for r in (env_run, project_run))):
        return [], {}
    packages = [p for p in environment.get("packages", []) if canonicalize_name(p.get("name", "")) == "django"]
    if (len(packages) != 1 or not packages[0].get("version")
            or {canonicalize_name(p) for p in environment.get("import_distributions", {}).get("django", [])} != {"django"}
            or "django" in {p.get("name") for p in project.get("local_modules", [])}):
        return [], {}
    plugin = any(canonicalize_name(p.get("name", "")) == "pytest-django" for p in environment.get("packages", []))
    facts, details = [], {}
    for issue in issues:
        if issue.tool not in {"pytest", "pytest_run"} or issue.environment_id != current:
            continue
        run = next((r for r in reversed(session.runs) if r.tool == issue.tool), None)
        if (not run or run.environment_id != current or run.source != "executed"
                or run.status != "completed" or run.truncated or run.exit_code in (None, 0)
                or run.scope != issue.scope or session.runs.index(env_run) >= session.runs.index(run)
                or _normal(run.cwd, session.project_root) != _normal(session.project_root, session.project_root)):
            continue
        pytest_versions = [p.get("version") for p in environment.get("packages", [])
                           if canonicalize_name(p.get("name", "")) == "pytest"]
        if run.tool_version not in ("", "unknown") and pytest_versions != [run.tool_version]:
            continue
        matches = [_signature(session, issue.model_copy(update={"event_ids": [event_id]}), run, environment)
                   for event_id in issue.event_ids]
        if not matches or any(m is None for m in matches) or len({m[0] for m in matches}) != 1:
            continue
        mechanism = matches[0][0]
        refs = list(dict.fromkeys(ref for match in matches for ref in match[1]))
        refs += [f"{env_run.run_id}:stdout:1", f"{project_run.run_id}:stdout:1"]
        facts.append(observed(issue.issue_id, "django_configuration", mechanism, refs))
        details[issue.issue_id] = {"mechanism": mechanism, "configuration": project.get("django_configuration", {}),
                                   "plugin_installed": plugin, "argv": run.argv}
    return facts, details


def refine(session, actions, details):
    from .evidence import current_environment, project_index
    from .persistent_configuration import SUPPORT_SOURCE, django_recipe, selection

    environment = current_environment(session)
    _, project = project_index(session)
    for action in actions:
        if "P86" not in action.rule_ids:
            continue
        matches = [details[i].get("django_configuration") for i in action.issue_ids if i in details]
        matches = [m for m in matches if m]
        if not matches:
            continue
        match = matches[0]
        config = match["configuration"] if isinstance(match["configuration"], dict) else {}
        candidates = [r for r in config.get("candidates", []) if isinstance(r, dict)
                      and isinstance(r.get("module"), str) and MODULE.fullmatch(r["module"])
                      and isinstance(r.get("source"), str) and isinstance(r.get("entrypoint"), str)][:MAX_ROWS]
        modules = {r["module"] for r in candidates}
        if candidates:
            action.explanation += " Recorded project candidates: " + "; ".join(
                f"{r['module']} in {r['source']} ({r['entrypoint']})" for r in candidates) + "."
            if len(modules) == 1 and not config.get("unknown_sources"):
                module = next(iter(modules))
                action.title = f"Check the project's test entrypoint for DJANGO_SETTINGS_MODULE={module}"
                action.explanation += (
                    f" Start by checking the recorded test entrypoint and whether {module} is the intended "
                    "importable test settings module. If running pytest directly, supply that confirmed module "
                    "through DJANGO_SETTINGS_MODULE before the test process starts, and check any overriding --ds option.")
            else:
                action.explanation += " Multiple or unresolved settings candidates remain; select the intended test environment before changing configuration."
        else:
            action.explanation += " No literal settings candidate was recorded. Inspect the project's documented test runner and test settings; no module name can be selected from this snapshot."
        if config.get("unknown_sources"):
            action.explanation += " Unresolved static sources: " + "; ".join(map(str, config["unknown_sources"][:MAX_ROWS])) + "."
        action.explanation += (
            " FixFirst's direct pytest check may bypass tox, Makefile or runtests.py setup. "
            "Recorded configuration does not prove what this run used; command-line options, environment "
            "variables and runtime setup can differ.")
        if match["plugin_installed"]:
            action.explanation += (
                " pytest-django is installed; check that it is loaded and receives the intended settings. "
                "When active it initializes Django; --ds overrides the environment, which overrides its config-file option.")
        elif any(r["entrypoint"] == "pytest-django configuration" for r in candidates):
            action.explanation += " pytest-django is not in the snapshot; its config option alone does not configure plain pytest. Check the project's declared test dependencies and runner."
        if match["mechanism"] == "apps_not_ready":
            action.title = "Check Django initialization before the failing model or registry access"
            action.explanation += (
                " The registry was unavailable at the failing access; this does not prove setup was never called. "
                "Check initialization order in the test runner. For a genuinely standalone runner, initialize "
                "Django after selecting settings and before model imports. Do not add django.setup() to reusable "
                "production imports or call it again during initialization.")
        action.explanation += " Sources: " + SETTINGS_SOURCE + " ; " + APPS_SOURCE + " ; " + PLUGIN_SOURCE
        action.verification = "Rerun the intended test entrypoint with the confirmed configuration, then repeat the original failing scope; an alternative runner passing does not verify the unchanged pytest invocation"
        if len(modules) == 1 and not config.get("unknown_sources"):
            selected, problem = selection(session, action, environment)
            recipe, requests = None, []
            if selected:
                recipe, requests, problem = django_recipe(selected, next(iter(modules)), environment, session.project_root)
            if recipe:
                action.kind = "manual_fix"
                action.title = f"Save DJANGO_SETTINGS_MODULE={next(iter(modules))} in {selected['file']}"
                if requests:
                    from .dependency_context import context

                    dependency_data = context(environment, project)
                    # An un-packaged script can have no dependency declaration at
                    # all; that absence is not a partially parsed constraint file.
                    project_notes = [n for n in project.get("notes", [])
                                     if n != "No supported static declaration file was found" or project.get("files")]
                    notes = [*dependency_data["notes"], *project_notes]
                    notes += [f"{row.get('source', 'project')} requires Python {row.get('specifier', 'unknown')}"
                              for row in project.get("requires_python", []) if row.get("status") != "satisfied"]
                    if notes:
                        problem = "Review the recorded dependency context before installing the plugin: " + "; ".join(notes)
                        recipe = None
                    else:
                        action.command = [session.target_python, "-m", "pip", "install", *requests]
                        action.title = f"Install pytest-django and save DJANGO_SETTINGS_MODULE={next(iter(modules))} in {selected['file']}"
                        recipe = ("First apply the companion installation command, which keeps the observed Django and pytest versions. "
                                  "Record pytest-django in the project's reviewed test dependencies for future environments. " + recipe
                                  + "The fixed plugin version is a compatibility candidate, not the earliest supported release or a verified project repair. "
                                  + f"Plugin compatibility source: {SUPPORT_SOURCE}. ")
                if recipe:
                    action.explanation = recipe + (
                        "pytest-django reads this setting and initializes Django; plain pytest does not. "
                        "Shell exports do not persist to a new shell. ") + action.explanation
                    action.verification = ("Run pip check and the original complete test command in a new shell with the same interpreter, "
                                           "without a temporary DJANGO_SETTINGS_MODULE export; keep the original test nodes and configuration policy")
            if not recipe:
                action.command = []
                action.title = f"Review prerequisites for saving DJANGO_SETTINGS_MODULE={next(iter(modules))}"
                action.explanation = (problem or "The recorded configuration cannot be selected safely.") + " " + action.explanation
    return _group_identical(actions, details)


def _group_identical(actions, details):
    """One configuration review can cover several failures, without dropping their evidence."""
    grouped, result = {}, []
    repair_fields = ("kind", "title", "explanation", "verification", "check", "targets", "cause",
                     "rule_ids", "command", "declaration_edits")
    for action in actions:
        key = None
        if "P86" in action.rule_ids and action.issue_ids:
            matches = [details.get(i, {}).get("django_configuration") for i in action.issue_ids]
            if all(isinstance(m, dict) and m.get("mechanism") in {"settings_unconfigured", "apps_not_ready"}
                   and isinstance(m.get("configuration"), dict) and isinstance(m.get("plugin_installed"), bool)
                   and isinstance(m.get("argv"), list) for m in matches):
                try:
                    context = [json.dumps(m, sort_keys=True, allow_nan=False) for m in matches]
                    if len(set(context)) == 1:
                        repair = {field: getattr(action, field) for field in repair_fields}
                        key = context[0], json.dumps(repair, sort_keys=True, allow_nan=False)
                except (TypeError, ValueError):
                    pass
        if key is None or key not in grouped:
            result.append(action)
            if key is not None:
                grouped[key] = action
            continue
        first = grouped[key]
        for field in ("issue_ids", "reason_refs", "preconditions"):
            setattr(first, field, list(dict.fromkeys([*getattr(first, field), *getattr(action, field)])))
        first.goal_impact = max(first.goal_impact, action.goal_impact)
        first.evidence_rank = max(first.evidence_rank, action.evidence_rank)
        first.cost = min(first.cost, action.cost)
    return result
