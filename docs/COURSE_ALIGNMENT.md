# Course alignment

Checked against the NUS-ISS IRS practice-module briefing (v2.16 and v2.17) and the proposal
/ final presentation guidelines (v015 and v016). Where the two versions differ, FixFirst
follows the union of their requirements.

## Technique groups (at least three of four)

| Technique group | FixFirst implementation | Where | Evidence it works |
|---|---|---|---|
| **Decision automation** (business rules, knowledge-based reasoning) | Production-rule engine: pattern matching with variables, negation as failure stratified by phase, version tests, provenance on every derived fact. 99 rules in five phases (derive → diagnose → heuristic → fallback → plan) produce root causes, likely causes and next actions; actions carry preconditions and are ordered by goal impact, evidence strength and cost. | `engine.py`, `knowledge/rules.toml`, `reasoning.py` | Rules + knowledge graph answer 79% of the diagnosis cases with 100% precision (83% with the heuristic phase, still 100%); on real projects they led Flask 1.1.4 from no runnable test to 525 passing and explain the last failure (docs/REAL_PROJECTS.md); on 13 held-out real projects the first step was right for 2 at first, and for 12 after fixing the general causes that check exposed (docs/GENERALISATION.md; not a held-out number); the rule base is validated for stratified negation when loaded; tests cover chaining, cycles, joins and rejected negation. |
| **Knowledge discovery and data mining** | Gini decision tree over 44 evidence features (no parser category, no label-derived value) trained on 215 real-execution cases; TF-IDF character n-grams + cosine similarity with structural blocking and complete-link grouping for repeated messages; optional Sentence-BERT. | `evidence.py`, `classification.py`, `grouping.py`, `diagnosis_cases.py`, `evaluation.py` | Cross-validated against baselines and ablations (see `examples/diagnosis-evaluation/REPORT.md`): the tree lifts accuracy on faults the knowledge base does not cover from 69% (rules alone) to about 90%. |
| **Cognitive techniques and tools** (knowledge base components: knowledge graph; human-oriented interface) | Domain knowledge graph: 5 causes, exception → candidate causes, import name → distribution, 118 removed modules, APIs, arguments and usages with versions and replacements, 10 deprecated names, 44 pytest fixtures mapped to their plugins, which Ruff rules indicate likely bugs, unmaintained packages, 23 cited sources plus plugin PyPI pages, queried by the rules. Session evidence graph: 10 entity types and 15 typed relations linking goal, actions, issues, causes, facts, rules, runs and sources; breadth-first queries answer questions in English or Chinese. | `domain.py`, `knowledge/domain.toml`, `knowledge_graph.py`, `web.py` | Removing the knowledge graph drops accuracy on the faults it covers from 100% to 7% (rules) and from 100% to 64% (hybrid). Queries are tested for supported and refused questions. |
| Business resource optimization (informed search, evolutionary computing) | Partly: a budgeted search over earlier patches and older release series (exponential then binary search, with a fallback over skipped patches; at most 12 real install-and-import trials in a throwaway environment) seeks a release that provides a missing name and pins the verified version. It is not informed search (A*) or evolutionary computing, and action ordering is a heuristic sort. | `versions.py`, rules D09, P57–P59 | The recorded v0.5 round 3 found the right bound for Flask, Django and scikit-learn in 2, 6 and 5 trials (docs/GENERALISATION.md). Subsequent regression tests with simulated histories cover earlier patches, exact pins and inconclusive searches; the real-project trials have not been rerun after that correction. Possible extension: A* over action sequences. |

The rule-based diagnosis, the learned classifier and the knowledge graph each handle a part
of the problem the others cannot: rules are precise but only where knowledge exists; the tree
generalises to unlisted removals but makes more mistakes; the graph supplies both the facts
the rules need and the explanations users see.

## Mapping to the modular courses

The group report appendix asks to map functions to the knowledge of MR, RS and CGS. The team
should check the module names below against the course outlines before submitting.

| System function | Knowledge / technique | Module |
|---|---|---|
| Rule base with forward chaining, variables and stratified negation | Knowledge representation, rule-based reasoning, inference engines | MR |
| Provenance (every conclusion keeps its rule, inputs and evidence) | Explanation facilities of knowledge-based systems | MR |
| Decision tree (Gini) on evidence features, cross-validation, ablation | Supervised learning, model evaluation | MR / RS |
| Goal-directed action ordering with preconditions and blocking relations | Decision making under goals and constraints | RS |
| TF-IDF + cosine similarity, complete-link grouping | Text mining, similarity, clustering | CGS |
| Domain knowledge graph and session evidence graph with graph queries | Knowledge graphs, graph traversal | CGS |
| Question answering over the graph (English/Chinese intents) | Natural-language interface to a knowledge base | CGS |
| Local web interface with explanations and verification controls | Human-centred cognitive system design | CGS |

## Deliverables (final submission, due 25 Oct 2026)

| Deliverable | Status |
|---|---|
| Runnable intelligent reasoning system | Yes: `fixfirst serve`, CLI, terminal menu |
| User interface, results interpretation and visualisation | Yes: web interface, HTML reports, evidence-graph view |
| Experiments with quantitative evaluation | Diagnosis (215 cases, two cross-validation protocols, baselines, ablations); grouping (60 controlled cases); upstream regression replays |
| Installation and user guide | README; to be expanded into the report appendix |
| Business case / market research / literature review | In the proposal; needs updating for the final report |
| Two 5-minute videos (promotion incl. pricing; system design) | To do. AI-generated presentation speech is not allowed |
| Group report, proposal appendix, course mapping appendix | To do (this file is the draft of the mapping appendix) |
| Individual reflection and peer review | To do, one page per member |
| GitHub repository from the IRS-PM template, zip, member-github.txt | To do |
| User study (proposal: 6–8 participants) | To do |
