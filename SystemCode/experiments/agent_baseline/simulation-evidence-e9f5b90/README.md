# Simulation evidence for e9f5b90

This is the same eleven settings as `../simulation-evidence-20261002/`, run with commit
`e9f5b9034554965606ffbba810ae20301305bb8f`.

That commit changed how replicates are counted. A replicate whose task differences agree within 1e-9,
not only exactly, is now degenerate and has no interval. Each result now also keeps its integer counts,
and its coverage among the replicates that had an interval.

Synthetic only: no experiment's results, labels, models or held-out material are read. There are no
local paths. The earlier package is left unchanged.

## Files

| File | What it holds |
|---|---|
| `MANIFEST.json` | Per setting: the parameters, seed (20261001), replicates (2000) and bootstrap resamples (1000); the exact command, relative to the repository root; the output path and its SHA-256. Also the full commit with the SHA-256 of `task_analysis.py` and `compare_arms.py`, and the Python version (3.12.13). |
| `results/<setting>.json` | Per effect: the true mean gain; how often the t-interval and the bootstrap interval exclude 0 and cover the truth, and how often the sign test has p < 0.05; how often no interval was given. Also `counts` (integers out of `replicates`) and `*_covers_truth_given_interval` (coverage over replicates that had an interval). |
| `COMPARISON.md` | 7914699 against e9f5b90, for every setting and effect. |
| `make_evidence.py` | Re-runs the eleven settings and rewrites `results/` and the manifest:<br>`python make_evidence.py PYTHON CHECKOUT` |
| `compare.py` | Checks both packages, then writes `COMPARISON.md`. |

`make_evidence.py` refuses a checkout unless:
- its HEAD equals the full commit above;
- `git status --untracked-files=all` shows no change anywhere in the working tree outside this folder.

It records the interpreter's version but does not enforce it.

`compare.py` checks before it renders anything:
- every output's SHA-256 against its package's manifest;
- every output's own content against its own manifest entry: tasks, runs per arm, baseline, effect
  model, correlation, replicates, resamples and seed, and the effects in order, both in its settings and
  in its result rows. A wrong file whose digest was updated with it is refused;
- that both packages have the same settings and parameters, in the same order;
- that every effect row pairs up, with the same true mean gain on both sides;
- in e9f5b90's results:
  - every count is a whole number from 0 to the replicates;
  - every displayed share equals its count over the replicates;
  - the coverage given an interval equals its count over the replicates that had one;
  - each zero-effect row splits its replicates exactly into false positives, coverage and no interval,
    for the t-interval and for the bootstrap.

`tests/test_simulation_evidence.py` replays these refusals on tampered copies of the two packages.

The package stays bound to e9f5b90. Later commits on the branch that leave the simulation alone do not
change that. To re-run it, use a checkout of exactly that commit.

## Results

The data are drawn exactly as before. 17 of the 246 displayed shares changed, each by at most 0.002. The
cause is a few replicates per setting that are now degenerate: the displayed `no interval` share rose in
7 of the 41 rows, by at most 0.002 (F6x3 at an effect of 0.3: 0.000 → 0.002). The earlier package kept
only rounded shares, so the exact number of newly degenerate replicates cannot be read from it.

Ranges over the eleven settings:

| Measure | t-interval | Bootstrap |
|---|---|---|
| False positives with no effect (11 rows) | 1.5–5.9% | 8.8–11.8% |
| Coverage over all replicates (41 rows) | 90.6–96.4% | 82.3–90.7% |
| Coverage over replicates with an interval | 91.8–98.4% | 83.7–91.0% |
| Replicates without an interval | 0–3.0% | |

The lowest t coverage is 0.906, in F8x3c at an effect of 0.2 (true mean gain 0.15).

Read the two coverages apart. In G with no effect, t covers 0.955 of all replicates but 0.984 of those
with an interval, and 3.0% have none. A coverage over all replicates closer to 0.95 is therefore not, by
itself, a sign of better calibration.

## How far the figures go

These are shares under the stated data-generating settings, with Monte Carlo error from 2000 replicates
(about 0.5 points near 0.05, about 0.65 near 0.9; compute per cell). They are not a guarantee for real
tasks and not intervals for FixFirst's effect.

## Corrections to the earlier package's README

- Its cleanliness check covered only `experiments/` and `src/`, outside its own folder, not the whole
  working tree as its README implied. This package's check covers the whole tree.
- Its `compare.py` rendered without checking digests or row pairing. That package's files were checked
  independently and found complete.
- The draft's earlier sentence "every figure changed by 0–2 points" was wrong. Between before and
  7914699 the largest displayed change was 3.6 points (A at 0.2, bootstrap excluding 0: 0.411 → 0.447),
  and 14 cells changed by more than 2 points.
