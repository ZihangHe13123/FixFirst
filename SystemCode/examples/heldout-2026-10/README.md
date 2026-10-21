# FixFirst held-out evaluation — 12 unseen Python projects (2026-10)

Private working repository holding the held-out set for the FixFirst evaluation: 12 real
Python projects that were **not** used while the rules and the decision tree were built,
each with a hand-written, independently reviewed label, run through the frozen FixFirst
**v0.7.0** exactly once.

Roles: **A** selected the projects, built the environments, wrote the labels and ran the
frozen version; **C** independently labelled, reviewed and independently scored; A and C
jointly adjudicated. This repository is published so the commit timestamps are checkable.

> **Disclosure — AI assistance.** Error *hunting* used AI; the label columns were written by
> people. Every judgement column (`root_cause`, `first_step`, `also_acceptable`,
> `partial_if`, `wrong_if`) was written line by line by A on the basis of sources A opened
> and verified, then independently reviewed by C. AI never produced a label column. Details
> in §4 and in `ai-assistance.md`.

---

## 1. Timeline and freeze

| When (Asia/Shanghai) | What | Artifact |
|---|---|---|
| 2026-09-30 20:59 (posted) | A1: labels written and committed to this repository | `labels-A.csv` @ `0bbcc35` |
| 2026-10-01 18:00 | C1: C's independent labels committed *before* seeing A's | `labels-C.csv` @ `b34263a` |
| 2026-10-01 18:19 (posted) | C1: review merged, final label commit | `labels.csv` @ `03f58d9` |
| 2026-10-01 23:24 | B5: FixFirst `v0.7.0` technical freeze | annotated tag `v0.7.0` → `c8151af` |
| 2026-10-02 | A2: raw pytest re-captured to confirm the environment is unchanged | `pytest-before-run/` |
| 2026-10-02 15:22 | A2: the single official run on `v0.7.0` | `results-v0.7.0.json` @ `a68ea23` |
| 2026-10-02 | A2: A and C scored independently, then reconciled | `scores-A.csv`, `scores-C.csv`, `scores.csv`, `scores-review.md` |

The commit numbers posted in the A1 and C1 Issues (`0bbcc35`, `03f58d9`) are the ones above.
The A2 run checked out `v0.7.0` (`git describe` → `v0.7.0`) and ran against the same
environments built in A1. `labels.csv` is byte-identical to the C1-final commit `03f58d9`.

**Environment unchanged.** `pytest-before-run/index.json` was compared per project against
A1's `pytest/index.json`: **12/12 summaries identical**, with one known difference that is a
parser regression, not environment drift — `python-slugify`'s summary string is `'FAILURES'`
under the v0.7.0 `heldout.py` (whose `summary_line()` does not strip ANSI) while A1 recorded
`'7 failed, 124 passed'`; the real pytest banner is identical on both sides
(`7 failed, 124 passed`). The project's own `addopts = "--color=yes"` is the only source of
ANSI in the set. Per the task card the run continued without touching the environment.

## 2. Sampling

Chosen per a fixed procedure, **not** by how well FixFirst might do (the task card forbids
using FixFirst on these projects before the freeze).

- **Source:** the [awesome-python](https://github.com/vinta/awesome-python) list, read in
  list order within each category — no preference-based skipping. Candidates were taken from
  10 of its categories (Testing, Text Processing, CLI Development, Image Processing, Web
  Frameworks, ORM, HTTP Clients, Caching, Date and Time, Data Analysis).
- **Skip rules (only these):** not pure Python / needs a C extension to build; no
  pytest-runnable tests; tests need network or a paid service; or on the exclusion list
  (the 13 projects from the 9/24 pilot, flask 1.1.4, humanize, anything already in
  `examples/`, and the 17 BugsInPy projects reserved for B12).
- **Version choice:** for version-incompatibility candidates, the last release before
  2022-01-01; for `healthy` and `code_defect`, a release from the last two years. Python 3.12
  by default, with a few projects on 3.10/3.11/3.13.
- **How installed:** strictly per each project's own documentation (README / CONTRIBUTING /
  tox.ini / requirements-dev.txt / the test extra in setup.py or pyproject.toml). For the
  non-version root causes, one *realistic* variation was applied on top (omit the testing
  extra, do not install the project, omit an env var, …) and written into `scenario` **before**
  pytest was run.
- **Candidates recorded:** every candidate tried or skipped is in `candidates.csv` —
  **85 rows**: 7 rejected by a skip rule, 78 kept as candidates, **15 actually built and run**.
- **Selected:** the **12** projects in `projects.toml` / `labels.csv`. The other three that
  were built — `dogpile-cache`, `bottle` (kept as a reserve pair, recorded in
  `labels-reserve.csv`, excluded from the official directories) and `parsy` (dropped: its
  natural failure is not `local_module`) — are documented but not part of the 12.

