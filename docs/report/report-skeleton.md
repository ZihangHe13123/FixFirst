---
title: "FixFirst: Evidence-Based Root-Cause Diagnosis and Verified Repair for Python Test Failures"
subtitle: "NUS-ISS Intelligent Reasoning Systems Practice Module · Group 24 · Project Report"
author: "HE ZIHANG · WEI YI · CHI YONGJUN"
date: "Skeleton v0.1, 29 September 2026 (final version due 25 October 2026)"
---

<!-- Skeleton conventions: [PLACEHOLDER: ...] marks text still to write; [PENDING: task, source]
marks a number that comes from an experiment not yet run. Every number in the final report must
cite the repository file it comes from (see docs/report/SOURCES.md). The report uses English file
names only, so that a PDF export shows every reference whatever fonts the exporting machine has:
"technical guide §n" is section n of the team's Chinese study guide, whose path is in
docs/report/SOURCES.md. -->

# Executive Summary

[PLACEHOLDER: 150–300 words, written last. The problem (Python projects break when installed
today), what FixFirst does (finds the root cause from real evidence, proposes the first step,
verifies every fix), the three technique groups, the headline results (held-out real projects,
baselines, user study) and the main limitation.]

# Business Case, Market Research and Literature Review

## The problem

[PLACEHOLDER: why failing Python environments matter, with sources:]

- PyDFix rebuilt 2,702 historical builds; 1,921 (71.1%) no longer reproduced because of dependency
  errors (Mukherjee et al., ISSTA 2021; docs/DATA_SOURCES.md).
- In the pilot survey, 12 of 13 open-source projects installed the way their own files describe had
  failing tests (docs/GENERALISATION.md).
- Python releases a new version every year (PEP 602) and removes deprecated modules and APIs.

## Target users and value

[PLACEHOLDER: developers taking over older projects, students and teaching assistants, researchers
reproducing code, maintainers onboarding contributors, organisations with legacy Python. Value:
faster root cause, fewer destructive fixes (deleting tests, blind upgrades), local operation,
traceable advice, verified repair.]

## Existing tools

| Tool or approach | What it does | What it does not do | Difference from FixFirst |
|---|---|---|---|
| pip check / pip's resolver | [PLACEHOLDER] | | |
| pipdeptree | | | |
| Dependabot / Renovate | | | |
| tox / nox | | | |
| IDE inspections | | | |
| General AI assistants (ChatGPT, Copilot, Claude Code) | | | Complementary: FixFirst can serve them through MCP |

## Literature review

[PLACEHOLDER: start from the proposal's references. Candidates to read and verify before citing:
PyDFix (ISSTA 2021), BugsInPy (ESEC/FSE 2020), Watchman, smartPip, PyEGo, DockerizeMe, SWE-bench.
Cite only papers that were opened and checked. End with how FixFirst differs: local diagnosis,
traceable rules and knowledge, verification by real checks, no automatic code edits.]

## Pricing

| Edition | Contents | Price |
|---|---|---|
| Community | Local command line and web interface, open source | Free |
| Pro | [PLACEHOLDER: monthly knowledge-base updates, faster release search, report export] | [PLACEHOLDER] |
| Team | [PLACEHOLDER: CI integration, shared rules and knowledge] | [PLACEHOLDER, per seat] |
| Education | [PLACEHOLDER] | Free or discounted |

[PLACEHOLDER: reasoning behind the prices; competitor prices with the date they were checked. The
promotion video (task B16) uses the same figures.]

# System Design and Model

## Overview

[PLACEHOLDER: the loop check → group → evidence → knowledge → rules → ordering → verification, with
the architecture figure (source: README "How it works"; docs/ARCHITECTURE.md).]

| Course technique group | FixFirst component | Where to read more |
|---|---|---|
| Decision automation (rules, knowledge-based reasoning) | Forward-chaining production system, [PENDING: rule count at the freeze] rules in five phases | docs/ARCHITECTURE.md, "Rule base" |
| Knowledge representation / cognitive techniques | Domain knowledge graph (removed APIs, sources) and per-session evidence graph | docs/ARCHITECTURE.md, "Knowledge base" and "Evidence graph" |
| Knowledge discovery and data mining | Gini decision tree over 44 evidence features; TF-IDF message grouping | docs/ARCHITECTURE.md, "One troubleshooting round", steps 2 and 5 |
| Resource optimisation (partial) | Bounded release search ("Find it") | docs/ARCHITECTURE.md, "Finding a release that works" |

## Evidence and features

[PLACEHOLDER: pytest probe, what counts as evidence, the 44 features and why labels and parser
categories are excluded.]

## Knowledge graph

[PLACEHOLDER: contents with counts (docs/ARCHITECTURE.md, "Knowledge base"; technical guide §5.1),
how it is queried, sources.]

## Rule engine

[PLACEHOLDER: facts, matching, stratified negation, phases, provenance; one worked example
(collections.Mapping, rule D02).]

## Decision tree

[PLACEHOLDER: training data, hyper-parameters fixed in advance, fallback role, confidence
threshold.]

## Ordering and verification

[PLACEHOLDER: how steps are ordered for a goal; when an issue counts as fixed.]

## Interfaces

[PLACEHOLDER: web interface (screenshots), command line, MCP tools for coding agents.]

# System Development and Implementation

