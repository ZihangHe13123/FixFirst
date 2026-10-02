# The confirmatory family, simulated with c464214

What the registered confirmatory analysis does when the truth is known: three models (5, 5 and 3 runs per
arm, as decided on 2 Oct 2026), eight tasks, mcp − baseline per model, Holm's procedure at 0.05 on the
paired t-test's p-values. Each replicate goes through `task_analysis.analyse()` with a family, so what is
simulated is the path a real analysis takes. Code: commit `c464214e860fd536a1286ebbf57e20516dd93d79`.

Synthetic only: no experiment's results, labels, models or held-out material are read. There are no local
paths.

## Files

| File | What it holds |
|---|---|
| `MANIFEST.json` | Per setting: the parameters, seed (20261001), replicates (2000) and alpha (0.05); the exact command, relative to the repository root; the output path and its SHA-256. Also the full commit with the SHA-256 of `task_analysis.py` and `compare_arms.py`, and the Python version (3.12.13). |
| `results/<setting>.json` | The setting's own parameters, and per model: its runs, effect and true mean difference, whether its null is true, how often Holm rejected it, how often its unadjusted p-value was below 0.05, how often it could not be estimated. For the family: any rejection, any false rejection, every helped model rejected, and the same for unadjusted p-values. Shares and integer counts. |
| `SUMMARY.md` | One row per setting, written by `check.py`. |
| `make_evidence.py` | Re-runs the thirteen settings and rewrites `results/` and the manifest:<br>`python make_evidence.py PYTHON CHECKOUT` |
| `check.py` | Checks the package, then writes `SUMMARY.md`. |

`make_evidence.py` refuses a checkout unless its HEAD equals the full commit above and
`git status --untracked-files=all` shows no change anywhere in the working tree outside this folder. It
records the interpreter's version but does not enforce it.

`check.py` checks before it writes anything:
- every output's SHA-256 against the manifest;
- every output's own content against its manifest entry: runs per model, effects, tasks, baseline, effect
  model, correlation, whether the models share their tasks, replicates, seed, and the level alpha the
  family was decided at (0.05 in every setting; the summary names the level it checked). A wrong file
  whose digest was updated with it is refused;
- per model: its runs and effect are the setting's, in order; a true null shows a true mean difference of
  0, and a model without an effect has a true null;
- every count is a whole number from 0 to the replicates, and every displayed share is its count over the
  replicates;
- Holm never rejects where the unadjusted p-value is not below alpha, per model and for "any model"; a
  false rejection is a rejection; with every null true, every rejection is a false one; a model is never
  rejected in a replicate where it could not be estimated;
- the family's counts fit the models' own: "any model" happened at least as often as its most frequent
  model and at most as often as all of them together, "every helped model" at most as often as its rarest,
  and an event over no model never happened. These are necessary conditions on the counts; the package
  holds no replicate-by-replicate record to rebuild the joint events from;
- a share that needs a true null, or a helped model, is given exactly when the setting has one.

`tests/test_family_evidence.py` replays these refusals on tampered copies.

## Results

A false rejection is the rejection of a model whose true mean difference is 0. Shares are exact for 2000
replicates (multiples of 0.05%).

| Measure | After Holm | Unadjusted |
|---|---|---|
| Any false rejection, no effect in any model (6 settings) | 1.15–4.85% | 11.35–17.70% |
| Any false rejection, one or two models helped (3 settings) | 3.70–4.30% | 7.05–12.35% |
| A model with a true gain of 0.275 rejected, 5 runs per arm (all three helped) | 58.75%, 55.65% | 74.00%, 73.10% |
| The same, 3 runs per arm | 40.35% | 55.90% |
| All three helped by 0.275: every one rejected | 23.70% | |

Other settings, after Holm, per model (5 / 5 / 3 runs):
- a true gain of 0.194: 25.85% / 24.40% / 16.35%;
- a gain of 0.275 when a task's runs repeat one draw with chance 0.7: 10.35% / 9.95% / 8.75%;
- a gain on half the tasks only (true means 0.137, 0.137 and 0.138): 9.00% / 8.60% / 5.75%.

The price of the adjustment is power: where only the first model is helped by 0.275, it is rejected in
50.50% of replicates, against 74.00% without the adjustment.

## How far the figures go

These are shares under the stated data-generating settings, with Monte Carlo error from 2000 replicates
(about 0.5 points near 0.05, about 1.1 near 0.5; compute per cell). 4.85% is not shown to be below 5%.
They are not a guarantee for real tasks: Holm's procedure is valid for any dependence between the models
only if each model's own test holds its level, and the single paired t-test does not always. Here a single
model's unadjusted p-value was below 0.05 in 3.70–7.05% of replicates with no effect (4.70–7.05% in the
three settings with baselines on 0.1–0.9 and runs drawn independently). In the experiment the three models
meet the same tasks; the settings share the tasks' baselines, which is one form of that dependence and not
a measurement of it.