Root-cause mix (target → actual): `version_incompatibility` 4, `missing_dependency` 2,
`local_module` 2, `config_missing` 2, `code_defect` 1, `healthy` 1.

## 3. Labels and independent review (A1 / C1)

- **Comparable cases:** m/N = **12/12**. No project appears in only one sheet; 0 pending,
  0 needing adjudication (`review-initial-C.md`).
- **Initial agreement on `root_cause`:** **12/12 (100%), Cohen's kappa 1.00** — comparing
  `labels-A.csv` against `labels-C.csv`, each written before its author saw the other's.
  A did use AI-assisted error hunting; the claim is therefore *independent human labelling
  with AI assistance on A's side only*, not "both sides fully unaided".
- After the independent comparison, A and C merged the `first_step` / `also_acceptable`
  wording project by project (12/12 agreed, 0 left open); click, python-qrcode and
  python-markdown had their layer ordering checked explicitly. Full record: `review.md`.

## 4. AI assistance

Full log: `ai-assistance.md`. Summary:

- **Model, A side:** main-session assistant **GPT-5.6 Sol** (A's confirmation); background
  execution agent — **model unknown** (its UI showed no version; recorded as unknown rather
  than guessed). **Purpose:** only "why does this error happen" — candidate causes, official
  docs / source locations at the relevant version, and minimal disambiguating experiments.
- **Cases assisted:** **12 of 12** on A's side. **C's independent pass used no AI** and did
  not open A's notes or AI answers until after committing `b34263a`; C used a terminal AI
  assistant afterwards only to run `heldout.py` and generate files, never to diagnose.
- **Human verification.** Every AI claim that reached a label was (a) checked against a
  first-hand source A opened — upstream commit / tag, `pyproject.toml`, `tox.ini`,
  `setup.py`, release notes — and (b) verified in a copy of the environment (`twin`), one
  intervention at a time. AI suggestions were rejected when the twin contradicted them;
  examples: "just upgrade pytest" for click (reproduced under pytest 9.1.1 → rejected),
  a single-site fix for python-qrcode (`ValueError` persisted from the test file → rejected),
  and `pkg_resources` being called a second defect (it is an artifact of the uv-created venv,
  pushed to `later_layers`). Each case's accepted/rejected suggestions and verification file
  are listed in `ai-assistance.md`.
- The pilot 9/24 projects are excluded from this set, as required, so no rule written with AI
  help was fitted on these 12.

## 5. The run

```bash
# on v0.7.0
python scripts/heldout.py pytest ~/heldout-projects --manifest projects.toml --output pytest-before-run
python scripts/run_real_world.py ~/heldout-projects --manifest projects.toml --search --output results-v0.7.0.json
```

One run only; nothing was re-run because a result looked bad. `--search` = when the first
step is "find an older version that still works" (the **Find it** affordance), the search is
continued and the first step *after* the search is recorded (the pre-search step is in
`search_offered`). Every project's raw pytest output is in `pytest/` (A1) and
`pytest-before-run/` (A2); the twins are in `twins/`.

## 6. Scoring (A2, steps 4–5)

Each of A and C scored independently against the rubric in `scoring-rubric.md`, then compared
with `heldout.py agree` (`scores-review.md`). **Only the first step** is scored — the first
thing a new user would act on.

- **Independent agreement: 9/12 (75%), Cohen's kappa 0.66.** Three rows differed —
  `python-qrcode`, `django-cacheops`, `django-storages`, all A `generic` vs C `partial`.
- **Reconciliation.** A read Axis A strictly: a cause *category* ("Version incompatibility",
  "Missing configuration") is not enough when the first step does not name the concrete
  dependency, setting, module, function or other specific cause. C initially treated the
  correct category as sufficient for Axis A. The reviewers resolved it by applying the
  rubric's named-cause requirement consistently with the already-agreed `python-slugify` case
  (cause category matched, first step named nothing, both scored `generic`). All three rows
  were reconciled to **`generic`**.
- **The independent sheets are unchanged.** `scores-A.csv` and `scores-C.csv` keep their own
  original calls, so 9/12, 75% and kappa 0.66 remain the true independent-scoring result.
  Only the final `scores.csv` records the consensus; the reasoning is in `scores-review.md`.

### Result

**Correct 4 / Partial 1 / Generic 6 / Wrong 1** (`scores-summary.md`).

| Root cause (label) | Projects | Correct | Partial | Generic | Wrong |
|---|---|---|---|---|---|
| version_incompatibility | 4 | 0 | 0 | 3 | 1 |
| missing_dependency | 2 | 1 | 1 | 0 | 0 |
| local_module | 2 | 2 | 0 | 0 | 0 |
| config_missing | 2 | 0 | 0 | 2 | 0 |
| code_defect | 1 | 0 | 0 | 1 | 0 |
| healthy | 1 | 1 | 0 | 0 | 0 |

**Scope.** N = 12; treat this as a small-sample result, not a general claim. Two patterns are
worth reporting but must stay scoped:

- The 4 `correct` rows all come from a named rule or `healthy`; all 4 rule-`F01` rows (no rule
  matched, decision-tree guess) landed in `generic`/`wrong` — **0/4**. With 4 samples this
  does not establish that `F01` is worse; it is only what this set shows.
- FixFirst's remediation commands set `--only-binary=:all:` (`dependency_advice.py:107,176`,
  `dependency_resolution.py:181,277,285`, `versions.py:146`). Any fix whose target has no
  wheel for the platform is therefore un-runnable by construction; `dateparser`/fasttext is
  the one observed instance.

