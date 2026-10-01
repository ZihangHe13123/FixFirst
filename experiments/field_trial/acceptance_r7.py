"""Round-7 acceptance cases (Claude, 2026-10-01), written before Codex's round-7 commit exists.

Targets: installation-failure feedback, failure causes and executable next steps. Each case rebuilds a
state in a fresh Python 3.12 venv and then follows FixFirst LITERALLY, the way the field-trial protocol
does: a step's command is run as given; an exact edit stated as "<file>:<line>: replace A with B" is
applied; a runnable action named as "fixfirst run <session> <action>" is run. When a step offers none of
these, the case stops: a human would have to decide, so the verdict is REVIEW (never an automatic
success). The harness never relaxes pins, never edits tests, never chooses versions.

  python experiments/field_trial/acceptance_r7.py --out RUNS --fixfirst VENV/bin/fixfirst --tag TAG [--only R7-A ...]
      [--mirror DIR]   (optional local clones named owner_repo, used instead of GitHub)

Verdicts: PASS (expectation met by literal following only), FAIL (an anti-pattern or a wrong claim),
REVIEW (needs the manual protocol in the handoff), ERROR (the case itself broke). The old acceptance.py
is unchanged; this file imports its helpers. Development material only; no private data.
"""

import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from acceptance import Case, first, sh  # noqa: E402

C1_URL, C1_COMMIT = "https://github.com/miguelgrinberg/microblog.git", "a975ef64864354867c88e0ed3a17ba7d17dca752"
SIX_TEST = "import six\n\n\ndef test_six():\n    assert six.PY3\n"