[PLACEHOLDER: code structure, safety measures (timeouts, redaction, no shell), Windows support,
testing (number of automated tests at the final commit), development process and the AI usage
statement's summary.]

# Experiments

## Data

| Source | Kind | Size | Used for | Role |
|---|---|---|---|---|
| Official documentation and release notes | Knowledge | [PENDING: counts at the freeze] | Knowledge graph | Knowledge |
| Generated fault projects | Executed, labelled | [PENDING: 44 scenarios × 5 templates, regenerated at the freeze (B5)] | Diagnosis evaluation, training the tree | Training and development |
| Hard cases | Executed, labelled | 30 | Behaviour changes, two-layer faults; rules H07 and H08 were written after seeing them | Development: never used to train the tree, and not held-out evidence even when re-run after the freeze |
| Multi-fault cases | Executed, labelled | 5 | Next-step ordering (B17) | Evaluation of ordering; built by the team before the freeze, so not held out |
| Pilot real projects | Real | 13 | Development (round 1 was held out) | Development |
| New real projects | Real, labels before the run | [PENDING: A1, C1] | Held-out test | Test |
| BugsInPy | Real defects | [PENDING: B12 phase 2; 27 reproduced in phase 1] | Verification | Test |
| Upstream regressions | Real defects | 4 in packaging and click | Verification | Test |
| PyDFix | Public records | 22 cases | Text-only check (optional, A3) | Test |

## Labelling protocol

[PLACEHOLDER: independence of the rule author, sampling, labels before the run (commit hashes and
dates), double labelling with agreement and Cohen's kappa [PENDING: C1], scoring rubric and the
scorers' agreement [PENDING: A2].]

## Root-cause diagnosis (generated data)

| Method | Leave one scenario out: accuracy | Macro-F1 | Leave one template out: accuracy |
|---|---|---|---|
| Parser category only (baseline) | [PENDING: B6 after the freeze] | | |
| Rules without the knowledge graph | | | |
| Rules + knowledge graph | | | |
| Rules + knowledge graph + heuristics | | | |
| Decision tree only | | | |
| FixFirst (hybrid) | | | |
| Local LLM, one shot (per model) | [PENDING: B3 formal run] | | |

[PLACEHOLDER: ablations (without the knowledge graph, without the tree); hard cases reported
separately as development results (H07 and H08 were written after seeing them); which other
results are development results. Only the new real projects are held out.]

## Next-step ordering

[PENDING: B17. First step reasonable and invalid attempts before the goal, against message order
and fixed category order, on the multi-fault cases (docs/B4_SCENARIOS.md); functional ablations.]

## Message grouping

[PENDING: B9. Precision, recall and F1 against identical-text grouping on value, path and line
variants; target precision at least 0.90.]

## Verification on real defects

[PENDING: B12 phase 2 on v0.7.0. Whether issues stay open until the fix and close only after a
same-scope passing check; whether environment advice is given for code defects.]

## Held-out real projects

[PENDING: A2. Correct, partial, generic and wrong first steps overall and by root cause; error
analysis with screenshots; comparison with the pilot's held-out round 1 (2 of 13).]

## Baselines with local language models

[PENDING: B3 (one-shot diagnosis) and B7 (agent repair with and without FixFirst over MCP):
models, runs, fix rate, first passing turn, turns, time, tokens, edits to tests.]

## User study

[PENDING: C2 data, B13 analysis. Completion rate; median time of completed tasks against the 20%
target; the median with unfinished tasks counted as the time limit, named separately; false
completion claims; cause explanations; SUS; threats to validity.]

# Findings and Discussion

## Findings

[PLACEHOLDER]

## Limitations

[PLACEHOLDER: start from technical guide §11 and the problems found after the freeze.]

## Deviations from the proposal

| The proposal said | What was done | Why |
|---|---|---|
| PyDFix as the main data source | Generated projects run for real, plus real projects; PyDFix as a small text-only check | PyDFix keeps only error lines, mostly outside FixFirst's scope (docs/DATA_SOURCES.md) |
| BugsInPy defects in their original Python 3.6–3.8 | Reproduced on Python 3.9, only bugs that reproduce there | FixFirst supports target interpreters from 3.9 |
| One task per condition in the user study | Two tasks per condition | Less dependence on any single task; falls back if the pilot shows it is too long |
| A baseline was not in the proposal | One-shot LLM diagnosis and agent repair with and without FixFirst | Examiner's feedback at the proposal presentation |
| Ablations removing grouping, goal-based ordering and evidence display | [PENDING: B17 — which ablations were run] | |
| [PLACEHOLDER: further deviations] | | |

## Future work

[PLACEHOLDER]

# References

[PLACEHOLDER: in one consistent style; every entry checked.]

# Appendix A: Project Proposal

[PLACEHOLDER: the submitted proposal, unchanged.]

# Appendix B: Mapped System Functionalities against MR, RS and CGS

[PLACEHOLDER: from docs/COURSE_ALIGNMENT.md.]

# Appendix C: Installation and User Guide

[PLACEHOLDER: from docs/USER_GUIDE.md (task B14).]

# Appendix D: Individual Reports

One to two pages per member, written by each member personally (not by an AI tool): (1) personal
contribution to the project, (2) what was learnt that is most useful, (3) how the knowledge and
skills can be applied in other situations or at work.

## HE ZIHANG

[PLACEHOLDER: written by HE ZIHANG]

## WEI YI

[PLACEHOLDER: written by WEI YI]

## CHI YONGJUN

[PLACEHOLDER: written by CHI YONGJUN]

# Appendix E: AI Usage Statement

[PLACEHOLDER: which parts AI coding assistants helped with (code, documentation, report drafts);
which parts were done only by people (labels, label review, scoring, user-study sessions, video
narration, individual reflections); how the team reviewed and understood AI-written material.]
