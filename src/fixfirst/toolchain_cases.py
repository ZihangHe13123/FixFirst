"""Toolchain cases: the broken part is the environment or a tool, not the project's own code.

The main diagnosis dataset (diagnosis_cases.py) injects one fault into a healthy project and runs it
in one shared environment. These scenarios cannot work that way: an old test tool crashing on a new
Python, a library the new Python no longer supports, a framework nobody configured. Each scenario
therefore names a *fault environment* (real packages pinned in a throwaway virtual environment) and
a *fix*: either another environment in which the unchanged project passes, or a small project edit,
or an environment variable. A case is kept only when

  * the fault is observed in the fault environment and its output shows the intended mechanism, and
  * the stated fix is run for real and makes the whole test run pass.

Every distinct fault environment becomes one sub-dataset (cases.jsonl + environment.json +
manifest.json), because a stored session shares one environment snapshot. ``load_rows`` joins them.

Labels follow the root cause of the mechanism, not the error text: an old tool crashing on a new
Python is ``version_incompatibility``, an unconfigured framework ``config_missing``. The scenarios
were written after the 2026-10 held-out run showed these mechanisms; they are development data and
say nothing about generalisation to projects nobody has seen.

Cases whose fault shows only as an unparsed ``tool_failure`` (pytest died before collection and
printed no recognisable exception line) are listed under ``unparsed`` in the manifest, not stored:
the parser has to understand them first, and regenerating the suite then adds them.
"""

from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

from . import diagnosis_cases as dc
from .models import now
from .service import create_session, scan

HEALTHY_ENV = "t8"


@dataclass(frozen=True)
class Env:
    key: str
    python: str
    packages: tuple


ENV_LIST = (
    Env("t8", "3.12", ("pytest==8.3.5",)),
    Env("t625-py110", "3.12", ("pytest==6.2.5", "py==1.10.0")),
    Env("t713-py110", "3.12", ("pytest==7.1.3", "py==1.10.0")),
    Env("t625-py111", "3.12", ("pytest==6.2.5", "py==1.11.0")),
    Env("t701-py111", "3.12", ("pytest==7.0.1", "py==1.11.0")),
    Env("t722", "3.12", ("pytest==7.2.2",)),
    Env("t744", "3.12", ("pytest==7.4.4",)),
    Env("t8-nose", "3.12", ("pytest==8.3.5", "nose==1.3.7")),
    Env("t8-nose-py311", "3.11", ("pytest==8.3.5", "nose==1.3.7")),
    Env("t8-six115", "3.12", ("pytest==8.3.5", "six==1.15.0")),
    Env("t8-six117", "3.12", ("pytest==8.3.5", "six==1.17.0")),
    Env("t8-setuptools81", "3.12", ("pytest==8.3.5", "setuptools==81.0.0")),
    Env("t8-setuptools84", "3.12", ("pytest==8.3.5", "setuptools==84.0.0")),
    Env("t8-django", "3.12", ("pytest==8.3.5", "django>=5,<6")),
    Env("t8-django-pytest", "3.12", ("pytest==8.3.5", "django>=5,<6", "pytest-django")),
)
ENVS = {e.key: e for e in ENV_LIST}


@dataclass(frozen=True)
class ToolScenario:
    scenario_id: str
    label: str
    knowledge: bool  # whether the knowledge base covers the fault (checked against v0.7.0)
    description: str
    family: str
    fault_env: str
    shows: str  # regular expression found in the failing run's output
    apply: object
    fix_env: str = ""  # an environment where the unchanged project passes
    fix: object = None  # a project edit that makes it pass (run in fix_env, or the fault env)
    fix_variables: tuple = ()  # environment variables that make it pass
    templates: tuple = ()  # restrict to these templates (empty = all)


TOOL_SCENARIOS: list[ToolScenario] = []


def t(scenario_id, label, family, fault_env, shows, description, knowledge=False, **options):
    def register(function):
        TOOL_SCENARIOS.append(ToolScenario(
            scenario_id, label, knowledge, description, family, fault_env, shows, function, **options))
        return function

    return register


# ---------------------------------------------------------------------------------------
# helpers shared by the scenarios
# ---------------------------------------------------------------------------------------

NO_PYTHONPATH_INI = tuple(x.name for x in dc.TEMPLATES if "pythonpath" not in x.ini)
SETTINGS = (
    'SECRET_KEY = "test"\nINSTALLED_APPS = ["django.contrib.contenttypes"]\n'
    'DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}\n'
    "USE_TZ = True\nDEBUG = False\n"
)