CASES = {
    "R7-A": {
        "title": "C1 from its original initial state: a failed batch install is read, not repeated",
        "clone": (C1_URL, C1_COMMIT), "mirror": "miguelgrinberg_microblog",
        "readme_install": ["-r", "requirements.txt"], "pytest": False,
        "goal": ["--goal", "pass_unittest", "--unittest-dir", ".", "--test-pattern", "tests.py"],
        "test_command": ["tests.py"], "sdist_only": ["flask-mail", "langdetect"], "rounds": 10,
        "expect": "Initial state = the first batch's C1: the pinned install fails building multidict 6.0.4, the venv is "
                  "empty. Follow FixFirst literally. FAIL if a step is repeated unchanged after its command failed; if "
                  "Flask-Mail 0.9.1 or langdetect 1.0.9 (sdist only, pure Python, both build) is called a version "
                  "conflict or a Python problem; or if a command installs the declared packages with their pins "
                  "removed. PASS needs: unittest suite passes; reached only by commands, exact edits and FixFirst "
                  "actions; Flask-Mail==0.9.1 and langdetect==1.0.9 still declared; every other declaration change "
                  "was an exact FixFirst edit. Reference (operator check, not given to the tool): changing only "
                  "multidict to a release with a cp312 wheel and letting pip build the two pure-Python sdists makes "
                  "all 4 tests pass. Anything else is REVIEW for the manual M1/M2/H protocol.",
    },
    "R7-SDIST": {
        "title": "An sdist-only pure-Python pin is a missing wheel, not a version conflict",
        "files": {"requirements.txt": "Flask-Mail==0.9.1\nFlask==3.0.0\n",
                  "test_app.py": "import flask_mail\n\n\ndef test_import():\n    assert flask_mail\n"},
        "setup": [], "goal": ["--goal", "pass_tests"], "sdist_only": ["flask-mail"], "rounds": 6,
        "expect": "Flask-Mail 0.9.1 exists only as an sdist (pure Python; pip builds it into a py3-none-any wheel). "
                  "FAIL on an unchanged repeat after a failed command, on version-conflict or Python-change claims about "
                  "it, or on a command that drops its pin. PASS: tests pass by literal following with Flask-Mail==0.9.1 "
                  "still declared and installed.",
    },
    "R7-NOTFOUND": {
        "title": "Counterexample: a name that does not exist is not an sdist-only package",
        "files": {"requirements.txt": "fixfirst-nonexistent-package-xyz==1.0\nsix==1.16.0\n", "test_six.py": SIX_TEST},
        "setup": [], "goal": ["--goal", "pass_tests"], "sdist_only": [], "rounds": 3,
        "not_found": "fixfirst-nonexistent-package-xyz",
        "expect": "Under --only-binary pip prints the same 'from versions: none' for an sdist-only package and for a "
                  "missing one (checked with docopt 0.6.2). FAIL if FixFirst proposes a source build/wheelhouse for this "
                  "name or calls it sdist-only, or repeats unchanged after the failure. PASS if it says the distribution "
                  "was not found (name or index) without a build route. Otherwise REVIEW.",
    },
    "R7-PGCONFIG": {
        "title": "A missing system build tool (pg_config) is not a Python-version problem",
        "files": {"requirements.txt": "psycopg2\n",
                  "test_db.py": "import psycopg2\n\n\ndef test_import():\n    assert psycopg2\n"},
        "setup": [], "goal": ["--goal", "pass_tests"], "imported_install": True, "rounds": 1,
        "expect": "The user's README install fails: 'pg_config executable not found' (psycopg2, unpinned, needs the "
                  "PostgreSQL client tools). The log is imported. FAIL if the first step routes to an older/other "
                  "Python or a version change, or does not mention pg_config / PostgreSQL / libpq. PASS if it names "
                  "the missing tool and gives an executable route (a command, or an explicit, explained declaration "
                  "change such as psycopg2 -> psycopg2-binary). REVIEW if it names the tool without a route.",
    },
    "R7-PGFLOW": {
        "title": "Following FixFirst into a source build of psycopg2 ends at pg_config, not at Python",
        "files": {"requirements.txt": "psycopg2\n",
                  "test_db.py": "import psycopg2\n\n\ndef test_import():\n    assert psycopg2\n"},
        "setup": [], "goal": ["--goal", "pass_tests"], "sdist_only": [], "rounds": 5, "pg_flow": True,
        "expect": "Same project, but nothing imported: FixFirst's own commands are followed. psycopg2 has no wheel "
                  "(sdist only) and its build needs pg_config, so a source-build route must fail. FAIL on an unchanged "
                  "repeat, on a Python-change route after the pg_config failure, or on repeating the failed source "
                  "build. PASS if tests pass by literal following with a stated, explicit psycopg2 route. Else REVIEW.",
    },
    "R7-PYTEST": {
        "title": "A missing test runner still leads to installing the project's declared set",
        "files": {"requirements/prod.txt": "six==1.16.0\n", "requirements/dev.txt": "-r prod.txt\npytest==8.3.3\n",
                  "tests/test_six.py": SIX_TEST},
        "setup": [], "pytest": False, "goal": ["--goal", "pass_tests"], "sdist_only": [], "rounds": 4,
        "first_step_needs_command": True,
        "expect": "The venv is empty; pytest is declared only in requirements/dev.txt, which includes prod.txt with -r "
                  "(the C2 layout). FAIL if the first step is a generic 'check that the tool is available' without a "
                  "command. PASS if literal following installs the declared set (pytest==8.3.3, six==1.16.0) and the "
                  "tests pass. Otherwise REVIEW.",
    },
    "R7-SUBST": {
        "title": "A psycopg2-binary installed in place of the declared psycopg2 is explained, not ignored",
        "files": {"requirements.txt": "psycopg2\nSQLAlchemy==1.1.9\n", "app.py": "import psycopg2\nimport sqlalchemy\n",
                  "test_app.py": "import app\n\n\ndef test_import():\n    assert app\n"},
        "setup": [["psycopg2-binary", "SQLAlchemy==1.1.9"]], "goal": ["--goal", "pass_tests"], "sdist_only": [],
        "rounds": 6, "substitution": ("psycopg2", "psycopg2-binary"),
        "expect": "The environment uses psycopg2-binary (the operator's C2 substitution) while requirements.txt declares "
                  "psycopg2; SQLAlchemy 1.1.9 fails on Python 3.12 (MutableMapping). FAIL if a dependency trial or step "
                  "stops at psycopg2 without mentioning psycopg2-binary / the substitution. PASS if literal following "
                  "reaches passing tests and every psycopg2 declaration change was an explicit, explained FixFirst edit. "
                  "REVIEW if the substitution is explained but a human must choose.",
    },
    "R7-CONFLICT": {
        "title": "Counterexample: a genuine version conflict stays a version conflict",
        "files": {"requirements.txt": "requests==2.31.0\nurllib3==1.20\n",
                  "test_req.py": "import requests\n\n\ndef test_import():\n    assert requests\n"},
        "setup": [], "goal": ["--goal", "pass_tests"], "imported_install": True, "rounds": 1,
        "expect": "requests 2.31.0 requires urllib3>=1.21.1,<3; the README install fails with ResolutionImpossible and "
                  "the log is imported. FAIL if the first step calls it a missing wheel, a source build or a system "
                  "tool problem. PASS if it names the conflicting pair (requests and urllib3). Otherwise REVIEW.",
    },
    "R7-LEGACY": {
        "title": "Counterexample: a pure-Python sdist can still fail to build (legacy setup.py)",
        "files": {"requirements.txt": "anyjson==0.3.3\n",
                  "test_any.py": "import anyjson\n\n\ndef test_import():\n    assert anyjson\n"},
        "setup": [], "goal": ["--goal", "pass_tests"], "imported_install": True, "rounds": 1,
        "expect": "anyjson 0.3.3 is pure Python and sdist only, but its setup.py uses use_2to3, which current setuptools "
                  "rejects ('use_2to3 is invalid'), so 'pure Python sdist => buildable' is false. The README install "
                  "log is imported. FAIL if the first step calls it a version conflict or routes to an older Python "
                  "(build isolation fetches the newest setuptools for any Python). PASS if it names the build failure "
                  "(setup.py / use_2to3 / setuptools) with an executable route. Otherwise REVIEW.",
    },
    "R7-CONFLICTFLOW": {
        "title": "Counterexample through FixFirst's own commands: a real conflict is read as a conflict",
        "added": "after the 5d661e6 baseline, before any round-7 commit: R7-CONFLICT showed the imported conflict was "
                 "ignored; this variant checks the same conflict when it comes from FixFirst's own command",
        "files": {"requirements.txt": "requests==2.31.0\nurllib3==1.20\n",
                  "test_req.py": "import requests\n\n\ndef test_import():\n    assert requests\n"},
        "setup": [], "goal": ["--goal", "pass_tests"], "sdist_only": [], "rounds": 5,
        "conflict_pair": ("requests", "urllib3"),
        "expect": "Literal following: FixFirst's install command fails with ResolutionImpossible (requests 2.31.0 needs "
                  "urllib3>=1.21.1). FAIL on an unchanged repeat or if the next step calls it a missing wheel, a source "
                  "build or a system tool problem. PASS only if literal following reaches passing tests (e.g. an exact "
                  "edit of one pin from a verified trial). REVIEW if it names the pair but leaves the choice to a human.",
    },
    "R7-LEGACYFLOW": {
        "title": "Counterexample through the source-build route: a legacy setup.py failure ends the route honestly",
        "added": "after the 5d661e6 baseline, before any round-7 commit: exercises the proposed session wheelhouse route",
        "files": {"requirements.txt": "anyjson==0.3.3\n",
                  "test_any.py": "import anyjson\n\n\ndef test_import():\n    assert anyjson\n"},
        "setup": [], "goal": ["--goal", "pass_tests"], "sdist_only": ["anyjson"], "rounds": 5, "legacy_flow": True,
        "expect": "Literal following: anyjson 0.3.3 has no wheel; if FixFirst proposes building it (e.g. pip wheel into a "
                  "session wheelhouse), the build fails with 'use_2to3 is invalid'. FAIL on an unchanged repeat (including "
                  "repeating the failed build), or if a later step calls it a version conflict or routes to another "
                  "Python. REVIEW otherwise (no automatic PASS expected: the fix needs an older setuptools in the build "
                  "environment or replacing the package, both human decisions).",
    },
    "R7-STALE": {
        "title": "After the user changes the declarations, an old failure log is not reported as current",
        "files": {"requirements.txt": "Flask-Mail==0.9.1\nsix==1.16.0\n", "test_six.py": SIX_TEST},
        "setup": [], "goal": ["--goal", "pass_tests"], "sdist_only": ["flask-mail"], "rounds": 1, "stale": True,
        "expect": "Round 1 follows FixFirst's first command (which may fail at Flask-Mail). Then the user (scripted, not "
                  "a fix judgement) removes Flask-Mail from requirements.txt and installs six==1.16.0. The next scan "
                  "must be done (tests pass) and no step may cite the Flask-Mail failure as current. FAIL otherwise.",
    },
}

