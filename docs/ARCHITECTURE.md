# FixFirst architecture

FixFirst turns the output of real checks into a diagnosed, ranked and verifiable plan. This
page describes the code as of v0.4. `models.py` holds the shared Pydantic records.

```
 project + interpreter + goal
            │
            ▼
 runner.py / probe.py / project.py   run allowlisted checks (environment snapshot, project
            │                        declarations + source index, pip check, pytest collect/run,
            ▼                        Ruff) with timeouts, output limits and redaction
 parsers.py → grouping.py            events → issues (structural blocking + TF-IDF/SBERT,
            │                        complete-link, never single-link chaining)
            ▼
 evidence.py                         observed facts + feature vectors per failing test
            │                        (exception, where it was raised, module status, signals)
            ├──────────── domain.py  knowledge facts for the names in the evidence
            │                        (knowledge/domain.toml, every entry cites a source)
            ├──── classification.py  decision-tree suggestion (hypothesis) per issue
            ▼
 engine.py + knowledge/rules.toml    forward chaining: derive → diagnose → heuristic → fallback → plan
            │
            ▼
 reasoning.py                        actions (rule remedies + verification re-runs),
            │                        ordering, goal status
            ▼
 service.py                          scope-aware verification: an issue closes only when a
            │                        completed check of the same scope and interpreter passes
            ▼
 knowledge_graph.py, report.py,      evidence graph + queries, HTML/JSON reports,
 web.py, cli.py, interactive.py      local web interface, CLI, terminal menu
```

## One troubleshooting round

1. **Collect.** `runner.collect` runs one allowlisted check with the selected interpreter.
   Arguments go straight to the subprocess (no shell); each check has a 10-minute timeout and a
   1 MB output cap; process groups are killed on timeout. The environment snapshot and `pip
   check` run in a temporary directory so that a project file such as `random.py` cannot
   shadow the standard library during the check. Output is redacted (credentials, URL
   passwords, `os.environ` dumps, secret-like dictionary values).
2. **Parse and group.** Parsers turn each run into events; unknown or incomplete output is
   kept and never read as success. Grouping only compares events with the same tool, stage,
   kind, component and version strings, then uses complete-link similarity so that A~B and
   B~C does not merge A with C.
3. **Build evidence.** `evidence.issue_evidence` reads the pytest probe records cited by an
   issue: the real exception type (even when pytest wraps it in `CollectError`), the
   innermost frame, the source lines that actually ran, module/API/argument names, config
   keys and missing files. `evidence.observations` adds what the environment snapshot and the
   project index say about each module (installed? standard library? local file? declared?
   similar local file?). Nothing is taken from the parser's category or from labels.
4. **Add knowledge.** `domain.facts_for` looks up only the names that appear in the
   evidence: removed modules, APIs, attributes and keyword arguments with the version that
   removed them, their replacements, and import-name → distribution mappings. Installed
   versions come from the snapshot, so a rule can compare "removed in 1.24" with "installed
   2.5.3".
5. **Suggest.** The bundled Gini decision tree (`knowledge/diagnosis_tree.json`, trained on the
   diagnosis dataset) predicts a cause from the feature vector. A suggestion with confidence
   ≥ 0.6 becomes a *hypothesis* fact.
6. **Reason.** `engine.run` applies the rule base phase by phase to a fixpoint:
   - `derive`: goal relevance (`affects`, `blocks`) and helper facts;
   - `diagnose`: root causes from evidence + knowledge (rules D01–D43), including pip check
     conflicts linked to missing names (D06);
   - `heuristic`: likely causes from general experience when no rule is certain, worded as
     unconfirmed (H01, H02);
   - `fallback`: the tree's suggestion, only when neither matched (F01);
   - `plan`: actions (P01–P51), merged by action id across issues.
   Negation is stratified: a rule may only negate predicates concluded in an earlier phase,
   which `engine.validate` checks when the rule base loads.
7. **Order.** `reasoning.order_actions` sorts by: blocked preconditions, goal impact (affects +
   blocks), strength of support (knowledge-backed 3, evidence 2, generic 1, hypothesis or
   awaiting verification 0), kind (gather evidence → fix → verify) and cost.
8. **Verify.** After the user changes the project, the next check updates only issues it
   covers. A complete pip check or Ruff run closes the findings it no longer reports; a
   complete test run closes earlier collection errors. Imported logs, partial runs,
   skipped/xfail tests, deleted tests, relaxed declarations or a different interpreter never
   close an issue.

## Rule base

`knowledge/rules.toml` is data, not code. A rule is:

```toml
[[rule]]
id = "D02"
phase = "diagnose"
description = "The code uses a module attribute or imported name that the installed version no longer provides."
when = [
  ["?i", "api", "?x"],
  ["?x", "removed_from", "?d"], ["?x", "removed_in_version", "?v"],
  ["?d", "installed_version", "?iv"], ["test", "version_gte", "?iv", "?v"],
]
then = [["?i", "diagnosis", "version_incompatibility"], ["?i", "remedy", "replace_removed"], ["?i", "because", "?x"]]
```

Every derived fact records the rule, its input facts and the union of their evidence
references, so the report and the graph can trace any advice back to a check record or a
cited document.

## Knowledge base

`knowledge/domain.toml` lists five causes, candidate causes per exception type, import names
that differ from their PyPI distribution, and 117 removed names from Python 3.10–3.13, NumPy,
SciPy, scikit-learn, Jinja2, MarkupSafe, packaging, pydantic, Werkzeug and pandas. Each entry
cites its release notes. `fixfirst knowledge --output kg.json` exports it with the rules.

## Evidence graph

`knowledge_graph.build_graph` creates 10 entity types (Goal, Action, Issue, Cause, Fact, Rule,
Event, Evidence, Run, Source) and 15 typed relations. `query_graph` recognises a few intents in
English or Chinese (why an action, root cause, what blocks the goal, what is unverified, which
package provides a module, whether a name was removed) and answers by breadth-first traversal
or a knowledge lookup. Unsupported questions are refused rather than guessed.

## Data and experiments

- `diagnosis_cases.py`: 5 project templates × 43 single-fault scenarios, executed for real
  (215 cases). Labels come from the scenario definition. Some scenarios are deliberately not
  covered by the knowledge base.
- `evaluation.py`: leave-one-template-out and leave-one-scenario-out cross-validation of the
  parser baseline, rules with/without the knowledge base, the tree, and the hybrids, with
  bootstrap confidence intervals.
- `cases.py` / `execution_cases.py`: the v0.1/v0.2 controlled datasets, now used for message
  grouping only.
- `historical_cases.py`: offline replay of four upstream regressions with official wheels.

## Interfaces

- `fixfirst serve`: local web interface on 127.0.0.1 with a per-launch token for every change
  and a Host-header check against DNS rebinding.
- `fixfirst ...`: the CLI; `fixfirst interactive`: a terminal menu over the same commands.
- Reports are static HTML (Content-Security-Policy blocks network access) plus JSON.
