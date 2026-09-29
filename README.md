# FixFirst

**Find the root cause of Python test failures from real evidence, then verify every fix.**

FixFirst runs your project's own checks (environment snapshot, dependency declarations,
`pip check`, pytest collection and runs, Ruff), groups repeated errors, diagnoses the root
cause of each failure, ranks what to do next for your goal, and closes an issue only when a
completed check of the same scope proves it fixed. It runs locally, never edits your code and
never installs anything into your environment (it gives you the command instead).

NUS-ISS Intelligent Reasoning Systems practice module, Group 24 · version 0.6.1

Windows group testing: see [组员测试说明](docs/WINDOWS_TEAM_TEST.md). What was tested on
each platform, and what is still open: [docs/WINDOWS_ADAPTATION.md](docs/WINDOWS_ADAPTATION.md).

## Quick start

Python 3.10+ on macOS, Linux or Windows 10/11.

```bash
bash scripts/setup.sh python3.12
.venv/bin/fixfirst serve
```

On Windows (PowerShell, in the project folder):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
.venv\Scripts\fixfirst serve
```

After setup, double-click `start-fixfirst.bat` to open the app. Windows commands
shown by FixFirst are for **PowerShell**, including paths containing spaces or
Chinese characters. Select the Python belonging to the project you are checking;
it can be a venv or a Windows Conda environment.

Setup reuses an existing compatible `.venv`. To change its Python version, pass
`-Python C:\Path\to\python.exe -Recreate`; the previous environment is moved to a
`.venv-backup-*` folder before rebuilding. No global packages or system code-page
settings are changed. PowerShell 5.1 UTF-16 redirected logs and requirements are
supported. See [Windows adaptation and validation](docs/WINDOWS_ADAPTATION.md).

The browser opens the local interface:

1. Choose your project folder (type it or press *Browse…*). FixFirst finds the project's own
   `.venv` and tells you if pytest is missing there.
2. Pick a goal (*Make my tests pass* by default) and press **Check my project**.
3. Follow the numbered steps under **Must fix**. Each says which file and line to change, why,
   and how to confirm; install steps come with a command to copy. After changing your code,
   press **Check again**; a step only counts as fixed when a real check passes.
4. Steps under **Optional** do not change how your code runs (for example style suggestions,
   or a test that only counts warnings); they are not counted as problems.
5. When a library no longer provides a name your code uses, **Find it** tries older releases
   in a throwaway environment and tells you exactly which version to install.

No project at hand? Press *Open a sample project* on the start page: four faults across three
root-cause categories, with the changes listed in its `FIXES.md`. You can also double-click
`start-fixfirst.command` (macOS) or `start-fixfirst.bat` (Windows). Checks import the project's
code, as its tests would;
only use projects you trust. The evidence graph, rules and raw output are one click away under
*Technical details*.

## Why

When a Python project fails, the messages from pip, pytest and linters are scattered and
repeated, and the same exception can have very different causes. `ModuleNotFoundError: No
module named 'imp'` is not fixed by installing a package (the module was removed in Python
3.12); `AttributeError: module 'yaml' has no attribute 'safe_load'` usually means a project
file called `yaml.py` hides the library; a `KeyError` inside `os.environ` is a missing
setting, not a bug. FixFirst makes that distinction explicit, shows why, and insists on a
real check before calling anything fixed.

## How it works

One troubleshooting round is a loop. Each check updates the plan, and nothing is called fixed
until a real check shows it.

```
 your project + its Python interpreter + a goal (e.g. "make my tests pass")
      │
  1  Check       run the project's own checks: environment snapshot, declared dependencies,
      │          pip check, pytest (collect and run), Ruff
  2  Group       put repeated messages together (same tool, stage and place; text similarity)
      │
  3  Evidence    what actually happened: the real exception, where it was raised, and whether
      │          each module is installed, in the standard library, a local file or declared
  4  Knowledge   look up only the names in the evidence: what was removed, in which release,
      │          what replaces it, which package provides it (from official documentation)
  5  Reason      103 rules, forward chaining in five phases:
      │          derive → diagnose → heuristic → fallback (decision tree) → plan
  6  Plan        order the actions: blocked or not, effect on the goal, strength of evidence,
      │          kind of action, cost
      │
  7  Verify      you change the code, FixFirst runs the check again; an issue closes only when a
                 completed check of the same scope and interpreter passes → back to 1