CONFLICT_CLAIMS = ("version conflict", "conflicts with", "conflicting requirement", "incompatible version",
                   "unsupported python", "incompatible with python", "older python", "another interpreter",
                   "different python", "change the python", "separate environment using the python")
PYTHON_ROUTES = ("older python", "python version supported", "separate environment using the python",
                 "another interpreter", "different python", "change the python", "select an older python")
BUILD_ROUTES = ("pip wheel", "wheelhouse", "build it from source", "build from source", "only as a source",
                "sdist only", "source distribution only", "no usable wheel")
NOT_BUILD_FOR_CONFLICT = ("pip wheel", "wheelhouse", "build from source", "no usable wheel", "pg_config",
                          "system package", "system library")
EDIT = re.compile(r"([\w./-]+):(\d+): replace (\S+) with (\S+?)\.(?:\s|$)")
ACTION = re.compile(r"fixfirst run (session-[0-9a-f]+) ([\w.\-]+)")


def claim_text(step) -> str:
    """The step's own claim: title + explanation before any quoted tool output, lower case."""
    explanation = step.get("explanation") or ""
    for marker in ("Resolver output:", "Original output", "Imported output"):
        explanation = explanation.split(marker)[0]
    return (step.get("title", "") + " " + explanation).lower()


def affirmative(claim: str) -> str:
    """Drop negated sentences ('does not establish a version conflict ...') before looking for claims."""
    sentences = re.split(r"(?<=[.;:])\s+", claim)
    return " ".join(s for s in sentences if not re.search(r"\b(not|no|never|without)\b|n't", s))


