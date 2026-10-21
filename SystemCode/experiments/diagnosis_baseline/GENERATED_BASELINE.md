# B3 generated and hard batches

This is the five-class companion to the label-free real-project B3 pipeline. It uses
raw recorded evidence, including package requirements and pytest failure/outcome
records. Its protocol is `b3-generated-answers-v1`; it is not the old development-trial
prompt or the real-project six-class protocol. The existing real-project helpers are
imported unchanged from `5cff6702351272829e2424c54f0d1232963d021f`.

## Prepare

Use a clean v0.7.0 source checkout (`c8151af7bd6c19d71605dd3add38ea2dcda98ec2`) and
one pinned acquisition environment to generate the complete 44 × 5 diagnosis cases
and 6 × 5 hard cases. Generate outside any repository with ancestor pytest configuration.
Record all rejected cases; verify healthy templates and observed fault shapes before
registration. Preserve existing historical datasets. Do not mix old and new rows or
choose cases based on model answers.

```sh
PYTHONPATH=/path/to/frozen/src python experiments/diagnosis_baseline/generated_baseline.py prepare \
  --diagnosis /path/to/diagnosis --hard /path/to/hard \
  --output /path/to/inputs --labels /path/to/separate-labels.json
```

Preparation restores the generator's explicitly shared `environment.json` snapshot;
this is storage reconstruction, not a new observation. Inputs bind source case and
shared-environment hashes, helper/product code identity, evidence hashes and the separate
labels digest. Labels must be outside the sender input directory. Case/scenario names,
labels and FixFirst conclusions are excluded from the model messages. Input sizes and
all omissions must be audited before running.

## Register and run

Before any request, fix the exact qualified cases (target 220 + 30), input bytes, helper
commit, frozen product commit, model weight/tokenizer/template identity, prompt, environment,
model order and request settings. Tokenize final prompts offline for every actual model.
The intended three-model batch has 750 requests if all 250 target cases qualify.

```sh
PYTHONPATH=/path/to/frozen/src python experiments/diagnosis_baseline/generated_baseline.py run \
  /path/to/inputs /path/to/new-answers \
  --models Qwen3.6-35B-A3B-6bit gemma-4-26B-A4B-it-qat-4bit Qwen3.8-27B-MLX-4bit
```

The sender calls an already running local OpenAI-compatible server (`LLM_BASE_URL`,
`LLM_API_KEY`); it does not start one or read the labels. Each model/case is sent once,
with fresh messages, no tools/history, no retry, seed 20260929, temperature 0, top_p 1,
max_tokens 1024 and thinking disabled. `one_shot`'s 1200-second timeout is a socket I/O
timeout, not a wall-clock deadline. Failed and invalid answers remain in the batch.
Outputs are never overwritten; an interrupted batch is unsealed and cannot be scored.
Do not blindly resend a request whose outcome is unknown.

## Score after sealing

```sh
PYTHONPATH=/path/to/frozen/src python experiments/diagnosis_baseline/generated_scores.py \
  /path/to/answers /path/to/separate-labels.json --output /path/to/new-summary.json
```

Scoring validates the complete seal, exact model/case sequence, original answers and all
input/label hashes before opening the labels. Keep the immutable pre-run registration
separately: local hashes detect inconsistent changes, not coordinated rewriting of all files.

- Diagnosis: accuracy and fixed-five Macro-F1.
- Hard: accuracy and per-class counts, Macro-F1 on the two registered truth-supported
  classes, plus the historical fixed-five Macro-F1. A perfect hard prediction scores
  1.0 on the supported classes and 0.4 on the fixed five; the other three have no examples.
- Missing/invalid roots count as incorrect. A valid root with missing `first_step` retains
  its root score and is separately reported as incomplete, following the old root metric.
- First-step quality remains **unscored** without a separate human rubric. Nonempty text
  does not establish correctness or repair success.

These are public development scenarios, including hard cases used in rule development.
Report the two suites separately and separately from the 12 real projects. Keep the
factory 44-feature model unchanged; this preparation does not train a new model.
