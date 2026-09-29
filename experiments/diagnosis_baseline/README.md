# One-shot diagnosis baseline (task B3)

A local model gets the same evidence as FixFirst and names the root cause and the first step,
with no tools and no chance to run anything. This measures what the model *knows*, independently
of how well it can act as an agent (that is B7's question).

## What the model sees

The records FixFirst's diagnosis reads, read the way FixFirst reads them (`one_shot.py`,
`evidence()`): the latest run of each check, and the environment and project snapshots only when
they belong to the selected interpreter.

- **pytest's output** (collection and test run). Output longer than 20,000 characters keeps its
  first and last 10,000.
- **The exception records of FixFirst's pytest plugin** for the same runs: the exception's type,
  message (up to 1,000 characters) and module, the file and line that raised it, and the warnings
  a failing test's recorder held. At most 50 records per run.
- **pip check and Ruff output** when the session has them (up to 6,000 characters each; Ruff's
  JSON as one line per finding).
- **The environment snapshot**: Python version, installed distributions (`name==version`), which
  distribution provides each import name, the standard library's module names, library paths and
  platform markers.
- **The project index**: the project root, declaration files, declared dependencies with their
  install status, Python requirements, notes, top-level modules, Python files, the names the code
  defines (`defined_names`), what each imported name refers to (`imported_names`), the
  distributions the project builds (`own_names`), lint settings and lock-file versions
  (`tested_versions`).

Lists and mappings keep at most 500 entries. Every cut says how much was left out.

**Left out**, and why:

| Left out | Why |
|---|---|
| Record identifiers, file hashes | Bookkeeping |
| The installed distributions' own requirements | The diagnosis does not read them; they made a small project's prompt four times longer |
| pytest's per-test outcome and finish records | Used to verify fixes, not to diagnose |
| The plugin's failure records | The same tracebacks as pytest's output |
| Release searches ("Find it") | FixFirst's own follow-up checks; the model has no tools |
| FixFirst's issues, facts, diagnoses, actions and knowledge base | FixFirst's conclusions and knowledge, not evidence |
| The case name, scenario and label | The answer |