```

### The parts, and how each is built

| Part (course technique) | What it does | How it is built | Code |
|---|---|---|---|
| **Rules** (decision automation) | Turn evidence and knowledge into root causes and next actions. A production system with variables, stratified negation and provenance; it concludes only when its conditions hold. | Written by the team: 103 rules in five phases, improved on development projects | `engine.py`, `knowledge/rules.toml`, `reasoning.py` |
| **Domain knowledge graph** (knowledge representation) | Supplies the facts the rules need: 119 removed modules, APIs, arguments, usages and fixtures with the release that removed them and their replacements, 10 deprecations, 44 pytest fixtures mapped to their plugins, import name → package, unmaintained packages, Ruff rules that indicate likely bugs | Curated from official documentation and release notes (23 sources); every entry cites its source. Not learned from data | `domain.py`, `knowledge/domain.toml` |
| **Evidence graph** (knowledge representation) | Records, for each session, the goal, issues, facts, causes, rules, actions, runs and sources (10 entity types, 15 relations); answers "why" and "what is left" questions by graph traversal | Built automatically during every check | `knowledge_graph.py` |
| **Decision tree** (data mining) | Suggests a likely cause when no rule or heuristic applies, shown as unconfirmed | Gini tree trained on 215 generated, executed cases, over 44 evidence features (no labels, no parser category) | `evidence.py`, `classification.py` |
| **Message grouping** (data mining) | TF-IDF character n-grams and cosine similarity, complete-link, inside blocks of the same tool, stage and place | One threshold (0.82), fixed before evaluation. So far no measurable gain over exact text matching, because each failing test forms its own block; being revised | `grouping.py` |
| **Release search** (search) | On request, tries older releases (at most 12 install-and-import trials, in a throwaway environment) and pins a version verified to provide a missing name | Runs at the time of use; nothing is trained | `versions.py` |

The rules are precise but only where knowledge exists, the knowledge graph supplies the facts
and the explanations, and the decision tree covers faults the knowledge graph does not list.

### One decision, step by step

From the sample project (*Open a sample project* on the start page):

```
evidence    pricing.py:1  `from collections import Mapping` fails; the interpreter is Python 3.12
knowledge   collections.Mapping was removed in Python 3.10; import it from collections.abc
            (source: Python documentation)
rule D02    a name the code uses + the release that removed it + the installed version
            → root cause: version incompatibility
action      "Replace collections.Mapping: removed in Python 3.10" (use collections.abc);
            confirm by re-running the affected tests with the same interpreter
