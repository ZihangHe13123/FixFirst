# FixFirst

**Find the root cause of Python test failures from real evidence, then verify every fix.**

FixFirst runs your project's own checks (environment snapshot, dependency declarations,
`pip check`, pytest collection and runs, Ruff), groups repeated errors, diagnoses the root
cause of each failure, ranks what to do next for your goal, and closes an issue only when a
completed check of the same scope proves it fixed. It runs locally, never edits your code and
never installs packages.

NUS-ISS Intelligent Reasoning Systems practice module, Group 24 · version 0.4.0

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

The browser opens the local interface:

1. Choose your project folder (type it or press *Browse…*). FixFirst finds the project's own
   `.venv` and tells you if pytest is missing there.
2. Pick a goal (*Make my tests pass* by default) and press **Check my project**.
3. Follow the numbered steps. Each says which file and line to change, why, and how to confirm.
   After changing your code, press **Check again**; a step only counts as fixed when a real
   check passes.

No project at hand? Press *Open a sample project* on the start page: four faults, four causes,
with the changes listed in its `FIXES.md`. You can also double-click `start-fixfirst.command`
(macOS) or `start-fixfirst.bat` (Windows). Checks import the project's code, as its tests would;
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

## How it reasons

| Technique | What it does | Code |
|---|---|---|
| Knowledge-based rules | A production system with variables, stratified negation and provenance. 56 rules in four phases derive goal relevance, diagnose causes, fall back to the classifier, and propose actions. | `engine.py`, `knowledge/rules.toml` |
| Knowledge graph | A curated domain graph (5 causes, 117 removed modules/APIs/arguments with the release that removed them, import-name → distribution mappings, 19 cited sources) that the rules query, and a per-session evidence graph (10 entity types, 15 relations) for explanations and questions. | `domain.py`, `knowledge/domain.toml`, `knowledge_graph.py` |
| Data mining | A Gini decision tree over 44 evidence features suggests a cause when no rule applies; TF-IDF + cosine similarity with complete-link grouping merges repeated messages. | `evidence.py`, `classification.py`, `grouping.py` |

Every recommendation traces back through the rule that proposed it, the facts it used and the
check record or release note those facts came from. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Results

215 executed single-fault cases (5 project templates × 43 scenarios, real libraries, labels from
the scenario definition). Accuracy of naming the root cause, with 95% bootstrap intervals:

| Method | Unseen fault type (leave one scenario out) | Unseen project structure (leave one template out) |
|---|---|---|
| Parser category only (FixFirst 0.3 behaviour) | 0.419 (0.353–0.484) | 0.419 (0.353–0.484) |
| Rules without the knowledge graph | 0.488 | 0.488 |
| Rules + knowledge graph (answers 79% of cases, precision 1.00) | 0.791 (0.740–0.842) | 0.791 (0.740–0.842) |
| Decision tree only | 0.609 (0.539–0.674) | 0.958 (0.930–0.981) |
| **Rules + knowledge graph, then tree** | **0.930 (0.898–0.963)** | **1.000** |

On faults the knowledge graph does not list, the hybrid reaches 0.897 against 0.690 for rules
alone; removing the knowledge graph drops accuracy on the faults it covers from 1.000 to
0.643. The rules and knowledge were written by the team, so their scores on team-designed
scenarios are optimistic; the remaining errors (a data-dict `KeyError`, a buggy fixture, a
removed library submodule) are listed in the report. Full tables, confusion matrix and
per-scenario results: [examples/diagnosis-evaluation/REPORT.md](examples/diagnosis-evaluation/REPORT.md).
No user study has been run yet.

## Command line

```bash
source .venv/bin/activate
fixfirst init /path/to/project --python /path/to/project/.venv/bin/python --goal pass_tests
fixfirst scan SESSION_ID                       # all checks for the goal
fixfirst scan SESSION_ID --checks pytest_run --nodes 'tests/test_a.py::test_x'
fixfirst show SESSION_ID                       # issues, causes, next steps
fixfirst ask SESSION_ID "what is the root cause"
fixfirst ask SESSION_ID "which package provides cv2"
fixfirst mark-fixed SESSION_ID ISSUE_ID        # then re-run the check to verify
fixfirst report SESSION_ID --open
fixfirst export SESSION_ID --output shared.html   # redacted copy for sharing
fixfirst knowledge --output kg.json            # domain knowledge graph + rules
fixfirst interactive                           # terminal menu
```

Goals: `collect_tests` (default), `check_style`, `pass_tests`. Sessions live in `.fixfirst/`
under the current directory (`--store` changes it). `--no-classifier` uses rules and knowledge
only; `--model` loads another decision tree.

Experiments:

```bash
fixfirst dataset --suite diagnosis --output workbench/diagnosis   # ~2 minutes, real runs
fixfirst evaluate workbench/diagnosis --output workbench/diagnosis-eval
fixfirst evaluate examples/diagnosis-dataset --output workbench/re-eval   # no execution
python scripts/record_playground.py --output workbench/playground
fixfirst historical --assets examples/historical-regressions/assets --output workbench/replay
```

## Scope and safety

- Supported: small Python projects on macOS, Linux and Windows; pytest, Ruff, pip; static
  `pyproject.toml`, `requirements*.txt` and `setup.cfg` declarations. Windows support is new
  and is being validated on real machines.
- Checks run with timeouts, output limits and no shell. The environment snapshot runs outside
  the project so project files cannot shadow the standard library during the check.
- Output is redacted before it is stored: credentials in URLs, token/password assignments,
  secret-like dictionary values and `os.environ` dumps.
- An issue closes only after a completed check of the same scope and interpreter passes.
  Imported logs, partial runs, skipped or xfail tests, deleted tests and relaxed declarations
  never count as fixes.
- The web interface binds to 127.0.0.1, requires a per-launch token for every change and
  checks the Host header.

## Repository

| Path | Contents |
|---|---|
| `src/fixfirst/` | the package (see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)) |
| `src/fixfirst/knowledge/` | rule base, domain knowledge, bundled decision tree |
| `tests/` | 104 tests, most running real subprocesses |
| `examples/` | recorded runs, datasets and experiment reports ([overview](examples/README.md)) |
| `docs/` | architecture, course alignment, team notes |

```bash
.venv/bin/ruff check src tests scripts
.venv/bin/pytest -q
```

## Limitations

- The diagnosis dataset is synthetic: one injected fault per case in five templates. It
  measures diagnosis, not time saved; a user study is still to be done.
- The knowledge graph covers selected releases of selected libraries; anything else falls back
  to evidence rules and the classifier.
- Defects inside third-party libraries (see `examples/historical-regressions/`) are outside
  the five root-cause classes.

## AI assistance

Parts of the code and documentation were written with AI coding assistants (OpenAI Codex for
v0.1–v0.3, Anthropic Claude for v0.4). The team is responsible for reviewing, understanding and
presenting the work.