**Why this scope.** The first version gave the model only pytest's output, the package list, the
Python files and the declarations. FixFirst also reads the project's imports: in the committed
hard case `flat-shop--vb_click_mix_stderr`, heuristic H07 concludes a version incompatibility
because `CliRunner` is `click.testing.CliRunner`, and without the imports it concludes nothing. The
old prompt was the same with or without them (found in Codex's review, 29 September).
`tests/test_one_shot_baseline.py` now checks that case, and that every field of the two snapshots
reaches the model unless it is listed above.

**No label leakage.** Recorded sessions keep the case name (which contains the scenario), so the
prompt is built from the check records only, never from the session's name, the case row or the
scenario. Before a prompt is sent it is checked for the case name, the scenario and the label; the
listing's own field names do not count (`local_modules` is not the label `local_module`), their
values do. A prompt that contains any of them is not sent and is recorded. None of the 245
committed generated and hard cases does.

## Answers

The system prompt lists the five root causes with the knowledge base's own definitions and asks
for one JSON object: `{"root_cause": ..., "first_step": ...}`. An answer is read with a JSON
decoder (`parse()`): once any `<think>` block is removed it must be one JSON object, bare or in one
Markdown code fence. `root_cause` must be one of the five classes (case and outer spaces do not
matter) and `first_step` a non-empty string. Text around the object, two objects, or anything that
is not an object is not an answer.

Each row of `results.jsonl` records the prediction and first step, the problems found in the
answer, the raw answer, the evidence's SHA-256 and length, latency, token counts, and an error
kind:

- `not_sent`: the prompt would have given the answer away;
- `request_failed`: the request did not complete (connection, HTTP error, timeout);
- `bad_response`: the server answered, but not with a chat completion that holds text.

A failure is recorded for its case and the run goes on; `summary.json` is written at the end. For
the root cause, anything without a valid class counts as wrong. The summary keeps apart
`complete_answers` (valid class and first step), `root_cause_without_first_step` (the class counts
for accuracy, but the answer is not complete and its first step scores as no answer),
`invalid_answers`, `failed_requests`, `bad_responses` and `not_sent`. The median latency is taken
over the requests the model answered.

`config.json` keeps the dataset's SHA-256, the case list, the evidence limits and what is left out,
the answer format, the models, the decoding settings, the system prompt and its SHA-256, the
FixFirst commit, any uncommitted changes to `src/` or the script, and the seed.

## Running it

Start the local server with environment variables only (command-line flags would be written into
omlx's settings), then run the script from the repository root:

```bash
OMLX_HOST=127.0.0.1 OMLX_PORT=8123 OMLX_API_KEY=<any throwaway key> omlx serve
LLM_API_KEY=<the same key> .venv/bin/python experiments/diagnosis_baseline/one_shot.py \
    examples/diagnosis-dataset --models Qwen3.6-35B-A3B-6bit --per-label 2 --output workbench/b3-check
```

Decoding: temperature 0, top_p 1, at most 1,024 tokens, thinking disabled through
`chat_template_kwargs` (any `<think>` block would be removed before parsing), fixed seed.

`--rescore DIR` reads the saved answers in `DIR` again with the current parser and rewrites its
`summary.json`, without asking any model.

## Development trial 1, 29 September 2026 (`dev-trial-2026-09-29/`)

**A check of the pipeline, not a result.** 10 cases from the committed 215-case dataset, two per
root cause (seed 20260929), two fast local models, run from commit 3c0153d (branch
`b4-scenarios`; the script does not depend on the B4 changes). It used the first version of the
evidence, without the project's imports and names or the exception records.

| Model | Complete answers | Failed requests | Correct | Median seconds |
|---|---|---|---|---|
| Qwen3.6-35B-A3B-6bit | 10/10 | 0 | 10/10 | 1.33 |
| gemma-4-26B-A4B-it-qat-4bit | 10/10 | 0 | 10/10 | 1.46 |

The first summary took the upper of the two middle latencies (1.36 and 1.47 seconds); the medians
above were recomputed from the saved answers with `--rescore`, which read all 20 answers the same
way. The first request to each model took 42 and 14 seconds, most likely while the server loaded
the model; the median is not affected.

Checked on the way: no prompt contained the case name, scenario or label; every answer was plain
JSON (at most 64 tokens, no thinking block); a request to a model that does not exist was recorded
as an HTTP 404 error and counted as wrong. The omlx settings file was unchanged afterwards.

## Development trial 2, 29 September 2026 (`dev-trial-2026-09-29-b/`)

**Also a check of the pipeline, not a result.** The same 10 cases, models and settings, with the
evidence described above, run from commit bcd352e with no uncommitted changes.

| Model | Complete answers | Failed requests | Correct | Median seconds | Prompt tokens |
|---|---|---|---|---|---|
| Qwen3.6-35B-A3B-6bit | 10/10 | 0 | 10/10 | 4.23 | 3,513–4,881 |
| gemma-4-26B-A4B-it-qat-4bit | 10/10 | 0 | 10/10 | 2.87 | 3,618–5,166 |

Prompts are about three times longer than in trial 1 (1,060–2,629 tokens); the evidence is
8,908–16,084 characters. Every answer was one plain JSON object (at most 60 tokens, no thinking
block, no problems recorded). A separate run with a model name the server does not have (not
kept) recorded `request_failed` (HTTP 404) for that model and still answered and summarised the
next one. The omlx settings files were unchanged afterwards and the server was stopped.

Single-fault generated cases are easy: like the agent pilot, these trials say nothing about how
the models compare with FixFirst. The formal run needs the harder sets below.

## Formal run (after B4 is final)

Fixed before it starts and recorded in `config.json`: the data snapshots (the regenerated
diagnosis dataset with 44 scenarios and the 30 hard cases, then the new real projects once A2's
results are merged), this prompt and evidence, the models (Qwen3.8-27B, Qwen3.6-35B-A3B,
Gemma-4-26B-A4B), the decoding settings, the FixFirst commit (the frozen v0.7.0) and the seed. The
hard cases were used to develop rules H07 and H08, so FixFirst's results on them are development
results. On the real projects the models' first steps are scored by A and C without knowing which
model wrote them (A2, step 7). No paid remote model is used.