### Per project (the 8 not scored `correct`)

| Project | Score | What FixFirst said, and why that is not a correct first step |
|---|---|---|
| click | wrong | Headline "1 problem to fix"; first step "Read the original output and investigate by hand", cause "Defect in project code or tests" (F01, hedged). The blocker is the pinned `py==1.10.0`, not click's code — this hits the label's `wrong_if`. |
| pytest | generic | First step "Check that the tool is available and ran to completion"; no cause given. Does not name the pinned pytest 6.2.5 / Python 3.12 incompatibility. |
| dateparser | partial | Correctly names the missing dependency fasttext (rule D20) with an install command, but the command sets `--only-binary=:all:` and fails (`No matching distribution found`; the only published artifact is an sdist). Cause right, step not executable → partial (twin: `twins/dateparser.a2-first-step.txt`). |
| python-qrcode | generic | First step "Check the import path and dependency declarations"; the only cause signal is the hedged category "Version incompatibility" (F01). Does not name the `strftime('%-d %b %Y')` Windows-portability issue. |
| httpx | generic | First step "Check that the tool is available and ran to completion"; no cause given. |
| python-slugify | generic | First step "Compare the failed assertion's expected and actual values" (rule D40, cause "Defect in project code or tests"); does not name `_modern_truncate` / the trailing-delimiter truncation. |
| django-cacheops | generic | First step "Read the original output and investigate by hand"; only the hedged category "Missing configuration" (F01). Does not name `DJANGO_SETTINGS_MODULE=tests.settings` / Django initialization. |
| django-storages | generic | First step "Inspect the exception raised while running the test"; only the hedged category "Missing configuration" (F01). Does not name `tests.settings`. |

`python-ftfy` (healthy), `robotframework`, `seleniumlibrary` (both `local_module`) and
`python-markdown` (`missing_dependency`) were scored `correct`.

## 7. Corrections to labels (labels **not** amended)

Per the card, `labels.csv` is frozen; discrepancies are recorded here instead
(cf. `examples/real-world/LABELS.md`, "Corrections").

1. **dateparser — reason corrected, conclusion unchanged.** The `checked_by_trying` cell says
   fasttext fails because a C++/MSVC toolchain is missing. A 2026-10-02 twin check found VS
   2022 Build Tools *are* installed and pip can invoke `cl.exe`; the real failure is that
   fasttext 0.9.2/0.9.3's bundled pybind11 is incompatible with that compiler (`C2672: no
   matching overload for pybind11::init`). The first layer still cannot be closed in this
   environment, so the label's conclusion stands; `first_step`'s "or another compatible
   installation path" already covers it. Details: `report-notes.md` §3.
2. **python-slugify — summary-string difference.** See §1: A1's `pytest/` capture recorded
   `7 failed, 124 passed`; the v0.7.0 `heldout.py` summary parser records `FAILURES` for the
   same run (ANSI-stripping landed later, in FixFirst PR #49, which does not affect the
   v0.7.0 tag). The underlying pytest result is identical; no label depends on the string.

## 8. Files

| Path | What |
|---|---|
| `projects.toml` | the 12 projects: repo, ref, install/layout scenario, per-project disclosure |
| `environments/` | version snapshots of each built environment |
| `pytest/`, `pytest-before-run/` | raw pytest output, A1 and A2 (environment-unchanged check) |
| `pytest-before-run/index.json` | per-project summary comparison |
| `labels-A.csv`, `labels-C.csv` | the two independent label sheets |
| `labels.csv` | the merged, final label set (12 rows) |
| `review-initial-C.md`, `review.md` | C1: independent review and merged decisions |
| `ai-assistance.md` | per-case AI-assistance record and verification sources |
| `scoring-rubric.md` | the scoring rubric, fixed **before** either reviewer filled a sheet |
| `results-v0.7.0.json` | the single FixFirst v0.7.0 run |
| `scores-A.csv`, `scores-C.csv` | the two independent scoring sheets (unchanged) |
| `scores.csv` | the agreed final scores |
| `scores-review.md`, `scores-summary.md` | agreement stats, reconciliation, result table |
| `twins/` | copy-environment verification records |
| `candidates.csv` | every candidate tried or skipped, with reasons |

`tools/`, `probe/`, `reserve/` and the screening caches are working artifacts and are
Git-ignored where noted in `.gitignore`.