def pin(p, env_key):
    """requirements.txt records the environment's pins, like a real project that pinned its stack."""
    (p.root / "requirements.txt").write_text("\n".join(ENVS[env_key].packages) + "\n", encoding="utf-8")


def ini_options(p) -> dict:
    path = p.root / "pytest.ini"
    options = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("["):
                key, value = line.split("=", 1)
                options[key.strip()] = value.strip()
    return options


def write_pytest_config(p, filename, extra):
    """Write the project's pytest options (the template's plus ``extra``) into one config file."""
    options = {**ini_options(p), **extra}
    (p.root / "pytest.ini").unlink(missing_ok=True)
    if filename == "pytest.ini":
        body = "[pytest]\n" + "".join(f"{k} = {v}\n" for k, v in options.items())
        (p.root / "pytest.ini").write_text(body, encoding="utf-8")
    elif filename == "setup.cfg":
        body = "[tool:pytest]\n" + "".join(f"{k} = {v}\n" for k, v in options.items())
        (p.root / "setup.cfg").write_text(body, encoding="utf-8")
    elif filename == "pyproject.toml":
        lines = ["", "[tool.pytest.ini_options]"]
        for key, value in options.items():
            lines.append(f"{key} = " + json.dumps(value.split()))
        path = p.root / "pyproject.toml"
        path.write_text(path.read_text(encoding="utf-8") + "\n".join(lines) + "\n", encoding="utf-8")
    else:
        raise ValueError(filename)


def error_filter(p, filename="pytest.ini", value="error"):
    write_pytest_config(p, filename, {"filterwarnings": value})


def old_tool_project(p, env_key, filename="pytest.ini", value="error"):
    pin(p, env_key)
    error_filter(p, filename, value)


# ---------------------------------------------------------------------------------------
# family 1: an old test tool crashes on Python 3.12 (version_incompatibility)
# ---------------------------------------------------------------------------------------

@t("tt_py_spec_t625", "version_incompatibility", "old_test_tool", "t625-py110", r"AttributeError: __spec__",
   "pytest 6.2.5 with py 1.10.0 on Python 3.12: importing pytest fails inside py's vendored apipkg",
   fix_env="t744")
def _(p):
    pin(p, "t625-py110")


@t("tt_py_spec_t713", "version_incompatibility", "old_test_tool", "t713-py110", r"AttributeError: __spec__",
   "pytest 7.1.3 with py 1.10.0 on Python 3.12: the same import failure with another pytest version",
   fix_env="t744")
def _(p):
    pin(p, "t713-py110")


@t("tt_ast_str_ini", "version_incompatibility", "old_test_tool", "t722", r"ast\.Str is deprecated",
   "pytest 7.2.2 rewrites assertions with ast.Str, which Python 3.12 warns about; pytest.ini makes warnings errors",
   fix_env="t744")
def _(p):
    old_tool_project(p, "t722")


@t("tt_ast_str_t625", "version_incompatibility", "old_test_tool", "t625-py111", r"ast\.Str is deprecated",
   "pytest 6.2.5 (2021 pin) with warnings as errors on Python 3.12", fix_env="t744", templates=NO_PYTHONPATH_INI)
def _(p):
    old_tool_project(p, "t625-py111")


@t("tt_ast_str_setupcfg", "version_incompatibility", "old_test_tool", "t722", r"ast\.Str is deprecated",
   "the same crash with the error filter in setup.cfg [tool:pytest]", fix_env="t744")
def _(p):
    old_tool_project(p, "t722", "setup.cfg")


@t("tt_ast_str_toml", "version_incompatibility", "old_test_tool", "t722", r"ast\.Str is deprecated",
   "the same crash with the error filter in pyproject.toml [tool.pytest.ini_options]", fix_env="t744")
def _(p):
    old_tool_project(p, "t722", "pyproject.toml")


@t("tt_ast_str_conftest", "version_incompatibility", "old_test_tool", "t722", r"ast\.Str is deprecated",
   "the crash happens while loading conftest.py, which pytest reports as an ImportError", fix_env="t744")
def _(p):
    old_tool_project(p, "t722")
    p.fixture("\n\ndef check(value):\n    assert value is not None\n    return value")


