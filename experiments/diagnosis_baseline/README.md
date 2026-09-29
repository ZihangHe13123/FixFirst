# One-shot diagnosis baseline (task B3)

A local model gets the same evidence as FixFirst and names the root cause and the first step,
with no tools and no chance to run anything. This measures what the model *knows*, independently
of how well it can act as an agent (that is B7's question).

## What the model sees

Only what FixFirst's checks recorded for the case (`one_shot.py`, `evidence()`):

- the pytest output (`pytest_run`, clipped to 12,000 characters, middle left out when longer);
- a summary of the environment snapshot: the Python version and every installed package with its
  version;
- the project's Python files and its declared dependencies with their sources.

The system prompt lists the five root causes with the knowledge base's own definitions and asks
for one JSON object: `{"root_cause": ..., "first_step": ...}`.

**No label leakage.** Recorded sessions keep the case name (which contains the scenario), so the
prompt is built from the check outputs only, never from the session's name, the case row or the
scenario. Before a prompt is sent it is checked for the case name, the scenario and the label;
a prompt that contains any of them is not sent and is recorded as an error.

**Everything is recorded** in `results.jsonl`: the prediction and first step, the raw answer, the
evidence's SHA-256, latency, token counts, and failures (a failed request or an answer that is
not valid JSON counts as wrong). `config.json` keeps the dataset's SHA-256, the case list, the
models, the decoding settings, the system prompt and its SHA-256, the FixFirst commit and the
seed.

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

## Development trial, 29 September 2026 (`dev-trial-2026-09-29/`)

**A check of the pipeline, not a result.** 10 cases from the committed 215-case dataset, two per
root cause (seed 20260929), two fast local models. It was run from commit 3c0153d (branch
`b4-scenarios`); the script does not depend on the B4 changes.

| Model | Answered | Failed requests | Correct | Median seconds |
|---|---|---|---|---|
| Qwen3.6-35B-A3B-6bit | 10/10 | 0 | 10/10 | 1.4 |
| gemma-4-26B-A4B-it-qat-4bit | 10/10 | 0 | 10/10 | 1.5 |

Checked on the way: no prompt contained the case name, scenario or label; every answer was plain
JSON (at most 64 tokens, no thinking block); a request to a model that does not exist was recorded
as an HTTP 404 error and counted as wrong. The omlx settings file was unchanged afterwards.

Single-fault generated cases are easy: like the agent pilot, this trial says nothing about how the
models compare with FixFirst. The formal run needs the harder sets below.

## Formal run (after B4 is final)

Fixed before it starts and recorded in `config.json`: the data snapshots (the regenerated
diagnosis dataset with 44 scenarios and the 30 hard cases, then the new real projects once A2's
results are merged), this prompt, the models (Qwen3.8-27B, Qwen3.6-35B-A3B, Gemma-4-26B-A4B),
the decoding settings, the FixFirst commit (the frozen v0.7.0) and the seed. On the real projects
the models' first steps are scored by A and C without knowing which model wrote them (A2, step 7).
No paid remote model is used.
