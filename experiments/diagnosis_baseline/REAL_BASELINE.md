# B3: saved real-project evidence and anonymous scoring

This workflow prepares the one-shot real-project baseline after the A2 handoff. It does not
change the frozen product, train a model, rerun project checks, or start a model server. The
implementation is checked with synthetic sessions and request stubs. No real-model result is
claimed here.

## 1. Preserve and prepare the original evidence

A/C should retain the original `.fixfirst/<session_id>/session.json` and the A2 `id` ↔
`session_id` mapping. A result summary with diagnoses and steps is insufficient: it lacks the
raw check output and snapshots. Do not rerun A2 to fill missing historical observations. Use
real records only after their independent scoring, reconciliation and sanitization are
confirmed and the result PR has been merged and handed off.

The locator file is either a JSON list or `{"results": [...]}`. Each row needs `id` and
`session_id`. Other A2 summary fields are ignored. For a nonstandard saved history, add
`observation_cutoff_run_id`, the final run of the original evidence batch. The automatic cutoff
recognizes only the original A2 order: environment, pip_check, pytest_run, ruff, project, optionally
followed by version_search/dependency_resolve/pip_install. Repeated, mixed or unsupported checks
are rejected; an explicit cutoff must still identify an unambiguous initial prefix.

```sh
python experiments/diagnosis_baseline/real_evidence.py \
  mapping.json saved-sessions prepared-evidence
```

Only saved `pass_tests` pytest sessions are supported. The adapter verifies project working
directory, interpreter identity, executed source, scope and snapshot/run links before replacing
known paths and opaque source identifiers with neutral aliases. Saved Windows paths are handled as
Windows paths even on macOS. It does not open the original project or interpreter.

Prepared `cases.jsonl` contains a case ID for pairing, raw evidence, its digest and the original
session digest. `manifest.json` records the original mapping/session hashes, selected run IDs,
cutoff, builder digest, field policy and limits. The model receives only the evidence object.
It includes package `requires`, static project declarations/imports, stdout/stderr, exceptions,
operation observations, failure text, node/stage associations and raw outcome/finish records.
FixFirst issues, facts, actions, diagnoses, follow-up search results, labels and reference fixes
are excluded. Fixed text/list limits are recorded in `truncation`; the comparison is a **bounded
presentation of shared original evidence**, not a claim of identical information or no loss.

Known project/environment paths are neutralized consistently. Absolute Windows and POSIX
home-directory prefixes outside those roots also have their account component neutralized.
Case IDs and session display names are omitted as metadata; they are not globally erased
from diagnostic content. A case named `pytest`, for example, must retain the actual package
name, import names, requirements and command text. Windows path matching is insensitive to
case, while Python names remain case-sensitive. Ambiguous identifier collisions are rejected
rather than silently changing evidence.

Prepared files from an older builder that replaced real package names with `case` cannot be
repaired by guessing the original names. Re-export from the unchanged original sessions with
the corrected, pinned builder and preserve both exports and their provenance. Do not rerun
project checks to replace historical evidence.

This is not a general secret scanner. Ambiguous unquoted paths and arbitrary secrets embedded
in original stdout still need review by the data owners; the adapter must not erase adjacent
diagnostic text to guess a path boundary.
Private source records, mappings and manifests should not be committed with experiment code.

## 2. Request answers without labels

After inputs, exact model identities, server context and decoding are locked and a real run is
authorized, point `LLM_BASE_URL` / `LLM_API_KEY` at the existing local server:

```sh
python experiments/diagnosis_baseline/real_baseline.py \
  prepared-evidence answers --models MODEL_A MODEL_B MODEL_C
```

This command **makes model requests**. Do not run it as a preparation check. It does not read
labels or evaluate accuracy. Each model gets the same evidence bytes in a fresh two-message
request, once per case, without tools. Defaults: temperature 0, top_p 1, max_tokens 1024,
thinking disabled, seed 20260929. These are B3 settings, separate from B7's turn/time budget.

The answer is one JSON object with `root_cause` and nonempty `first_step`. The five fault causes
are joined by `healthy`, meaning no necessary fix within the supplied completed check scope.
Missing, skipped or incomplete checks do not demonstrate health. Uncertainty belongs in the
first step; the six-class answer format has no separate `unknown` class. This does not change
the product classifier.

`results.jsonl` retains raw completions/responses, parsed fields, errors, latency and token
counts. Empty/malformed responses and failed requests remain in the batch; there are no retries.
`config.json` records the prompt, decoding, seed, script hashes and input hashes. Original input
files are copied into the answer directory. A checksum manifest and `SEALED.json` are written
only after all model/case rows exist. Interrupted batches cannot be exported; retained partial
rows are available for audit. Checksums detect inconsistency, not malicious rewriting by someone
who can replace every file. No input or output directory is overwritten.

The existing `one_shot.py` and historical development trials keep their original behavior.
Report five-fault-class diagnosis performance separately from `healthy` behavior and human
first-step quality. No automatic root-cause score substitutes for A/C's first-step judgment.

## 3. Seal first, then join labels and export sheets

```sh
python experiments/diagnosis_baseline/blind_scores.py \
  answers labels.csv blind-sheets private/model-key.json
```

The exporter verifies the seal, input/config/results hashes, every model/case pair, response
validity and per-case input hashes **before reading labels**. Labels accept the existing heldout
CSV schema (`id`, `root_cause`, `first_step`, `also_acceptable`, `partial_if`, `wrong_if`) or
equivalent JSON rows / `{"cases": [...]}`. IDs must match exactly. Include
`input_batch_sha256` in a JSON envelope or each row to bind labels to this input batch; legacy
labels without it can only be checked by their ID set, so their provenance still needs human
confirmation. For `healthy`, write an explicit no-fix reference step rather than an empty cell.

Each model is shuffled to one alias, `model-1`, `model-2`, etc. A and C each receive one UTF-8
BOM CSV per alias, with original project IDs, reference criteria, model cause/first step and
answer status. `score`, `scored_by` and `notes` start empty. Invalid or failed answers retain
their rows, with empty prediction cells; partial predictions remain in the sealed raw answers.
The existing `heldout.py agree --column score` and `summary` use the retained `id`, `score`,
`label_root_cause` fields. Human scoring remains correct/partial/generic/wrong.

The model key is created outside the sheet directory and is withheld until scoring ends. The
sheets exclude request errors, raw server metadata and true model names from metadata. A model
could still self-identify in its own first-step text, so metadata separation alone cannot
guarantee blinding. Scorers should record such a case without silently changing the answer.

## Comparison boundary

A2's task card scores FixFirst's step after an optional Find it search. B3 sees the original
raw check evidence and gives one answer without tools. Preserve and report that difference;
do not silently replace A2's scored step or invent an unavailable initial headline. Preparing
these scripts neither accepts A2 results nor registers or executes a formal experiment.