@t("tt_ast_str_narrow", "version_incompatibility", "old_test_tool", "t701-py111", r"ast\.Str is deprecated",
   "pytest 7.0.1 with a narrow filter (error::DeprecationWarning)", fix_env="t744")
def _(p):
    old_tool_project(p, "t701-py111", value="error::DeprecationWarning")


@t("tt_own_warning", "code_defect", "old_test_tool", "t8", r"DeprecationWarning: legacy helper is deprecated",
   "the project itself raises a DeprecationWarning at import time and warnings are errors; the tool is current")
def _(p):
    pin(p, "t8")
    error_filter(p)
    p.imports("import warnings\n\nwarnings.warn('legacy helper is deprecated', DeprecationWarning)")


@t("tt_shadow_pluggy", "local_module", "old_test_tool", "t8", r"cannot import name 'HookimplMarker' from 'pluggy'",
   "a project file named pluggy.py hides the real pluggy, so pytest itself cannot start")
def _(p):
    pin(p, "t8")
    p.write("pluggy.py", "VALUE = 1\n")


# ---------------------------------------------------------------------------------------
# family 2: a library or tool the newer Python no longer supports
# ---------------------------------------------------------------------------------------

@t("ol_nose_imp", "version_incompatibility", "old_library", "t8-nose", r"No module named 'imp'",
   "nose 1.3.7 imports the imp module, which Python 3.12 removed; nose is no longer maintained", knowledge=True,
   fix_env="t8-nose-py311")
def _(p):
    pin(p, "t8-nose")
    p.imports("import nose")


@t("ol_six_moves", "version_incompatibility", "old_library", "t8-six115", r"No module named 'six\.moves'",
   "six 1.15.0 cannot provide six.moves on Python 3.12; six 1.16 fixed it", fix_env="t8-six117")
def _(p):
    pin(p, "t8-six115")
    p.imports("from six.moves import urllib\n\nPARSER = urllib.parse")


# ---------------------------------------------------------------------------------------
# family 3: pkg_resources (Python 3.12 environments have no setuptools; setuptools 82 dropped it)
# ---------------------------------------------------------------------------------------

@t("st_pkg_resources_absent", "missing_dependency", "setuptools", "t8", r"No module named 'pkg_resources'",
   "pkg_resources is imported but the environment has no setuptools (Python 3.12 virtual environments omit it)",
   fix_env="t8-setuptools81")
def _(p):
    pin(p, "t8")
    p.imports("import pkg_resources\n\nREQUIRED = pkg_resources")


@t("st_pkg_resources_runtime", "missing_dependency", "setuptools", "t8", r"No module named 'pkg_resources'",
   "pkg_resources is imported inside a function, so the failure appears when the test calls it",
   fix_env="t8-setuptools81")
def _(p):
    pin(p, "t8")
    p.body("    import pkg_resources\n\n    pkg_resources.working_set")


@t("st_get_distribution", "missing_dependency", "setuptools", "t8", r"No module named 'pkg_resources'",
   "a command-line helper reads its version with pkg_resources.get_distribution", fix_env="t8-setuptools81")
def _(p):
    pin(p, "t8")
    p.imports("from pkg_resources import get_distribution\n\nVERSION = get_distribution('pip').version")


@t("st_pkg_resources_removed", "version_incompatibility", "setuptools", "t8-setuptools84",
   r"No module named 'pkg_resources'",
   "setuptools is installed, but setuptools 82 and later no longer contain pkg_resources",
   fix_env="t8-setuptools81")
def _(p):
    pin(p, "t8-setuptools84")
    p.imports("import pkg_resources\n\nREQUIRED = pkg_resources")


# ---------------------------------------------------------------------------------------
# family 4: Django is installed but nobody told the tests which settings to use (config_missing)
# ---------------------------------------------------------------------------------------

DJANGO_VARIABLE = (("DJANGO_SETTINGS_MODULE", "settings_x"),)
NOT_CONFIGURED = r"settings are not configured"


def django_project(p, env_key="t8-django"):
    pin(p, env_key)
    p.write("settings_x.py", SETTINGS)


@t("dj_unset_tox", "config_missing", "django", "t8-django", NOT_CONFIGURED,
   "tests read django.conf.settings at import; tox.ini sets DJANGO_SETTINGS_MODULE but plain pytest does not",
   fix_variables=DJANGO_VARIABLE)
