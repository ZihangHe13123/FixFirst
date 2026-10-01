"""Acceptance cases A-G from the field trial (Claude, 2026-09-30), written before any fix is run.

Each case rebuilds, in a fresh Python 3.12 venv, the state the trial met, runs FixFirst through the
command line given with --fixfirst, and checks the expectation below. A command in FixFirst's first
step is executed in the case's own venv, as a user would. Development material only.

  python experiments/field_trial/acceptance.py --out RUNS --fixfirst /path/to/venv/bin/fixfirst --tag TAG [--only A C]

RUNS must be a new folder outside any project. Needs uv, network access to PyPI and GitHub (case C
clones gothinkster/django-realworld-example-app at 29c9d42). Results: RUNS/TAG/results.json.
"""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess

FLASK_SQLA_APP = "from flask_sqlalchemy import SQLAlchemy\n\ndb = SQLAlchemy()\n"
IMPORT_TEST = "import app\n\n\ndef test_import():\n    assert app\n"

CASES = {
    "A": {
        "title": "Upgrade must not overshoot into a release that breaks a declared, co-installed pin",
        "files": {"requirements.txt": "SQLAlchemy==1.1.9\nFlask_SQLAlchemy==2.2\nFlask\n",
                  "app.py": FLASK_SQLA_APP, "test_app.py": IMPORT_TEST},
        "setup": [["SQLAlchemy==1.1.9", "Flask_SQLAlchemy==2.2", "flask"]],
        "goal": ["--goal", "pass_tests"],
        "invalid": "Baseline 0eb87e5 showed this setup cannot see the overshoot: after SQLAlchemy jumps to 2.x, "
                   "Flask-SQLAlchemy 2.2 first fails on Flask 3's missing _app_ctx_stack, masking _BindParamClause. "
                   "In the trial (C2) the broken co-installed package was alembic 1.4.3. Replaced by A2; kept, not run "
                   "by default.",
        "expect": "First failure: SQLAlchemy 1.1.9 uses collections.MutableMapping (removed in Python 3.10). "
                  "After running the first step's command, the MutableMapping error is gone and the next failure "
                  "is not the overshoot symptom (flask_sqlalchemy 2.2 unable to import _BindParamClause from "
                  "SQLAlchemy >= 2). A first step without a command must say which pin to relax (reviewed by hand).",
    },
    "A2": {
        "title": "Upgrade must not overshoot into a release that breaks a co-installed package (corrected A)",
        "files": {"requirements.txt": "SQLAlchemy==1.1.9\nalembic\n",
                  "app.py": "import sqlalchemy\nimport alembic.ddl\n", "test_app.py": IMPORT_TEST},
        "setup": [["SQLAlchemy==1.1.9", "alembic"]],
        "goal": ["--goal", "pass_tests"],
        "expect": "First failure: SQLAlchemy 1.1.9 uses collections.MutableMapping. pip paired it with alembic 1.4.3, "
                  "which needs SQLAlchemy's pre-2.0 _BindParamClause (the trial's C2 mechanism). After running the "
                  "first step's command the tests must pass: the upgrade stays below the release that breaks alembic, "
                  "or upgrades alembic with it. A first step without a command is reviewed by hand.",
    },
    "B": {
        "title": "A name the newer release introduced must lead to an upgrade, never an older search",
        "files": {"requirements.txt": "Flask-SQLAlchemy==3.1.1\nFlask\n", "app.py": FLASK_SQLA_APP,
                  "test_app.py": IMPORT_TEST},
        "setup": [["Flask-SQLAlchemy==3.1.1", "flask"], ["SQLAlchemy==1.4.54"]],
        "goal": ["--goal", "pass_tests"],
        "expect": "Flask-SQLAlchemy 3.1.1 requires SQLAlchemy>=2.0.16 (pip check says so); SQLAlchemy 1.4.54 lacks "
                  "sqlalchemy.orm.DeclarativeBase. The first step must not search or install an older SQLAlchemy; "
                  "running its command must leave pip check clean and the tests passing.",
    },
    "B2": {
        "title": "Same case as B, with a corrected direction check",
        "files": {"requirements.txt": "Flask-SQLAlchemy==3.1.1\nFlask\n", "app.py": FLASK_SQLA_APP,
                  "test_app.py": IMPORT_TEST},
        "setup": [["Flask-SQLAlchemy==3.1.1", "flask"], ["SQLAlchemy==1.4.54"]],
        "goal": ["--goal", "pass_tests"],
        "expect": "Same expectation as B. B's checker read any 'sqlalchemy<' in the command as a downgrade, so an "
                  "upgrade bounded above (sqlalchemy<3,>=2.0.16) failed. B2 fails only if the command's range admits "
                  "no release >= 2.0.16 or the text searches older releases; B and its results are kept unchanged.",
    },
    "C": {
        "title": "Release search must respect the project's declared version and other constraints",
        "clone": ("https://github.com/gothinkster/django-realworld-example-app.git", "29c9d42"),
        "setup": [["-r", "requirements.txt"]],
        "goal": ["--goal", "run_project", "--script", "manage.py", "--arg", "migrate"],
        "expect": "Django 1.10.5 (declared ==1.10.5) cannot import django.utils.six.moves on Python 3.12. Neither the "
                  "first step's command nor a release search it offers may install a Django older than the declared "
                  "1.10.5 (the trial got 1.5.12, then an unbounded upgrade). An interpreter route or an explicit "
                  "'no release fits the declaration on this Python' passes.",
    },
    "D1": {
        "title": "Several missing declared dependencies are installed by one step",
        "files": {"requirements.txt": "rich\nclick\nPyYAML\nattrs\ntabulate\n",
                  "app.py": "import attr\nimport click\nimport rich\nimport tabulate\nimport yaml\n",
                  "test_app.py": IMPORT_TEST},
        "setup": [],
        "goal": ["--goal", "pass_tests"],
        "expect": "None of the five declared packages is installed. Running the first step's command once must leave "
                  "no missing declared dependency (the trial needed one round per package).",
    },
    "D2": {
        "title": "A failed pip install log names the pin that cannot build",
        "files": {"requirements.txt": "pandas==1.1.0\nrich\n",
                  "app.py": "import pandas\nimport rich\n", "test_app.py": IMPORT_TEST},
        "setup": [],
        "pip_log": True,
        "goal": ["--goal", "pass_tests"],
        "invalid": "Superseded by D2b after Codex's review: this check failed every step without a command, although "
                   "the handoff allows 'relax that pin', and it passed a command that silently installs another pandas "
                   "while requirements.txt still pins pandas==1.1.0. Kept with its baseline; not run by default.",
        "expect": "pip install -r requirements.txt fails because pandas==1.1.0 cannot build on Python 3.12, so nothing "
                  "is installed; the log is imported with fixfirst import --tool pip_install. The first step must name "
                  "pandas 1.1.0 (or its build failure) as the blocker, and running its command must leave pandas and "
                  "rich importable.",
    },
    "D2b": {
        "title": "A failed pip install names the pin that cannot build, without silently bypassing it (corrected D2)",
        "files": {"requirements.txt": "pandas==1.1.0\nrich\n",
                  "app.py": "import pandas\nimport rich\n", "test_app.py": IMPORT_TEST},
        "setup": [],
        "pip_log": True,
        "goal": ["--goal", "pass_tests"],
        "expect": "Same state as D2 (pandas==1.1.0 cannot build on Python 3.12; nothing installed; the pip log is "
                  "imported). The first step must identify the blocker: pandas, the pinned 1.1.0, requirements.txt and "
                  "build/interpreter evidence. FAIL: a command installing another pandas without telling the user to "
                  "change the pin (silent bypass), or a command after which pandas or rich is still missing. REVIEW "
                  "(never an automatic success, reported apart): the step asks to change the declaration, or has no "
                  "command; the operator then follows the steps literally (edit the declaration as instructed, run the "
                  "install plan given) and records the real result. PASS needs identification, pandas and rich "
                  "importable, tests passing and no pandas==1.1.0 left in requirements.txt.",
    },
    "E": {
        "title": "environment.yml is a declaration source",
        "files": {"environment.yml": "name: demo\ndependencies:\n  - numpy\n  - imageio\n",
                  "app.py": "import imageio\nimport numpy\n", "test_app.py": IMPORT_TEST},
        "setup": [["numpy"]],
        "goal": ["--goal", "pass_tests"],
        "expect": "imageio is declared in environment.yml but not installed. The first step must give a command that "
                  "installs imageio; running it must make the tests pass.",
    },
    "F": {
        "title": "No alternative that cannot be installed on the current Python",
        "files": {"requirements.txt": "pandas==1.1.0\n",
                  "app.py": "import pandas as pd\n\n\ndef rows(values):\n    frame = pd.DataFrame()\n"
                            "    for value in values:\n        frame = frame.append({'value': value}, ignore_index=True)\n"
                            "    return len(frame)\n",
                  "test_app.py": "from app import rows\n\n\ndef test_rows():\n    assert rows([1, 2, 3]) == 3\n"},
        "setup": [["pandas"]],
        "goal": ["--goal", "pass_tests"],
        "expect": "pandas 2 removed DataFrame.append. The first step may advise pandas.concat, but must not offer "
                  "pinning pandas below 2.0 (pandas 1.5.3 has no build for Python 3.12) unless it says that pin "
                  "cannot be installed on this interpreter.",
    },
    "G": {
        "title": "The CLI lists no stale action for an issue the latest run did not reach",
        "files": {"requirements.txt": "SQLAlchemy==1.1.9\nFlask_SQLAlchemy==2.2\nFlask\n",
                  "app.py": FLASK_SQLA_APP, "test_app.py": IMPORT_TEST},
        "setup": [["SQLAlchemy==1.1.9", "Flask_SQLAlchemy==2.2", "flask"]],
        "then": [["SQLAlchemy==2.0.44"]],
        "goal": ["--goal", "pass_tests"],
        "expect": "Scan with SQLAlchemy 1.1.9 (MutableMapping issue), install SQLAlchemy 2.0.44, scan again: the "
                  "MutableMapping issue is no longer observed. 'fixfirst show' must not list an action for it (the "
                  "trial showed 'sqlalchemy 2.x still uses collections.MutableMapping'), and its first step must "
                  "equal the web view's first step.",
    },
}

