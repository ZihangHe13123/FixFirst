# Root-cause diagnosis: the frozen 0.8.0rc5 (task B6)

12 October 2026. Product source: commit `646c12a`, tag `b12-rc5-freeze-20261010`, package version
0.8.0rc5 (the source of `main` at `c56309a`). No language model was run for this report and no
project was executed again: everything is computed from saved observations.

The report in the parent folder is the evaluation of 24 September on 215 cases with the earlier
rules and the 44-feature tree. It is kept as it was. The numbers here are not a continuation of
that table: the cases (220), the rule base, the knowledge and the tree's features (81) differ.

**What kind of evidence this is.** The 220 ordinary and 30 hard cases are development data. The
rules, the knowledge base, the heuristics and the tree's features were written with these
scenarios in view, and the heuristics that decide the hard cases were written after seeing them.
Holding out a template or a scenario isolates what the tree of a fold has not seen; it does not
turn the result into performance on unseen projects. Real projects are in section 7.

## 1 Data and commands

- **Ordinary cases**: 220 = 5 project templates × 44 fault scenarios, one injected fault each,
  executed for real when they were collected. Labels from the scenario definition:
  missing_dependency 30, local_module 30, version_incompatibility 70, config_missing 30,
  code_defect 60.
- **Hard cases**: 30 = 5 templates × 6 scenarios (documented behaviour changes of installed
  libraries and one two-layer fault): local_module 5, version_incompatibility 25. Never used to
  train a tree.
- Both are the snapshots sealed on 3 October for the comparison with language models (task B3):
  `experiments/diagnosis_baseline/generated-results-20261004/inputs/data/snapshots/`.

```bash
SNAP=experiments/diagnosis_baseline/generated-results-20261004/inputs/data/snapshots
fixfirst evaluate $SNAP/diagnosis --output OUT/diagnosis
fixfirst evaluate $SNAP/hard --train $SNAP/diagnosis --output OUT/hard
python examples/diagnosis-evaluation/frozen-0.8.0rc5/tools/b6_replay.py . $SNAP OUT/product-replay.json
```

`fixfirst evaluate` fits a tree of its own for every fold. The shipped tree
(`src/fixfirst/knowledge/diagnosis_tree.json`, sha256 `189f712e…`) is neither written nor
retrained; its digest was the same before and after. `diagnosis/decision_tree.*` is the tree the
command fits on all 220 cases for display, not the shipped one.

## 2 The methods on the 220 ordinary cases

Correct answers of 220. "Template out": the tree of a fold has not seen the project template.
"Scenario out": it has not seen the fault scenario. Rows without a tree do not depend on the fold.

| Method | Template out | Scenario out | Accuracy, scenario out (95% interval) | Macro-F1 | Answers | Right when answering |
|---|---:|---:|---|---:|---:|---:|
| Parser category only | 90 | 90 | 0.409 (0.345–0.473) | 0.276 | 220 | 0.409 |
| Rules without the knowledge graph | 105 | 105 | 0.477 (0.414–0.545) | 0.603 | 110 | 0.955 |
| Rules + knowledge graph | 172 | 172 | 0.782 (0.727–0.836) | 0.884 | 172 | 1.000 |
| Rules + knowledge graph + heuristics | 183 | 183 | 0.832 (0.782–0.882) | 0.903 | 183 | 1.000 |
| Decision tree only | 220 | 191 | 0.868 (0.823–0.914) | 0.844 | 220 | 0.868 |
| Rules + heuristics without the knowledge graph, then tree | 205 | 205 | 0.932 (0.900–0.964) | 0.945 | 220 | 0.932 |
| Rules + knowledge graph + heuristics, then tree | 220 | 220 | 1.000 | 1.000 | 220 | 1.000 |

The two ablations the task asks for:

- **Without the knowledge graph**: 205 instead of 220. On the 70 cases whose fault the knowledge
  graph lists, accuracy falls from 1.000 to 0.786.
- **Without the tree**: 183 instead of 220. The rules, knowledge and heuristics answer 183 cases
  and are right in every one; the other 37 stay unanswered. The tree supplies those 37.

The tree alone names every cause when only the template is new, and 191 of 220 when the scenario
is new.

## 3 Per class and common misjudgements (scenario out)

Correct answers per class:

| Method | missing_dependency (30) | local_module (30) | version_incompatibility (70) | config_missing (30) | code_defect (60) |
|---|---:|---:|---:|---:|---:|
| Parser category only | 30 | 0 | 0 | 5 | 55 |
| Rules without the knowledge graph | 5 | 30 | 0 | 25 | 45 |
| Rules + knowledge graph + heuristics | 20 | 30 | 63 | 25 | 45 |
| Decision tree only | 30 | 15 | 61 | 30 | 55 |
| Rules + knowledge graph + heuristics, then tree | 30 | 30 | 70 | 30 | 60 |

What goes wrong, most frequent first:

