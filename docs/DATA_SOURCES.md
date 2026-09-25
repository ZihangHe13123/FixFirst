# Data and knowledge sources

Every source FixFirst is built or evaluated on, what it is used for, and how far it has got.
Numbers are from the files in this repository; each row links to where it can be regenerated.

## Overview

| Source | Kind | Size | Used for | Status |
|---|---|---|---|---|
| Official documentation and release notes | Knowledge | 23 cited sources → 119 removed modules/APIs/arguments/usages/fixtures, 10 deprecations, 44 pytest fixtures → plugins, import-name → package map | The domain knowledge graph that the rules query (`src/fixfirst/knowledge/domain.toml`) | In use |
| Generated fault projects | Executed, labelled | 215 cases = 5 project templates × 43 fault scenarios, 5 root causes, 0 rejected | Root-cause diagnosis: baselines, ablations, two cross-validation protocols ([report](../examples/diagnosis-evaluation/REPORT.md)) | Done |
| Controlled grouping sets | Executed, labelled | 30 collection + 30 execution cases | Message grouping, exact text vs TF-IDF ([collection](../examples/grouping-evaluation/collection/REPORT.md), [execution](../examples/grouping-evaluation/execution/REPORT.md)) | Done; too easy to separate the methods, needs harder cases |
| Upstream library regressions | Real defects, official wheels | 4 defects in packaging and click, SHA256-pinned | Verification on real library defects, replayed offline ([report](../examples/historical-regressions/REPORT.md)) | Done |
| Real-project walk-throughs | Real projects | humanize (healthy), humanize without test dependencies, Flask 1.1.4 on today's libraries | End-to-end use: Flask from no runnable test to 525 passing ([record](REAL_PROJECTS.md)) | Done |
| Held-out real-world check | Real projects, labels committed before running | 13 open-source projects, 9 domains, Python 3.9–3.14 | First-step correctness on unseen projects ([record](GENERALISATION.md)) | Round 1 held out (2/13); a fresh set chosen by another member is next |
| **PyDFix** (ISSTA 2021) | Public research data, BSD-3-Clause | 1,927 table rows → **22 distinct import errors in 10 repositories** | External text-only check of parsing and knowledge coverage ([details](../examples/public-data/README.md)) | Collected; labels to do |
| **BugsInPy** (ESEC/FSE 2020) | Public benchmark, facts and links only | **501 real bugs in 17 projects**; 70 bugs in 5 projects need nothing compiled | Verification on real code defects; checking that code defects are not blamed on the environment ([details](../examples/public-data/README.md)) | Indexed; none reproduced yet |

Regenerate the two public sources with `.venv/bin/python scripts/collect_public_data.py`.

## How the sources map to the proposal's evaluation plan

| Proposal evaluation area | Sources |
|---|---|
| Message grouping | Controlled grouping sets; harder cases still needed |
| Issue classification (root cause) | Generated fault projects; PyDFix cases as an external text-only check |
| Next-step guidance | Held-out real-world check; baselines (message order, fixed category order) still to add |
| Verification | Controlled execution cases, upstream regressions; BugsInPy for real code defects |
| User troubleshooting | Playground sample project; user study still to run |

## What changed from the proposal, and why

The proposal named PyDFix as the main source and BugsInPy for live verification. Checking both
(`examples/public-data/`) showed:

- **PyDFix is mostly outside FixFirst's scope.** Its tables hold only the flagged error line,
  not the logs, and most rows are 2015–2020 CI build and install failures (`setup.py`,
  `build_ext`) or Python 2.7/3.4 version checks. The rows FixFirst can read, import errors,
  collapse to 22 distinct cases. It stays in the evaluation as a small external check, not as
  the main dataset.
- **BugsInPy only contains code defects**, all in one of FixFirst's five causes, so it cannot
  test the environment and version diagnosis that is FixFirst's main contribution. It is used
  for what it is good at: verification, and a check that genuine code defects do not get
  environment advice.
- **The main evaluation therefore rests on data the team can execute and label**: the 215
  generated cases for controlled comparisons, and real open-source projects run on today's
  Python and libraries for realism, where 12 of 13 projects had failing tests when installed
  the way their own files describe.

PyDFix's own result supports the problem FixFirst addresses: 1,921 of the 2,702 real builds it
rebuilt (71.1%) no longer reproduced because of dependency errors
([Mukherjee et al., ISSTA 2021](https://dl.acm.org/doi/abs/10.1145/3460319.3464797)).