verify      the issue closes only after a completed run covering it passes on that interpreter
```

Every recommendation traces back like this through the rule that proposed it, the facts it used
and the check record or release note those facts came from. The web page shows the trace under
*Details*; [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) describes the code.

### How we improve it

Much like training a model, with the data kept apart:

1. **Development projects**: run FixFirst, compare with labels, and fix the *general* cause of
   each mistake (missing evidence, missing knowledge, a wrong rule, wrong advice), never a
   single project. Each fix gets a test.
2. **Regression check**: the 215 generated cases and the unit tests must not get worse.
3. **Held-out test**: freeze a version, label a fresh set of projects before running, run once
   and report the result as it is ([docs/GENERALISATION.md](docs/GENERALISATION.md)).

Where the data comes from: [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

## Results

215 executed single-fault cases (5 project templates × 43 scenarios, real libraries, labels from
the scenario definition). Accuracy of naming the root cause, with 95% bootstrap intervals:

| Method | Unseen fault type (leave one scenario out) | Unseen project structure (leave one template out) |
|---|---|---|
| Parser category only (FixFirst 0.3 behaviour) | 0.419 (0.353–0.484) | 0.419 (0.353–0.484) |
| Rules without the knowledge graph | 0.488 | 0.488 |
| Rules + knowledge graph (answers 79% of cases, precision 1.00) | 0.791 (0.740–0.842) | 0.791 (0.740–0.842) |
| Rules + knowledge graph + heuristics (answers 83%, precision 1.00) | 0.828 (0.777–0.879) | 0.828 (0.777–0.879) |
| Decision tree only | 0.609 (0.539–0.674) | 0.958 (0.930–0.981) |
| **Rules + knowledge graph + heuristics, then tree** | **0.930 (0.898–0.963)** | **1.000** |

On the 145 faults the knowledge graph does not list, adding the decision-tree fallback raises
accuracy from 0.745 to 0.897 with rules, knowledge and heuristics otherwise unchanged;
removing the knowledge graph drops accuracy on the faults it covers from 1.000 to
0.643. The rules and knowledge were written by the team, so their scores on team-designed
scenarios are optimistic; the remaining errors (a data-dict `KeyError`, a buggy fixture, a
removed library submodule) are listed in the report. Full tables, confusion matrix and
per-scenario results: [examples/diagnosis-evaluation/REPORT.md](examples/diagnosis-evaluation/REPORT.md).

**Hard cases.** 30 further cases use documented behaviour changes of installed libraries
(NumPy 2, PyYAML 6, pydantic 2, Click 8.2) that the knowledge base does not list, plus a
two-layer fault. With the tree trained on the 215 cases, FixFirst named the cause in 5 of 30.
Two general heuristics written afterwards (H07: an imported library function rejects the call's
arguments; H08: a library the project calls raises after a major upgrade past the declared lower
bound) raise this to 15 of 30, without changing any result above. Because they were written after
seeing these cases, 15 of 30 is a development result. Both NumPy changes (a changed `repr`, a
changed type promotion) and pydantic's stricter validation are still missed:
[examples/hard-evaluation/REPORT.md](examples/hard-evaluation/REPORT.md).

**Real projects.** On 13 open-source projects it had never seen (9 domains, Python 3.9–3.14,
ground truth written before the first run; [docs/GENERALISATION.md](docs/GENERALISATION.md)),
FixFirst's first step was right for 2 of 13 at first and named the cause in 6. Every failure had
a general cause (its own Python 3.9 support, pytest 9 subtests, unread `setup.py`, advice that
asked pip to install Python, ...). After fixing those causes, adding the release search and
reading lock files, it is right for 12 of 13 on the same projects; that figure is not held out.
Earlier walk-throughs ([docs/REAL_PROJECTS.md](docs/REAL_PROJECTS.md)) led Flask 1.1.4 on
today's libraries from "no test can run" to 525 passing tests. No user study has been run yet.

## Command line

```bash
source .venv/bin/activate
fixfirst init /path/to/project --python /path/to/project/.venv/bin/python --goal pass_tests
fixfirst scan SESSION_ID                       # all checks for the goal
fixfirst scan SESSION_ID --checks pytest_run --nodes 'tests/test_a.py::test_x'
fixfirst show SESSION_ID                       # issues, causes, next steps
fixfirst ask SESSION_ID "what is the root cause"
fixfirst ask SESSION_ID "which package provides cv2"
fixfirst run SESSION_ID ACTION_ID              # run a step's check, e.g. a release search
fixfirst mark-fixed SESSION_ID ISSUE_ID        # then re-run the check to verify
fixfirst report SESSION_ID --open
fixfirst export SESSION_ID --output shared.html   # redacted copy for sharing
fixfirst knowledge --output kg.json            # domain knowledge graph + rules
fixfirst interactive                           # terminal menu
```

Goals: `collect_tests` (default), `check_style`, `pass_tests`. Sessions live in `.fixfirst/`
under the current directory (`--store` or `FIXFIRST_STORE` changes it). `--no-classifier` uses
rules and knowledge only; `--model` loads another decision tree.

Experiments:

```bash
fixfirst dataset --suite diagnosis --output workbench/diagnosis   # ~2 minutes, real runs
fixfirst evaluate workbench/diagnosis --output workbench/diagnosis-eval
fixfirst evaluate examples/diagnosis-dataset --output workbench/re-eval   # no execution
python scripts/record_playground.py --output workbench/playground
fixfirst historical --assets examples/historical-regressions/assets --output workbench/replay
python scripts/setup_real_world.py ../test-projects/generalisation   # the 13 held-out projects
python scripts/run_real_world.py ../test-projects/generalisation --search
python scripts/heldout.py -h             # a new held-out batch: plain pytest, copies, labels, scores
python scripts/collect_public_data.py    # PyDFix and BugsInPy subsets, see docs/DATA_SOURCES.md
python scripts/bugsinpy_case.py tqdm 2 --deps pytest nose   # reproduce one BugsInPy bug, check it
```

## Coding agents (MCP)

`fixfirst mcp` offers FixFirst to coding agents over the Model Context Protocol (stdio, no extra
dependency). An agent gets three tools:

| Tool | What it does |
|---|---|
| `diagnose` | runs the checks for a goal (default `pass_tests`) on a project folder and returns the steps to fix, most important first, each with its location, cause, rule and how to confirm it |
| `check_again` | re-runs the checks after the agent changed the code and reports what is now fixed and what is new; the goal counts as reached only when a real check passes |
| `explain` | the error, rules and documentation behind a step, and the checks that ran; runs nothing |

The server's instructions tell the agent to diagnose first, fix the first step, check again, and
stop once the goal is reached. The agent edits the code; FixFirst never does. Sessions are kept in
`~/.fixfirst/sessions`, outside the project being fixed, and `fixfirst --store
~/.fixfirst/sessions serve` shows them in the web interface. For Claude Code or any client that
reads `mcpServers` (for example a project's `.mcp.json`):

```json
{
  "mcpServers": {
    "fixfirst": {
      "command": "/path/to/FixFirst/.venv/bin/python",
      "args": ["-m", "fixfirst", "mcp"]
    }
  }
}
```

`experiments/agent_baseline/` compares local models fixing failures with and without these tools.

## Scope and safety

- Supported: small Python projects on macOS, Linux and Windows; target interpreters Python
  3.9–3.14, tested (venv, uv or conda); pytest, Ruff, pip. Declarations are read statically from
  `pyproject.toml` (PEP 621, dependency groups, flit), `requirements*.txt`, `setup.cfg` and
  literal lists in `setup.py` (never executed); lock files give the versions a project was
  tested with. Windows support is new and is being validated on real machines.
- Checks run as if the project's virtual environment were activated. The release search runs
  only when asked, installs prebuilt wheels only (no build scripts) into a throwaway
  environment and needs internet access.
- Checks run with timeouts, output limits and no shell. The environment snapshot runs outside
  the project so project files cannot shadow the standard library during the check.
- Output is redacted before it is stored: credentials in URLs, token/password assignments,
  secret-like dictionary values and `os.environ` dumps.
- An issue closes only after a completed check of the same scope and interpreter passes.
  Imported logs, partial runs, skipped or xfail tests, deleted tests and relaxed declarations
  never count as fixes.
- The web interface binds to 127.0.0.1, requires a per-launch token for every change and
  checks the Host header.
- The MCP server talks over stdio only. Its tools run the same checks as the command line
  (running tests executes project code) and never edit files.

## Repository

| Path | Contents |
|---|---|
| `src/fixfirst/` | the package (see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)) |
| `src/fixfirst/knowledge/` | rule base, domain knowledge, bundled decision tree |
| `tests/` | 232 tests, most running real subprocesses; Windows runs all of them, macOS and Linux skip one PowerShell-only test |
| `experiments/` | agent baseline: local models fixing failures with and without FixFirst ([README](experiments/agent_baseline/README.md)) |
| `examples/` | recorded runs, datasets, experiment reports and the real-world check ([overview](examples/README.md)) |
| `docs/` | architecture, data sources, generalisation check, real-project case studies, course alignment, team plan and task cards (`后续计划.md`, `tasks/`), a technical study guide in Chinese (`技术原理详解.md`), team notes (`队友说明.md`), optimisation log; `docs/history/` keeps earlier versions' records |
| `scripts/` | setup (macOS/Linux/Windows), real-project set-up and batch runs, demo recording |

```bash
.venv/bin/ruff check src tests scripts experiments
.venv/bin/pytest -q
```

## Limitations

- The diagnosis dataset is synthetic: one injected fault per case in five templates. It
  measures diagnosis, not time saved; a user study is still to be done.
- The knowledge graph covers selected releases of selected libraries; anything else falls back
  to evidence rules, heuristics, the release search and the classifier.
- Release search considers stable older releases with compatible wheels and stops after 12
  trials. It may miss a working release or leave newer releases unchecked. An unfinished or
  failed trial does not prove that no older version works; a verified import still needs the
  project's tests to confirm the full environment.
- Behaviour changes that raise no "name is missing" error (a library returning different
  results) are only recognised through a lock file; otherwise they look like code defects.
- The only held-out real-world measurement is round 1 of the generalisation check (2 of 13);
  the improved version needs a new set of projects chosen by someone else.
- Defects inside third-party libraries (see `examples/historical-regressions/`) are outside
  the five root-cause classes.

## AI assistance

Parts of the code and documentation were written with AI coding assistants (OpenAI Codex for
v0.1–v0.3 and the v0.6 fixes, Anthropic Claude for v0.4–v0.5). The team is responsible for reviewing, understanding and
presenting the work.