def _(p):
    django_project(p)
    p.write("tox.ini", "[tox]\nenvlist = py312\n\n[testenv]\ndeps =\n    pytest\n    django\n"
                       "setenv =\n    DJANGO_SETTINGS_MODULE = settings_x\ncommands = pytest {posargs}\n")
    p.imports("from django.conf import settings\n\nDEBUG_FLAG = settings.DEBUG")


@t("dj_unset_runtests", "config_missing", "django", "t8-django", NOT_CONFIGURED,
   "a runtests.py script exports DJANGO_SETTINGS_MODULE; running pytest directly skips it",
   fix_variables=DJANGO_VARIABLE)
def _(p):
    django_project(p)
    p.write("runtests.py", "import os\nimport sys\n\nimport pytest\n\n"
                           "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings_x')\nsys.exit(pytest.main(sys.argv[1:]))\n")
    p.imports("from django.conf import settings\n\nDEBUG_FLAG = settings.DEBUG")


@t("dj_unset_makefile", "config_missing", "django", "t8-django", NOT_CONFIGURED,
   "the Makefile test target sets DJANGO_SETTINGS_MODULE; calling pytest by hand does not",
   fix_variables=DJANGO_VARIABLE)
def _(p):
    django_project(p)
    p.write("Makefile", "test:\n\tDJANGO_SETTINGS_MODULE=settings_x python -m pytest\n")
    p.imports("from django.conf import settings\n\nDEBUG_FLAG = settings.DEBUG")


@t("dj_unset_runtime", "config_missing", "django", "t8-django", NOT_CONFIGURED,
   "the settings are read inside a function, so the failure appears when the test runs, not at collection",
   fix_variables=DJANGO_VARIABLE)
def _(p):
    django_project(p)
    p.write("tox.ini", "[testenv]\nsetenv =\n    DJANGO_SETTINGS_MODULE = settings_x\ncommands = pytest {posargs}\n")
    p.body("    from django.conf import settings\n\n    settings.DEBUG")


@t("dj_unset_pytest_django", "config_missing", "django", "t8-django-pytest", NOT_CONFIGURED,
   "pytest-django is installed but no DJANGO_SETTINGS_MODULE is given anywhere the plugin reads",
   fix_variables=DJANGO_VARIABLE)
def _(p):
    django_project(p, "t8-django-pytest")
    p.write("tox.ini", "[testenv]\nsetenv =\n    DJANGO_SETTINGS_MODULE = settings_x\ncommands = pytest {posargs}\n")
    p.imports("from django.conf import settings\n\nDEBUG_FLAG = settings.DEBUG")


def _django_setup(p):
    path = p.root / p.t.conftest
    text = path.read_text(encoding="utf-8")
    marker = "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings_x')"
    path.write_text(text.replace(marker, marker + "\n\nimport django\n\ndjango.setup()", 1), encoding="utf-8")


@t("dj_apps_not_ready", "config_missing", "django", "t8-django", r"Apps aren't loaded yet",
   "the settings variable is set but django.setup() is never called, so importing a model fails",
   fix=_django_setup)
def _(p):
    django_project(p)
    p.fixture("\n\nimport os\n\nos.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings_x')")
    p.imports("from django.contrib.contenttypes.models import ContentType\n\nMODEL = ContentType")


# the tt_own_warning and tt_shadow_pluggy fixes edit the project instead of the environment
def _fix_own_warning(p):
    path = p.root / p.t.service
    path.write_text(path.read_text(encoding="utf-8").replace(
        "warnings.warn('legacy helper is deprecated', DeprecationWarning)", "pass"), encoding="utf-8")


def _fix_shadow(p):
    (p.root / "pluggy.py").rename(p.root / "pluggy_local.py")


_FIXES = {"tt_own_warning": _fix_own_warning, "tt_shadow_pluggy": _fix_shadow}
TOOL_SCENARIOS[:] = [
    ToolScenario(**{**s.__dict__, "fix": _FIXES.get(s.scenario_id, s.fix)}) for s in TOOL_SCENARIOS
]
IDS = [s.scenario_id for s in TOOL_SCENARIOS]
if len(set(IDS)) != len(IDS):
    raise ValueError("duplicate toolchain scenario ids")


# ---------------------------------------------------------------------------------------
# building the environments and the dataset
# ---------------------------------------------------------------------------------------

def run(argv, cwd=None, env=None, timeout=900):
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, errors="replace", timeout=timeout)


