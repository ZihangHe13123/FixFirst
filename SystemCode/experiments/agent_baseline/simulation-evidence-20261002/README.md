# Simulation evidence, 2026-10-02: the eleven settings before and after the analysis fixes

Synthetic only: `task_analysis.py --simulate` draws tasks with known fix probabilities. No experiment's
results, labels, models or held-out material are read. Nothing here has a local path.

## What was run

Eleven settings, each twice:

- **before**: with the code that produced the figures reported on 2026-10-01. F8x3, F6x3, F8x3c and F8x5 come
  from `bedb38b`; A to G come from `304f9dc`.
- **after**: with `7914699`, the commit with the fixes of Codex's reviews.

Every setting uses 2000 replicates, 1000 bootstrap resamples and seed 20261001.

| Setting | Tasks | Runs per arm | Baseline fix probability | Effect model | Correlation | Effect parameters |
|---|---|---|---|---|---|---|
| F8x3 | 8 | 3 | uniform 0.1–0.9 | shift | 0 | 0, 0.1, 0.2, 0.3, 0.4 |
| F6x3 | 6 | 3 | uniform 0.1–0.9 | shift | 0 | 0, 0.1, 0.2, 0.3, 0.4 |
| F8x3c | 8 | 3 | uniform 0.6–1.0 | shift | 0 | 0, 0.1, 0.2, 0.3, 0.4 |
| F8x5 | 8 | 5 | uniform 0.1–0.9 | shift | 0 | 0, 0.1, 0.2, 0.3, 0.4 |
| A | 8 | 3 | uniform 0.1–0.9 | shift | 0 | 0, 0.2, 0.3 |
| B | 8 | 3 | beta(0.5, 0.5) | shift | 0 | 0, 0.2, 0.3 |
| C | 8 | 3 | uniform 0–0.3 | shift | 0 | 0, 0.2, 0.3 |
| D | 8 | 3 | uniform 0.1–0.9 | half | 0 | 0, 0.1, 0.15 |
| E | 8 | 3 | uniform 0.1–0.9 | share | 0 | 0, 0.4, 0.6 |
| F | 8 | 3 | uniform 0.1–0.9 | shift | 0.7 | 0, 0.2, 0.3 |
| G | 8 | 3 | beta(0.5, 0.5) | half | 0.7 | 0, 0.1, 0.15 |

Effect models:

- **shift**: every task gains the effect, capped at 1.
- **share**: FixFirst fixes that share of the remaining failures.
- **half**: each task, with chance 1/2, gains twice the effect (capped); otherwise it gains nothing.

Correlation is the chance that a task's runs in one arm all repeat one draw. The true mean gain is the
average over 200,000 draws of the task population. So for `shift` it is not always the effect parameter;
with uniform 0.1–0.9, for example, it is 0.194 for 0.2.

## Where everything is

| File | What it holds |
|---|---|
| `MANIFEST.json` | For each setting: its parameters and seed, and for before and after the code commit, the exact command (relative to the repository root), the output path and the output's SHA-256. It also gives the three commits with the SHA-256 of `task_analysis.py` and `compare_arms.py` at each, the Python version and the random streams. |
| `before/<setting>.json`, `after/<setting>.json` | The outputs: the settings, then per effect the true mean gain, how often the t-interval and the bootstrap interval exclude 0 and cover the truth, how often the sign test has p < 0.05, and (after only) how often no interval was given. |
| `COMPARISON.md` | Every setting and effect, before → after. `python compare.py` regenerates it from the two folders. |
| `make_evidence.py` | Re-runs all 22 from three clean checkouts and rewrites the outputs and the manifest:<br>`python make_evidence.py PYTHON CHECKOUT_bedb38b CHECKOUT_304f9dc CHECKOUT_7914699`<br>It refuses a checkout at another commit, or with uncommitted changes outside this folder. |

## Checks made

- The 11 `before` files are byte-identical to the files behind the figures reported on 2026-10-01.
  `before/F8x3.json` has SHA-256 `fdddff4a59acc0fc1c73d80c8f8773707bf19e2462a51e5765368a3b296e22db`, the digest
  Codex's review also recorded for its replay of that setting.
- The 11 `after` files are byte-identical to the reruns reported on 2026-10-02 before 7914699 was
  committed. Between those reruns and the commit only text in docstrings changed.
- Python 3.12.13 on macOS; the simulation uses only the standard library.

## What changed between before and after

The data are drawn the same way. Only the counting changed:

- Decisions now use the unrounded intervals. Before, they used intervals rounded to three decimals.
- A replicate whose task differences are all equal now has no interval. It neither excludes 0 nor covers
  the truth, and is counted as `no_interval`. Before, it counted as a point interval at its mean.

The bootstrap's random draws are the same in all three commits: the seed string is
`{seed}|{effect}|{replicate}` plus the same group and arms.

## How far the figures go

These are shares under the stated data-generating settings. With 2000 replicates, a share near 0.05 has
a Monte Carlo standard error of about 0.5 points, and one near 0.9 about 0.7 points. They show how the
analysis behaves in these settings, not a guarantee for real tasks. The t-interval's coverage fell to
0.906 in F8x3c with a true gain of 0.15.