def declared(project: Path) -> dict:
    return {str(p.relative_to(project)): p.read_text(encoding="utf-8")
            for p in sorted(project.rglob("*.txt")) if "requirements" in p.name or p.parent.name == "requirements"}


def unpins_declared(command: str, project: Path) -> bool:
    """A command that installs five or more declared names without their pins, or strips pins with sed."""
    if re.search(r"sed\s+'s/\[=<>~!\]", command):
        return True
    names = set()
    for text in declared(project).values():
        for line in text.splitlines():
            m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*==", line)
            if m:
                names.add(m.group(1).lower().replace("_", "-"))
    bare = [t.lower().replace("_", "-") for t in command.split() if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", t)]
    return sum(1 for t in bare if t in names) >= 5


class R7Case(Case):
    def __init__(self, name, spec, folder, fixfirst, mirror):
        super().__init__(name, spec, folder, fixfirst)
        self.mirror = mirror
        self.rounds = []

    def build(self):
        self.folder.mkdir(parents=True)
        if "clone" in self.spec:
            url, commit = self.spec["clone"]
            local = self.mirror / self.spec["mirror"] if self.mirror else None
            sh(["git", "clone", "-q", str(local) if local and local.exists() else url, str(self.project)])
            sh(["git", "checkout", "-q", commit], cwd=self.project)
        else:
            for name, text in self.spec["files"].items():
                path = self.project / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
        sh(["uv", "venv", "-q", "--seed", "--python", "3.12", str(self.venv)])
        if self.spec.get("pytest", True):
            self.pip(["pytest"])
        for packages in self.spec.get("setup", []):
            done = self.pip(packages)
            self.notes.append(f"setup pip install {' '.join(packages)} -> exit {done.returncode}")
        if "readme_install" in self.spec:
            done = sh([str(self.py), "-m", "pip", "install", *self.spec["readme_install"]], cwd=self.project)
            self.notes.append(f"README install -> exit {done.returncode} (expected to fail as in the first batch)")
        self.original = declared(self.project)

    def run_tests(self):
        if "test_command" in self.spec:
            return sh([str(self.py), *self.spec["test_command"]], cwd=self.project, timeout=600)
        return self.tests()

    def follow(self, limit):
        """Follow FixFirst literally for up to `limit` rounds; return (outcome, problems)."""
        problems, previous = [], None
        for number in range(1, limit + 1):
            view = self.scan()
            if view["status"] == "done":
                return "done", problems
            step = first(view)
            if not step:
                return "no step", problems
            key = (step.get("title"), step.get("command"))
            record = {"round": number, "title": step.get("title"), "command": step.get("command"),
                      "claim": claim_text(step)[:1500]}
            problems += self.antipatterns(step, previous)
            if previous and key == previous["key"] and previous.get("exit") not in (0, None):
                problems.append(f"round {number}: the step is repeated unchanged after its command failed")
                record["action"] = "stopped: unchanged repeat"
                self.rounds.append(record)
                return "repeat", problems
            command, text = step.get("command"), step.get("explanation") or ""
            edits = EDIT.findall(text)
            for path, line, before, after in edits:
                target = self.project / path
                lines = target.read_text(encoding="utf-8").splitlines(keepends=True) if target.exists() else []
                index = int(line) - 1
                if index >= len(lines) or lines[index].strip() != before:
                    problems.append(f"round {number}: stated edit {path}:{line} does not match the file")
                    self.rounds.append(record)
                    return "edit mismatch", problems
                lines[index] = lines[index].replace(before, after)
                target.write_text("".join(lines), encoding="utf-8")
            if edits:
                record.update(edits=edits)
            if command:
                done = self.run_step(step)
                record.update(action="edits + command" if edits else "command", exit=done.returncode,
                              output_tail=(done.stdout + done.stderr)[-1500:])
            elif edits:
                record.update(action="edits", exit=0)
            elif ACTION.search(text):
                session, action = ACTION.search(text).groups()
                done = self.cli("run", session, action)
                record.update(action=f"fixfirst run {action}", exit=done.returncode,
                              output_tail=(done.stdout + done.stderr)[-1500:])
            else:
                record["action"] = "stopped: no command, exact edit or FixFirst action"
                self.rounds.append(record)
                return "needs human", problems
            self.rounds.append(record)
            previous = {"key": key, "exit": record.get("exit")}
        view = self.scan()
        return ("done" if view["status"] == "done" else "rounds exhausted"), problems

    def antipatterns(self, step, previous):
        found, claim, command = [], affirmative(claim_text(step)), step.get("command") or ""
        for name in self.spec.get("sdist_only", []):
            if re.search(re.escape(name).replace("\\-", "[-_]?"), claim) and any(w in claim for w in CONFLICT_CLAIMS):
                found.append(f"{name} (sdist only) is described as a version conflict or Python problem")
        if self.spec.get("pg_flow") and any("pg_config" in r.get("output_tail", "") for r in self.rounds) \
                and any(w in claim for w in PYTHON_ROUTES):
            found.append("after a pg_config build failure the step routes to another Python")
        if self.spec.get("legacy_flow") and any("use_2to3" in r.get("output_tail", "") for r in self.rounds) \
                and any(w in claim for w in CONFLICT_CLAIMS + PYTHON_ROUTES):
            found.append("after a use_2to3 build failure the step claims a conflict or routes to another Python")
        if command and unpins_declared(command, self.project):
            found.append("a command installs declared packages with their pins removed")
        return found


def result(c: R7Case, verdict, why, **extra):
    return {"verdict": verdict, "why": why, "rounds": c.rounds, **extra}


def check_follow(c: R7Case):
    outcome, problems = c.follow(c.spec["rounds"])
    final = declared(c.project)
    changed = {p: (c.original.get(p), t) for p, t in final.items() if c.original.get(p) != t}
    tests = c.run_tests()
    passed = tests.returncode == 0
    edits = [e for r in c.rounds for e in r.get("edits", [])]
    extra = {"outcome": outcome, "tests_pass": passed, "declaration_changes": changed, "fixfirst_edits": edits,
             "tests_tail": (tests.stdout + tests.stderr)[-800:]}
    if problems:
        return result(c, "FAIL", "; ".join(problems), **extra)
    if c.spec.get("first_step_needs_command") and c.rounds and not c.rounds[0].get("command") \
            and not c.rounds[0].get("edits") and not c.rounds[0]["action"].startswith("fixfirst run"):
        return result(c, "FAIL", "the first step is generic: no command, exact edit or FixFirst action", **extra)
    if c.spec.get("conflict_pair"):
        first_name, second_name = c.spec["conflict_pair"]
        raw = " ".join(r.get("claim", "") for r in c.rounds[1:])
        if any(w in affirmative(raw) for w in NOT_BUILD_FOR_CONFLICT):
            return result(c, "FAIL", "the conflict is described as a wheel/build/system problem", **extra)
        if outcome == "done" and passed:
            return result(c, "PASS", "goal reached by literal following only", **extra)
        named = first_name in raw and second_name in raw
        return result(c, "REVIEW", "names the conflicting pair; a human must choose" if named else
                      "literal following stopped without naming the pair; read by hand", **extra)
    if c.spec.get("legacy_flow"):
        return result(c, "REVIEW", f"no anti-pattern; literal following ended: {outcome}", **extra)
    if c.spec.get("not_found"):
        claim = " ".join(r.get("claim", "") for r in c.rounds[1:])
        if c.spec["not_found"] in claim and any(w in claim for w in BUILD_ROUTES):
            return result(c, "FAIL", "the missing name is given a source-build route or called sdist-only", **extra)
        says = any(w in claim for w in ("not found", "no such", "does not exist", "check the name", "index"))
        return result(c, "PASS" if says else "REVIEW", "states not found" if says else "read the steps by hand", **extra)
    for name in c.spec.get("sdist_only", []):
        for text in final.values():
            if not re.search(rf"(?im)^{re.escape(name).replace(chr(92) + '-', '[-_]')}\s*==", text):
                return result(c, "FAIL", f"the {name} pin was removed or relaxed", **extra)
    if c.spec.get("substitution"):
        declared_name, installed = c.spec["substitution"]
        claim = " ".join(r.get("claim", "") for r in c.rounds)
        if installed not in claim and outcome != "done":
            return result(c, "FAIL", f"steps never mention {installed} although it replaces the declared {declared_name}",
                          **extra)
    if outcome == "done" and passed:
        unexplained = [p for p in changed if not any(e[0] == p for e in edits)]
        if unexplained:
            return result(c, "REVIEW", f"tests pass but declarations changed outside FixFirst's exact edits: {unexplained}",
                          **extra)
        return result(c, "PASS", "goal reached by literal following only (commands, exact edits, FixFirst actions)",
                      **extra)
    return result(c, "REVIEW", f"literal following stopped ({outcome}); continue with the manual M1/M2/H protocol",
                  **extra)


def check_imported(c: R7Case):
    log = c.folder / "pip-install.log"
    done = sh([str(c.py), "-m", "pip", "install", "-r", "requirements.txt"], cwd=c.project)
    log.write_text(done.stdout + done.stderr)
    c.notes.append(f"README install -> exit {done.returncode}; log imported")
    c.cli("import", c.session, "--tool", "pip_install", "--file", str(log), "--exit-code", str(done.returncode))
    step = first(c.scan())
    raw, command = claim_text(step), step.get("command") or ""
    claim = affirmative(raw)
    extra = {"step": {k: step.get(k) for k in ("title", "command")}, "claim": raw[:1500]}
    if c.name == "R7-PGCONFIG":
        if any(w in claim for w in PYTHON_ROUTES) or "version" in step.get("title", "").lower():
            return {"verdict": "FAIL", "why": "a missing pg_config is routed to a Python or version change", **extra}
        names = any(w in raw for w in ("pg_config", "postgresql", "libpq"))
        if not names:
            return {"verdict": "FAIL", "why": "the missing pg_config / PostgreSQL client is not mentioned", **extra}
        route = bool(command) or "psycopg2-binary" in raw
        return {"verdict": "PASS" if route else "REVIEW",
                "why": "names the missing build tool with a route" if route else "names the tool, no route", **extra}
    if c.name == "R7-CONFLICT":
        if any(w in claim for w in NOT_BUILD_FOR_CONFLICT):
            return {"verdict": "FAIL", "why": "a resolver conflict is described as a build/wheel/system problem", **extra}
        names = "requests" in raw and "urllib3" in raw
        return {"verdict": "PASS" if names else "REVIEW",
                "why": "names the conflicting requests/urllib3 pair" if names else "read the step by hand", **extra}
    if c.name == "R7-LEGACY":
        if any(w in claim for w in ("version conflict", "conflicts with")) or any(w in claim for w in PYTHON_ROUTES):
            return {"verdict": "FAIL", "why": "a legacy setup.py build failure is called a conflict or a Python problem",
                    **extra}
        names = any(w in raw for w in ("use_2to3", "setup.py", "setuptools", "build backend", "failed to build"))
        route = bool(command)
        return {"verdict": "PASS" if names and route else "REVIEW",
                "why": "names the build failure with a route" if names and route else "read the step by hand", **extra}
    raise ValueError(f"no imported check for {c.name}")


def check_stale(c: R7Case):
    outcome, problems = c.follow(1)
    req = c.project / "requirements.txt"
    req.write_text("six==1.16.0\n", encoding="utf-8")
    c.pip(["six==1.16.0"])
    c.notes.append("scripted user action: removed Flask-Mail from requirements.txt, installed six==1.16.0")
    view = c.scan()
    steps_text = " ".join(claim_text(s) for s in view["steps"])
    if view["status"] != "done" or "flask-mail" in steps_text or "flask_mail" in steps_text:
        return result(c, "FAIL", f"after the declarations changed: status {view['status']}; steps still cite "
                      f"Flask-Mail: {'flask' in steps_text}", status=view["status"])
    return result(c, "PASS", "the old failure is not reported once the declarations changed", status=view["status"])


def check_case(c: R7Case):
    if c.spec.get("imported_install"):
        return check_imported(c)
    if c.spec.get("stale"):
        return check_stale(c)
    return check_follow(c)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fixfirst", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--only", nargs="+", choices=sorted(CASES))
    parser.add_argument("--mirror", type=Path, help="folder with local clones named owner_repo")
    args = parser.parse_args(argv)
    base = args.out.resolve() / args.tag
    base.mkdir(parents=True, exist_ok=False)
    fixfirst = args.fixfirst.resolve()
    head = sh([str(fixfirst.with_name("python")), "-c",
               "import fixfirst, pathlib, subprocess; root = pathlib.Path(fixfirst.__file__).resolve().parents[2]; "
               "print(subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip())"])
    results = {"fixfirst": str(fixfirst), "head": head.stdout.strip(), "cases": {}}
    for name in args.only or list(CASES):
        case = R7Case(name, CASES[name], base / name, fixfirst, args.mirror.resolve() if args.mirror else None)
        try:
            case.build()
            case.init()
            outcome = check_case(case)
        except Exception as error:  # a broken case is reported, never skipped silently
            outcome = {"verdict": "ERROR", "why": f"{type(error).__name__}: {error}", "rounds": case.rounds}
        results["cases"][name] = {"title": CASES[name]["title"], "expect": CASES[name]["expect"],
                                  "notes": case.notes, **outcome}
        print(f"{name:12} {outcome['verdict']:6} {outcome['why'][:160]}", flush=True)
    (base / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
