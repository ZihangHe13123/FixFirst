# Next-step ordering and ablations (task B17)

12 October 2026. Product source: `main` at `0ee7a43`, which is the frozen 0.8.0rc5 (`646c12a`) plus
a repair of one dataset generator that this evaluation does not touch. No language model was used.
The projects were run for real.

**The result in one paragraph.** On the five multi-fault cases FixFirst picks a right problem
first every time, makes no wrong attempt and reaches the goal. So do both naive orderings. This
was known before FixFirst was run on these cases: the check of 29 September showed that the
suite cannot separate the methods, and the cases were not changed to create a difference.
Switching the grouping changes nothing either. What the suite does show is the quality of the
first step itself: of the eleven first steps FixFirst gave on the way, seven are an allowed
repair, four name no concrete change, and none is wrong.

## 1 Material and rules

The five cases M1 to M5 of `docs/B4_SCENARIOS.md` (section 2): generated projects with two or
three injected faults, some hidden behind others, built before the freeze for this evaluation.
They are development material, not held out and not a sample of natural failures. The grading was
fixed on 29 September, before any FixFirst result on them:

- **Which problem is picked.** The method picks one open issue. If an observable required fault is
  behind it, that fault's reference repair is applied; otherwise nothing is applied and the pick
  counts as a wrong attempt. Repeat until every required fault is repaired, at most ten steps.
  The reference repair stands in for whatever the method proposed, so this measures the choice
  of problem only.
- **Whether the proposed action is right.** Judged apart, from the action as written, against the
  allowed repairs listed for each fault; never by putting the reference repair in its place.

Methods:

- **FixFirst**: the issue of the first step of its plan.
- **Message order**: the first failure in pytest's output.
- **Category order**: the parser's category in a fixed order (missing dependency, local module,
  version, configuration, code defect, then style).
- **FixFirst with exact grouping** and **FixFirst without grouping**, through the session's own
  settings.

## 2 Which problem is picked

| Method | First issue right | Wrong-issue attempts | Goal reached | Repairs in an acceptable order |
|---|---:|---:|---:|---:|
| FixFirst | 5 of 5 | 0 | 5 of 5 | 5 of 5 |
| Message order | 5 of 5 | 0 | 5 of 5 | 5 of 5 |
| Category order | 5 of 5 | 0 | 5 of 5 | 5 of 5 |
| FixFirst, exact grouping | 5 of 5 | 0 | 5 of 5 | 5 of 5 |
| FixFirst, no grouping | 5 of 5 | 0 | 5 of 5 | 5 of 5 |

Every method repairs the faults in the same order in every case (11 steps in all).

**Why nothing separates the methods.** In these cases a collection error hides everything behind
it, the faults that are visible together (M2, M4) may be repaired in either order, and the only
decoy is the optional lint finding in M3, which no method picks. An ordering can only do better
than the order of the messages where two problems are visible at once and one of them must come
first. This suite has no such state.

## 3 The ablations

| Ablation | How | Result |
|---|---|---|
| Without ordering by goal | The two naive orderings above | The same as FixFirst on all five cases |
| Exact matching in place of TF-IDF grouping | Session setting `grouping="exact"` | At each of the eleven states the same open issues, the same number of steps shown, the same issue picked and the same first step |
| No grouping | A threshold no pair of messages reaches | The same again |
| Without the display of evidence | Needs an arm of a user study with real participants | **Not done.** No such study exists; this evaluation makes no statement about it |

The grouping result agrees with `examples/grouping-evaluation/REPORT.md`: in these projects, as in
all saved data, the events that share a block have identical text or are single.

## 4 Is the first step itself right

FixFirst's first step at each of the eleven states it visited, read as written and judged against
the allowed repairs. One rater, the author of this report; the texts are in `advice.json`.

| Fault behind the issue | States | Allowed repair | What the first step says | Judgement |
|---|---:|---|---|---|
| `renamed_helper` | 2 | move the helper file back, or import the new name | "Update imports of helper: the project has helpers.py … update the imports or restore the file" | correct |
| `numpy_alias` | 2 | use the builtin `float` | "Replace numpy.float: removed in numpy 1.24 … use the builtin type" | correct |
| `stdlib_removed` | 1 | remove the import (use importlib) | "Replace imp: removed in Python 3.12 … use importlib" | correct |
| `env_missing` | 2 | provide a default for the variable | "Provide the configuration value … set it in the shell or the test configuration" | correct, on one reading |
| `private_moved` | 2 | import from `sklearn.utils._user_interface` | An inspecting step without instructions: "Find a compatible scikit-learn release that provides sklearn.utils._print_elapsed_time" | generic |
| `total_off_by_one` | 2 | restore `sum(self.values)` | "Compare the failed assertion's expected and actual values" | generic |

| | Correct | Generic | Wrong |
|---|---:|---:|---:|
| All eleven first steps | 7 | 4 | 0 |
| The first step of each case (5) | 4 | 1 | 0 |
| Strict reading of `env_missing`: all eleven | 5 | 4 | 2 |
| Strict reading: the first step of each case | 3 | 1 | 1 |

- The cause shown for the picked issue is the right category in all eleven states (nine by a rule,
  the two `private_moved` by a heuristic).
- **`env_missing`**: FixFirst says to provide the value; the table allows "a default for the
  variable". I read providing the value as within that. Read strictly, only a default in the code
  counts and the two steps are another action; the last two rows give that reading.
- **`private_moved`**: FixFirst names the right cause but points to the library's version, not to
  the new place of the name, and gives no instructions. Its knowledge base has no entry for where
  this private name went.
- **`total_off_by_one`**: for a defect in the project's own logic FixFirst does not propose a
  change. That is by design and is what the twelve real projects also showed for v0.7.0, where six
  of twelve first steps were rated generic.

## 5 What was not done

- **The playground project and the two-layer hard cases**, which the task card also names, were
  not scored. Only M1 to M5 have the fault definitions, reference repairs and "hidden by" relations
  the replay needs. The two-layer hard cases have one visible fault at a time, like M1, so there
  is nothing to order in them.
- **The arm without the display of evidence**: see section 3.
- No model answers were judged here; the two blind raters the grading asks for apply to those.

## 6 Limits

- Five generated cases built by the team; eleven first steps; one rater for the advice.
- The suite cannot show an ordering advantage. Whether FixFirst's ordering helps where several
  problems are visible at once and only one must come first has not been measured anywhere.
- The reference repair replaces the method's action in section 2, so a method that picks the right
  issue with a useless action still reaches the goal there. Section 4 is the measure of the action.

## 7 Files

| File | Content |
|---|---|
| `ordering.json` | Every replay: per state the open issues, the issue picked, the fault behind it and, for FixFirst, the step as written |
| `advice.json` | The eleven first steps with the allowed repair, the judgement on both readings and its reason |
| `experiments/ordering/ordering.py` | The replay script; `experiments/ordering/README.md` says how to run it |