def clean_env(home: Path, extra=()) -> dict:
    return {"PATH": "/usr/bin:/bin", "HOME": str(home), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
            "NO_COLOR": "1", **dict(extra)}


def build_env(root: Path, env: Env) -> Path:
    uv = shutil.which("uv")
    if not uv:
        raise ValueError("uv is required to build the toolchain environments")
    folder = root / env.key
    if folder.exists():
        return folder
    # --seed puts pip into the environment, as it is in every real user's environment
    result = run([uv, "venv", "-q", "--seed", "--python", env.python, str(folder)])
    if result.returncode:
        raise ValueError(f"cannot create {env.key}: {result.stderr[-300:]}")
    result = run([uv, "pip", "install", "-q", "--python", str(folder / "bin" / "python"), *env.packages])
    if result.returncode:
        raise ValueError(f"cannot install {env.packages} for {env.key}: {result.stderr[-400:]}")
    return folder


def freeze(folder: Path) -> list[str]:
    uv = shutil.which("uv")
    result = run([uv, "pip", "freeze", "--python", str(folder / "bin" / "python")])
    return sorted(line for line in result.stdout.splitlines() if line.strip())


def passes(project: Path, python: Path, variables=()) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="fixfirst-fix-") as home:
        result = run([str(python), "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=project,
                     env=clean_env(Path(home), variables))
    return result.returncode == 0 and " passed" in result.stdout, (result.stdout + result.stderr)[-300:]


def check_fix(scenario: ToolScenario, project: Path, template, index, envs: Path) -> dict:
    """Run the stated fix for real: the whole test run must pass afterwards."""
    with tempfile.TemporaryDirectory(prefix="fixfirst-copy-") as copy:
        target = Path(copy) / "project"
        shutil.copytree(project, target)
        if scenario.fix:
            scenario.fix(dc.Project(target, template, index))
        python = envs / (scenario.fix_env or scenario.fault_env) / "bin" / "python"
        ok, tail = passes(target, python, scenario.fix_variables)
    return {"fix_env": scenario.fix_env or scenario.fault_env, "project_edit": bool(scenario.fix),
            "variables": [k for k, _ in scenario.fix_variables], "passed": ok, "output_tail": "" if ok else tail}


def build_dataset(output: Path, work: Path | None = None, keep_work: bool = False, only=()):
    """Build the toolchain suite. ``work`` holds the virtual environments (large, not part of the result)."""
    output = output.expanduser().resolve()
    if output.exists():
        raise ValueError("Dataset directory already exists; choose a new --output")
    work = (work or Path(tempfile.mkdtemp(prefix="fixfirst-toolchain-"))).expanduser().resolve()
    work.mkdir(parents=True, exist_ok=True)
    envs = work / "envs"
    envs.mkdir(exist_ok=True)
    output.mkdir(parents=True)
    started = time.monotonic()
    chosen = [s for s in TOOL_SCENARIOS if not only or s.scenario_id in only]
    manifest = {
        "schema_version": 1,
        "created_at": now(),
        "origin": "toolchain_injection",
        "suite": "toolchain",
        "templates": [x.name for x in dc.TEMPLATES],
        "datasets": [],
        "environments": {},
        "scenarios": [
            {"id": s.scenario_id, "label": s.label, "knowledge": s.knowledge, "family": s.family,
             "description": s.description, "fault_env": s.fault_env, "fix_env": s.fix_env,
             "fix_variables": [k for k, _ in s.fix_variables], "project_edit": bool(s.fix)}
            for s in chosen
        ],
        "cases": [],
        "rejected": [],
        "unparsed": [],
        "limitations": (
            "Real runs in pinned virtual environments, one fix verified per case. Scenarios were written "
            "after the 2026-10 held-out run showed these mechanisms, so results on them are development "
            "results, never held-out ones. They are not a sample of naturally occurring failures."
        ),
    }
    try:
        pristine = work / "templates"
        reference = build_env(envs, ENVS[HEALTHY_ENV])
        for template in dc.TEMPLATES:
            dc.build_template(pristine / template.name, template)
            baseline = create_session(pristine / template.name, str(reference / "bin" / "python"), template.name,
                                      goal="pass_tests")
            scan(baseline, dc.CHECKS)
            if baseline.goal_status != "achieved" or any(i.status == "open" for i in baseline.issues):
                raise ValueError(f"Template {template.name} is not healthy: {[i.title for i in baseline.issues]}")
        for env_key in sorted({s.fault_env for s in chosen}):
            folder = build_env(envs, ENVS[env_key])
            manifest["environments"][env_key] = {"python": ENVS[env_key].python, "packages": freeze(folder)}
            for fix_key in sorted({s.fix_env for s in chosen if s.fault_env == env_key and s.fix_env}):
                manifest["environments"].setdefault(
                    fix_key, {"python": ENVS[fix_key].python, "packages": freeze(build_env(envs, ENVS[fix_key]))})
            sub = output / env_key
            sub.mkdir()
            cases = sub / "cases.jsonl"
            used = False
            for template in dc.TEMPLATES:
                for scenario in (s for s in chosen if s.fault_env == env_key):
                    if scenario.templates and template.name not in scenario.templates:
                        continue
                    row = build_case(scenario, template, pristine, work, folder, envs, sub, manifest)
                    if row:
                        used = True
                        with cases.open("a", encoding="utf-8") as stream:
                            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            if used:
                manifest["datasets"].append(env_key)
            else:
                shutil.rmtree(sub)
    finally:
        manifest["seconds"] = round(time.monotonic() - started, 1)
        dc.write(output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        if not keep_work:
            shutil.rmtree(work, ignore_errors=True)
    return output / "manifest.json"


def build_case(scenario, template, pristine, work, folder, envs, sub, manifest):
    case_id = f"{template.name}--{scenario.scenario_id}"
    project = work / "projects" / scenario.fault_env / case_id
    shutil.copytree(pristine / template.name, project)
    index = dc.TEMPLATES.index(template)
    scenario.apply(dc.Project(project, template, index))
    session = create_session(project, str(folder / "bin" / "python"), case_id, goal="pass_tests")
    scan(session, dc.CHECKS)
    runs = [r for r in session.runs if r.tool == "pytest_run"]
    text = "\n".join(f"{r.stdout}\n{r.stderr}" for r in runs)
    failures = [i for i in session.issues if i.status == "open" and i.tool == "pytest_run"]
    typed = [i for i in failures if i.kind != "tool_failure"]
    if not failures or not re.search(scenario.shows, text):
        manifest["rejected"].append({"case_id": case_id, "reason": "intended mechanism not observed",
                                     "issues": [f"{i.kind}:{i.title[:100]}" for i in session.issues]})
        print(f"  {case_id}: rejected (mechanism not observed)", flush=True)
        return None
    fix = check_fix(scenario, project, template, index, envs)
    if not fix["passed"]:
        manifest["rejected"].append({"case_id": case_id, "reason": "the stated fix does not make the tests pass",
                                     "fix": fix})
        print(f"  {case_id}: rejected (fix does not pass)", flush=True)
        return None
    if not typed:
        manifest["unparsed"].append({"case_id": case_id, "scenario": scenario.scenario_id, "label": scenario.label,
                                     "issues": [f"{i.kind}:{i.title[:100]}" for i in failures], "fix": fix})
        print(f"  {case_id}: fault seen only as tool_failure (not stored)", flush=True)
        return None
    stored, environment = dc.portable(session, project, prefix=str(folder))
    shared = sub / "environment.json"
    if not shared.exists():
        dc.write(shared, json.dumps(environment, ensure_ascii=False, indent=1))
    elif json.loads(shared.read_text(encoding="utf-8")) != environment:
        raise ValueError("The environment changed during generation")
    manifest["cases"].append({"case_id": case_id, "template": template.name, "scenario": scenario.scenario_id,
                              "label": scenario.label, "dataset": scenario.fault_env, "issues": len(typed),
                              "fix": {k: v for k, v in fix.items() if k != "output_tail"}})
    print(f"  {case_id}: {scenario.label} ({len(typed)} issue(s))", flush=True)
    return {"case_id": case_id, "template": template.name, "scenario": scenario.scenario_id,
            "label": scenario.label, "knowledge_covered": scenario.knowledge, "family": scenario.family,
            "session": stored}


def load_rows(output: Path, skip=()) -> list[dict]:
    """The evaluation rows of every sub-dataset (evaluation.load_rows), with the family and sub-dataset attached."""
    from .evaluation import load_rows as load_one

    output = Path(output)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    families = {s["id"]: s["family"] for s in manifest["scenarios"]}
    rows = []
    for name in manifest["datasets"]:
        for row in load_one(output / name, skip):
            row["family"] = families[row["scenario"]]
            row["dataset"] = name
            rows.append(row)
    return rows