- **Parser category only**: version incompatibility read as a missing dependency (39) or a code
  defect (31); missing configuration read as a code defect (25); a local module problem read as a
  missing dependency (20) or a code defect (10).
- **Rules without the knowledge graph**: no answer for 65 of the 70 version incompatibilities and
  the other 5 called a code defect; no answer for 25 missing dependencies.
- **Rules + knowledge graph + heuristics**: never wrong; no answer for 15 code defects, 10 missing
  dependencies, 7 version incompatibilities and 5 missing configurations.
- **Decision tree only**: 29 wrong, all in six scenarios it had not seen: a local module problem
  called a code defect (10) or a missing dependency (5), version incompatibility called a missing
  dependency (9), a code defect called a local module problem (5). The scenarios are
  `lm_src_layout`, `lm_circular`, `lm_relative`, `vi_stdlib_module`, `cd_missing_name` (5 each)
  and `vi_unknown_submodule` (4).

## 4 The 30 hard cases

The tree is fitted on the 220 ordinary cases; rules and knowledge are as shipped.

| Method | Correct of 30 | local_module (5) | version_incompatibility (25) |
|---|---:|---:|---:|
| Parser category only | 0 | 0 | 0 |
| Rules without the knowledge graph | 5 | 5 | 0 |
| Rules + knowledge graph | 5 | 5 | 0 |
| Rules + knowledge graph + heuristics | 30 | 5 | 25 |
| Decision tree only | 15 | 5 | 10 |
| Rules + heuristics without the knowledge graph, then tree | 5 | 5 | 0 |
| Rules + knowledge graph + heuristics, then tree | 30 | 5 | 25 |

All 25 version incompatibilities are decided by one heuristic (H10), which was written after these
cases had been seen. 30 of 30 is therefore a development result, and a heuristic answer is a
suggestion, not a confirmed diagnosis. The tree alone calls 15 of them a code defect. With five
fixed classes of which two occur, a perfect answer has Macro-F1 0.400.

## 5 What the product displays

The last row of the tables above is "rules, else tree" as the evaluation command combines them.
The product does more than that: it can decide that the evidence is not enough and ask for the
failure to be run again. `tools/b6_replay.py` therefore asks the product itself for its plan on
every saved session and reads the diagnosis of the session's open issue, as the B3 package did
for two earlier versions (`fixfirst/PROTOCOL.md` there; my replay is without that package's I/O
guard, and records instead that no exception was raised, that the saved observations were
unchanged and that no project folder of the sessions exists on the machine).

| Product version | Ordinary, correct of 220 | No diagnosis | Hard, correct of 30 | Source of the diagnoses, ordinary (rule / heuristic / tree / none) |
|---|---:|---:|---:|---|
| v0.7.0 (`c8151af`, B3 package) | 220 | 0 | 30 | 170 / 18 / 32 / 0 |
| candidate `ff92446` (B3 package) | 215 | 5 | 30 | 172 / 11 / 32 / 5 |
| 0.8.0rc5 (this replay) | 215 | 5 | 30 | 172 / 11 / 32 / 5 |

0.8.0rc5 gives the same diagnosis from the same source as `ff92446` in all 250 cases. The five
without a diagnosis are the five `vi_unittest_alias` cases: the saved records do not say which
object the removed method was called on, and the product's first step is "Re-run the failure
before choosing a repair" instead of a cause. They count as wrong here. In section 2 the tree
answers them, correctly. Both numbers are true; they measure different things.

Two limits of this table: the 32 diagnoses that come from the shipped tree are for cases from
the set that tree was trained on, so they are not held out; and on the hard cases 25 of 30 are
heuristic suggestions.

## 6 Three language models on the same cases

From the B3 package (`experiments/diagnosis_baseline/generated-results-20261004/`): each model
answered each case once, without tools, at temperature 0, from a redacted presentation of the
same saved evidence; an unusable answer counts as wrong. The numbers were recomputed from the
sealed answers.

| System | Ordinary, correct of 220 | Macro-F1 (five classes) | Hard, correct of 30 |
|---|---:|---:|---:|
| FixFirst 0.8.0rc5, as displayed (section 5) | 215 | 0.993 | 30 |
| Qwen3.8-27B-MLX-4bit | 216 | 0.987 | 18 |
| gemma-4-26B-A4B-it-qat-4bit | 213 | 0.973 | 15 |
| Qwen3.6-35B-A3B-6bit | 203 | 0.926 | 15 |

Per class on the ordinary cases (missing_dependency / local_module / version_incompatibility /
config_missing / code_defect): Qwen3.8 30 / 29 / 67 / 30 / 60; Gemma 30 / 30 / 66 / 27 / 60;
Qwen3.6 30 / 28 / 62 / 27 / 56. The models' most frequent mistake is calling a version
incompatibility a code defect (Qwen3.8 3, Gemma 4, Qwen3.6 5 cases), and Gemma and Qwen3.6 call
three missing configurations a code defect. On the hard cases every mistake of every model is of
that kind (12, 15 and 15 cases): a behaviour change of an upgraded library looks like a defect in
the project.
The tree alone makes the same 15 mistakes (section 4).