VIEW = """
import json, sys
from fixfirst.storage import Store
from fixfirst.workspace import build_view
session = Store(sys.argv[1]).load(sys.argv[2])
view = build_view(session)
print(json.dumps({
    "status": view["status"].get("kind"),
    "issues": [{"id": i.issue_id, "tool": i.tool, "status": i.status, "title": i.title[:300],
                "diagnosis": i.diagnosis, "rule": i.diagnosis_rule} for i in session.issues][:40],
    "steps": [{k: s.get(k) for k in ("id", "title", "explanation", "command", "issue_ids")} for s in view["steps"][:4]],
}))
"""


def clean_env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "PYTEST_ADDOPTS")}


def sh(argv, cwd=None, timeout=1800) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, env=clean_env(), timeout=timeout)


class Case:
    def __init__(self, name, spec, folder: Path, fixfirst: Path):
        self.name, self.spec, self.folder, self.fixfirst = name, spec, folder, fixfirst
        self.python_ff = fixfirst.with_name("python")
        self.project, self.venv, self.store = folder / "project", folder / "venv", folder / "store"
        self.py = self.venv / "bin/python"
        self.notes = []

    def build(self):
        self.folder.mkdir(parents=True)
        if "clone" in self.spec:
            url, commit = self.spec["clone"]
            sh(["git", "clone", "-q", url, str(self.project)])
            sh(["git", "checkout", "-q", commit], cwd=self.project)
        else:
            self.project.mkdir()
            for name, text in self.spec["files"].items():
                (self.project / name).write_text(text, encoding="utf-8")
        sh(["uv", "venv", "-q", "--seed", "--python", "3.12", str(self.venv)])
        self.pip(["pytest"])
        for packages in self.spec["setup"]:
            done = self.pip(packages)
            self.notes.append(f"setup pip install {' '.join(packages)} -> exit {done.returncode}")

    def pip(self, packages) -> subprocess.CompletedProcess:
        return sh([str(self.py), "-m", "pip", "install", "-q", *packages], cwd=self.project)

    def cli(self, *args) -> subprocess.CompletedProcess:
        return sh([str(self.fixfirst), "--store", str(self.store), *args])

    def init(self):
        self.cli("init", str(self.project), "--python", str(self.py), *self.spec["goal"])
        self.session = next(p.name for p in self.store.iterdir() if p.name.startswith("session-"))

    def scan(self) -> dict:
        self.cli("scan", self.session)
        return self.view()

    def view(self) -> dict:
        done = sh([str(self.python_ff), "-c", VIEW, str(self.store), self.session])
        return json.loads(done.stdout)

    def run_step(self, step) -> subprocess.CompletedProcess:
        return sh(["sh", "-c", step["command"]], cwd=self.project)

    def tests(self) -> subprocess.CompletedProcess:
        return sh([str(self.py), "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=self.project, timeout=600)


def first(view):
    return view["steps"][0] if view["steps"] else {}


def verdict(ok, why, **extra):
    return {"verdict": "PASS" if ok else "FAIL", "why": why, **extra}


def check_a(c: Case):
    view = c.scan()
    step = first(view)
    if not step.get("command"):
        return {"verdict": "REVIEW", "why": "first step has no command; read whether it names the pin to relax", "step": step}
    c.run_step(step)
    out = c.tests()
    text = out.stdout + out.stderr
    ok = "MutableMapping" not in text and "_BindParamClause" not in text
    return verdict(ok, "after the step: MutableMapping gone and no _BindParamClause overshoot" if ok else
                   "after the step the original error remains or the overshoot symptom appears", step=step,
                   tests_tail=text[-800:])


def check_a2(c: Case):
    view = c.scan()
    step = first(view)
    if not step.get("command"):
        return {"verdict": "REVIEW", "why": "first step has no command; read whether it bounds the upgrade or names alembic",
                "step": step}
    told = (step.get("title", "") + " " + (step.get("explanation") or "")).lower()
    mentions_pin = "requirements.txt" in told or "1.1.9" in told and "pin" in told  # recorded only, not a gate
    c.run_step(step)
    out = c.tests()
    text = out.stdout + out.stderr
    return verdict(out.returncode == 0, "tests pass: sqlalchemy and alembic import after the step" if out.returncode == 0
                   else "after the step sqlalchemy or alembic still fails to import (overshoot or original error)",
                   step=step, tests_tail=text[-800:], mentions_declared_pin=mentions_pin)


def check_b(c: Case):
    view = c.scan()
    step = first(view)
    text = (step.get("title", "") + " " + (step.get("explanation") or "")).lower()
    older = ("older sqlalchemy" in text or re.search(r"sqlalchemy\s*(<|==\s*1\.)", step.get("command") or "", re.I)
             or "no longer provides" in text)
    if older:
        return verdict(False, "the first step searches or installs an older SQLAlchemy / says 'no longer provides'", step=step)
    if not step.get("command"):
        return {"verdict": "REVIEW", "why": "no command; read whether it says to upgrade to >=2.0.16", "step": step}
    c.run_step(step)
    check = sh([str(c.py), "-m", "pip", "check"], cwd=c.project)
    out = c.tests()
    ok = check.returncode == 0 and out.returncode == 0
    return verdict(ok, "pip check clean and tests pass" if ok else "pip check or tests still fail", step=step,
                   pip_check=check.stdout[-400:], tests_tail=(out.stdout + out.stderr)[-600:])


def check_b2(c: Case):
    from packaging.requirements import InvalidRequirement, Requirement

    view = c.scan()
    step = first(view)
    text = (step.get("title", "") + " " + (step.get("explanation") or "")).lower()
    command = step.get("command") or ""
    downgrade = False
    for token in re.findall(r"'([^']*sqlalchemy[^']*)'|(\bsqlalchemy[^\s']*)", command, re.I):
        spec = token[0] or token[1]
        try:
            requirement = Requirement(spec)
        except InvalidRequirement:
            continue
        if requirement.specifier and not any(requirement.specifier.contains(v) for v in ("2.0.16", "2.0.44", "2.1.1")):
            downgrade = True
    if downgrade or "older sqlalchemy" in text or "search older" in text:
        return verdict(False, "the first step searches or installs a SQLAlchemy range without any release >= 2.0.16",
                       step=step)
    if not command:
        return {"verdict": "REVIEW", "why": "no command; read whether it says to upgrade to >=2.0.16", "step": step}
    c.run_step(step)
    check = sh([str(c.py), "-m", "pip", "check"], cwd=c.project)
    out = c.tests()
    ok = check.returncode == 0 and out.returncode == 0
    return verdict(ok, "pip check clean and tests pass" if ok else "pip check or tests still fail", step=step,
                   pip_check=check.stdout[-400:], tests_tail=(out.stdout + out.stderr)[-600:])


def django_version(text: str):
    found = re.search(r"django\s*(==|<|<=)\s*([\d.]+)", text, re.I) or re.search(r"install django ([\d.]+)", text, re.I)
    if not found:
        return None
    version = found.group(found.lastindex)
    return tuple(int(x) for x in version.split(".") if x.isdigit())


def check_c(c: Case):
    view = c.scan()
    step = first(view)
    blob = (step.get("title", "") + " " + (step.get("explanation") or "") + " " + (step.get("command") or ""))
    found = django_version(blob)
    if found and found < (1, 10, 5):
        return verdict(False, f"the first step points at Django {found} older than the declared 1.10.5", step=step)
    listing = c.cli("show", c.session).stdout
    search = re.search(r"^\s*\d+\.\s+(find-release-\S+)", listing, re.M)
    if search and step.get("id", "").startswith("find-release-"):
        c.cli("run", c.session, search.group(1))
        after = first(c.view())
        found = django_version(after.get("title", "") + " " + (after.get("command") or ""))
        if found and found < (1, 10, 5):
            return verdict(False, f"the release search recommends Django {found}, older than the declared 1.10.5",
                           step=step, after_search=after)
        return {"verdict": "REVIEW", "why": "search ran; read the recommendation", "step": step, "after_search": after}
    return {"verdict": "REVIEW", "why": "no older Django offered; read whether an interpreter route or an explicit "
                                        "'no release fits' is given", "step": step}


def check_d1(c: Case):
    view = c.scan()
    step = first(view)
    if not step.get("command"):
        return verdict(False, "no command in the first step", step=step)
    c.run_step(step)
    after = c.scan()
    # Tool availability (for example ruff not installed) is not a missing declared dependency.
    missing = [i["title"] for i in after["issues"] if i["status"] in ("open", "awaiting_verification")
               and i["tool"] in ("pytest_run", "pytest", "project", "python_run")
               and not i["title"].startswith("Could not start")
               and ("No module named" in i["title"] or "Required dependency missing" in i["title"])]
    return verdict(not missing, "one step installed every declared dependency" if not missing else
                   f"still missing after one step: {missing[:5]}", step=step)


def check_d2(c: Case):
    log = c.folder / "pip-install.log"
    done = sh([str(c.py), "-m", "pip", "install", "-r", "requirements.txt"], cwd=c.project)
    log.write_text(done.stdout + done.stderr)
    c.notes.append(f"pip install -r requirements.txt -> exit {done.returncode}")
    c.cli("import", c.session, "--tool", "pip_install", "--file", str(log), "--exit-code", str(done.returncode))
    view = c.scan()
    step = first(view)
    text = (step.get("title", "") + " " + (step.get("explanation") or "") + " " + (step.get("command") or "")).lower()
    names_blocker = "pandas" in text and ("1.1.0" in text or "build" in text)
    if not step.get("command"):
        return verdict(False, "no command in the first step", step=step, names_blocker=names_blocker)
    c.run_step(step)
    importable = sh([str(c.py), "-c", "import pandas, rich"], cwd=c.project).returncode == 0
    ok = names_blocker and importable
    return verdict(ok, f"names the blocker: {names_blocker}; pandas and rich importable after the step: {importable}",
                   step=step)


CHANGE_PIN = ("relax", "change the pin", "update the pin", "adjust the pin", "edit requirements", "change requirements",
              "update requirements", "modify the declaration", "change the declaration", "update the declaration",
              "remove the pin", "replace pandas==1.1.0", "change pandas==1.1.0", "loosen")


def check_d2b(c: Case):
    log = c.folder / "pip-install.log"
    done = sh([str(c.py), "-m", "pip", "install", "-r", "requirements.txt"], cwd=c.project)
    log.write_text(done.stdout + done.stderr)
    c.notes.append(f"pip install -r requirements.txt -> exit {done.returncode}")
    c.cli("import", c.session, "--tool", "pip_install", "--file", str(log), "--exit-code", str(done.returncode))
    view = c.scan()
    step = first(view)
    command = step.get("command") or ""
    text = (step.get("title", "") + " " + (step.get("explanation") or "") + " " + command).lower()
    identifies = ("pandas" in text and "1.1.0" in text and "requirements.txt" in text
                  and any(w in text for w in ("build", "wheel", "3.12", "compile")))
    says_change_pin = any(w in text for w in CHANGE_PIN)
    if says_change_pin or not command:
        return {"verdict": "REVIEW", "why": f"the step asks to change the declaration or has no command; identifies the "
                f"blocker: {identifies}. Operator follows it by hand and records the real result; never counted as an "
                f"automatic success", "identifies": identifies, "step": step, "manual_followthrough": None}
    if re.search(r"\bpandas\b", command) and "pandas==1.1.0" not in command:
        return verdict(False, "installs another pandas while requirements.txt still pins pandas==1.1.0, without telling "
                       "the user to change that pin (silent bypass)", step=step, identifies=identifies)
    c.run_step(step)
    importable = sh([str(c.py), "-c", "import pandas, rich"], cwd=c.project).returncode == 0
    out = c.tests()
    still_pinned = "pandas==1.1.0" in (c.project / "requirements.txt").read_text()
    ok = identifies and importable and out.returncode == 0 and not still_pinned
    return verdict(ok, f"identifies: {identifies}; importable: {importable}; tests pass: {out.returncode == 0}; "
                   f"pandas==1.1.0 still declared: {still_pinned}", step=step)


def check_e(c: Case):
    view = c.scan()
    step = first(view)
    if not step.get("command") or "imageio" not in step["command"]:
        return verdict(False, "the first step gives no command installing imageio", step=step)
    c.run_step(step)
    out = c.tests()
    return verdict(out.returncode == 0, "tests pass after the step" if out.returncode == 0 else "tests still fail",
                   step=step, tests_tail=(out.stdout + out.stderr)[-400:])


def check_f(c: Case):
    view = c.scan()
    step = first(view)
    text = (step.get("title", "") + " " + (step.get("explanation") or "") + " " + (step.get("command") or "")).lower()
    offers_pin = bool(re.search(r"pandas\s*<\s*2|pandas below 2", text))
    qualified = any(q in text for q in ("cannot be installed", "not installable", "no prebuilt", "no wheel",
                                        "no build for", "not available for python"))
    ok = not offers_pin or qualified
    return verdict(ok, "no uninstallable pandas<2 alternative offered" if ok else
                   "offers pinning pandas below 2.0 without saying it cannot be installed on Python 3.12", step=step)


def check_g(c: Case):
    c.scan()
    for packages in c.spec["then"]:
        c.pip(packages)
    view = c.scan()
    listing = c.cli("show", c.session).stdout
    steps_part = listing.split("Next steps", 1)[-1]
    stale = "MutableMapping" in steps_part
    web_first = first(view).get("id")
    cli_first = re.search(r"^\s*1\.\s+(\S+)", steps_part, re.M)
    same = bool(cli_first) and cli_first.group(1) == web_first
    ok = not stale and same
    return verdict(ok, f"stale MutableMapping action listed: {stale}; CLI first step equals web first step: {same}",
                   cli_steps=steps_part[:900], web_first=web_first)


CHECKS = {"A": check_a, "A2": check_a2, "B": check_b, "B2": check_b2, "C": check_c, "D1": check_d1, "D2": check_d2, "D2b": check_d2b, "E": check_e, "F": check_f,
          "G": check_g}


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fixfirst", type=Path, required=True, help="the fixfirst command of the build under test")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--only", nargs="+", choices=sorted(CASES))
    args = parser.parse_args(argv)
    base = args.out.resolve() / args.tag
    base.mkdir(parents=True, exist_ok=False)
    fixfirst = args.fixfirst.resolve()
    head = sh([str(fixfirst.with_name("python")), "-c",
               "import fixfirst, pathlib, subprocess; root = pathlib.Path(fixfirst.__file__).resolve().parents[2]; "
               "print(subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip())"])
    results = {"fixfirst": str(fixfirst), "head": head.stdout.strip(), "cases": {}}
    for name in args.only or [n for n in CASES if "invalid" not in CASES[n]]:
        case = Case(name, CASES[name], base / name, fixfirst)
        try:
            case.build()
            case.init()
            outcome = CHECKS[name](case)
        except Exception as error:  # a broken case is reported, never skipped silently
            outcome = {"verdict": "ERROR", "why": f"{type(error).__name__}: {error}"}
        results["cases"][name] = {"title": CASES[name]["title"], "expect": CASES[name]["expect"],
                                  "notes": case.notes, **outcome}
        print(f"{name:3} {outcome['verdict']:6} {outcome['why'][:150]}", flush=True)
    (base / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