This comparison must not be read as FixFirst beating language models. The cases are FixFirst's
own development scenarios; the models were not given the labels, FixFirst's conclusions or its
knowledge base and had never been fitted to these cases. On the ordinary cases the best model and
the product are level. The difference on the hard cases is the difference a heuristic written for
those cases makes.

## 7 Real projects

Kept apart from the generated cases, as the task asks.

### 7.1 Twelve held-out projects: v0.7.0 and the three models

Eleven projects with a fault and one healthy project, chosen and labelled by teammates before
v0.7.0 was run on them (`examples/heldout-2026-10/`). The models answered once from the evidence
of the first checks; the first steps were scored blind to the model by two scorers
(`experiments/diagnosis_baseline/real-results-20261003/`).

| System | Root cause right (11 faults) | Macro-F1 | First step: correct / partial / generic / wrong | No answer |
|---|---:|---:|---|---:|
| Qwen3.6 | 9 | 0.827 | 6 / 3 / 0 / 2 | 1 |
| Qwen3.8 | 8 | 0.798 | 5 / 3 / 0 / 2 | 2 |
| Gemma | 3 | 0.317 | 0 / 2 / 1 / 7 | 2 |
| FixFirst v0.7.0 | 8 | 0.813 | 4 / 1 / 6 / 1 | 0 |

Root cause right per class (missing_dependency 2 / version_incompatibility 4 / local_module 2 /
config_missing 2 / code_defect 1): Qwen3.6 2 / 4 / 1 / 1 / 1; Qwen3.8 2 / 3 / 1 / 1 / 1; Gemma
1 / 0 / 0 / 1 / 1; FixFirst 2 / 1 / 2 / 2 / 1.

To be read with it:

- This is v0.7.0, not 0.8.0rc5. The projects were used for development afterwards, so a later
  version on them would be a development result; none is reported here.
- FixFirst's weak class is version incompatibility (1 of 4), and six of its twelve first steps
  were rated generic: it named a category without a usable next action.
- FixFirst's 8 counts three causes it showed as "possible". Counting only unhedged causes gives 5.
- The Macro-F1 is over the 11 fault projects. Counting the healthy project too, on which Qwen3.6
  and Gemma raised a false alarm, gives Qwen3.6 0.800 and Gemma 0.283; FixFirst and Qwen3.8 are
  unchanged.
- The scores were drafted with AI assistance and reviewed row by row; the two scorers agreed on 29
  of 31 answered rows (kappa 0.904).
- Twelve projects and one answer each describe this batch and no more.

### 7.2 Real code defects: does FixFirst call a code defect a code defect?

All BugsInPy bugs are defects in project code, so they test one class only. On the 75 held-out
bugs of `examples/bugsinpy-verification/` (three sets, each on the version frozen before it), with
the bug's tests named, the first step named:

| First step's cause | Bugs |
|---|---:|
| Defect in project code or tests, stated | 44 |
| Defect in project code or tests, marked unconfirmed | 18 |
| Another cause, marked unconfirmed (missing configuration 2, version incompatibility 2) | 4 |
| No cause: FixFirst did not get to the failing test (first set: thefuck 8, httpie 1) | 9 |

No wrong cause was stated without the mark, and no step with an environment command was given.
In default use, without the tests named, the first step is often about another failure of the
suite (a package some other test needs) and says nothing about the bug; see that folder's README.

## 8 Summary

1. On its 220 development cases, rules, knowledge and heuristics answer 183 and are never wrong;
   the tree answers the rest, 220 of 220 in both ways of holding out. Without the knowledge graph
   it is 205; without the tree 183 with 37 unanswered.
2. The tree alone depends on having seen the scenario: 220 with a new template, 191 with a new
   scenario.
3. What the product displays is 215 of 220: for five cases it asks for the failure to be run again
   instead of naming a cause.
4. Three language models reach 203 to 216 of 220 on the same evidence. On the hard cases they and
   the tree alone make the same mistake, and FixFirst's 30 of 30 comes from a heuristic written
   for those cases.
5. On twelve real projects v0.7.0 named the cause as often as the better models (8 of 11) and
   gave a correct first step less often (4 of 12 against 5 and 6). Nothing here shows FixFirst
   ahead of language models on real projects.

## 9 Files

| File | Content |
|---|---|
| `per-case.csv` | One row per case (250): the label, every method under both ways of holding out, the three product versions, the three models. Every count of sections 2 to 6 can be recounted from it |
| `diagnosis/`, `hard/` | The outputs of `fixfirst evaluate`, unedited |
| `product-replay.json` | Output of `tools/b6_replay.py` for 0.8.0rc5 |
| `tools/b6_replay.py` | The replay script |
