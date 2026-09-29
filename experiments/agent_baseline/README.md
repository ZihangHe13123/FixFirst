# Agent baseline: a local model fixing failures, with and without FixFirst

At the proposal presentation (28 Sep 2026) the examiner asked for a baseline, either a local model or
an online flagship model. This experiment asks: when a language model fixes failing tests on its
own, does giving it FixFirst help? FixFirst is offered the way an MCP server would offer it: one
extra tool plus a short usage note.

## Setup

| | `baseline` arm | `mcp` arm | `fixfirst` arm (28 Sep pilot) |
|---|---|---|---|
| Tools | `run_command`, `read_file`, `write_file`, `finish` | the same, plus `diagnose`, `check_again` and `explain` from `fixfirst mcp`, called over MCP stdio | the same, plus `fixfirst_check` (`ff_tool.py`, the raw issue list) |
| System prompt | fix the root cause, do not edit or skip tests, offline | the same, plus the server's instructions, as an MCP client adds them | the same, plus a one-line usage note |

The `mcp` arm is the one to use from now on; `fixfirst` stays only so the pilot can be repeated.

- **Cases**: projects built by `diagnosis_cases.py`, given as `template:scenario`.
- **Isolation**: every command, FixFirst check and grading run executes under macOS `sandbox-exec`.
  It can write only inside the case, has no network, and cannot read `~/.ssh`, `~/.omlx`, `~/.claude`
  or the keychains. Cases run with this repository's `.venv` Python (3.12, real libraries).
- **Grader, independent of FixFirst**: restore the original test files and run the full suite. A case
  counts as fixed when pytest exits 0, the same number of tests pass as in the healthy template, and
  nothing is skipped. After every turn that changes files, the grader also runs on a copy, which gives
  the first turn at which the project was really fixed ("first green turn").
- **Recorded**: fixed, first green turn, turns, tool calls, pytest runs, FixFirst calls, tokens,
  model and tool seconds, test files changed. Every conversation is saved as a transcript.

## Running

Start omlx with environment variables, not flags; `omlx serve --host/--port` writes the flags into
`~/.omlx/settings.json`:

```bash
OMLX_HOST=127.0.0.1 OMLX_PORT=8123 OMLX_API_KEY=<any throwaway key> omlx serve
```

Then, from the repository root:

```bash
export LLM_API_KEY=<the same key>        # LLM_BASE_URL defaults to http://127.0.0.1:8123/v1
.venv/bin/python experiments/agent_baseline/toolcall_smoke.py Qwen3.8-27B-MLX-4bit
.venv/bin/python experiments/agent_baseline/agent_pilot.py --model Qwen3.8-27B-MLX-4bit \
    --cases pkg-inventory:lm_renamed flat-shop:lm_src_layout    # arms: baseline and mcp
```

Cases, transcripts and `results.jsonl` go to `workbench/agent_baseline/` (ignored by git). In zsh,
list the cases as separate arguments: an unquoted `$CASES` is not split into words.

## Pilot, 28 Sep 2026

Three local models through omlx 0.6.4 on an Apple M5 Pro (48 GB): `gemma-4-26B-A4B-it-qat-4bit`
(MoE, about 4B active), `Qwen3.6-35B-A3B-6bit` (MoE, about 3B active; mlx-community's conversion of
the official weights, revision `cb7e092`) and `Qwen3.8-27B-MLX-4bit` (dense). Four cases, both arms,
one run each, temperature 0.2, at most 20 turns. Results: `pilot-2026-09-28/results.jsonl`;
conversations: `pilot-2026-09-28/transcripts/` (machine paths replaced by `<cases>`, `<home>`, `<tmp>`).

All 24 runs were fixed. First green turn, baseline → FixFirst:

| Case (FixFirst's rule) | Gemma-26B-A4B | Qwen3.6-35B-A3B | Qwen3.8-27B |
|---|---|---|---|
| `pkg-inventory:lm_renamed` (D16) | 7 → 11 | 4 → 6 | 4 → 3 |
| `flat-shop:lm_src_layout` (D13) | 16 → 8 | 6 → 8 | 5 → 5 |
| `src-billing:vi_removed_kwarg` (D04) | 7 → 6 | 4 → 4 | 5 → 4 |
| `fixture-orders:lm_shadow_library` (D10) | 7 → 5 | 5 → 5 | 5 → 6 |
| Sum | 37 → 30 | 19 → 23 | 19 → 18 |
| Turns until the run ended | 51 → 47 | 28 → 36 | 26 → 34 |
| Wall time | 333 s → 159 s | 138 s → 144 s | 605 s → 765 s |

What we saw:

1. **No difference in success**: every model fixed every case in both arms.
2. **Stronger models gained nothing on these cases.** The first green turn stayed about the same, and
   the re-checks the usage note asks for added 1–4 turns in total.
3. **The weakest model gained most.** Gemma was faster in 3 of 4 cases. On `lm_src_layout` without
   FixFirst it edited the test imports, found the real fix only at turn 16 and never called `finish`;
   with FixFirst it set pytest's `pythonpath` at turn 8. It was slower on `lm_renamed` because it ran the
   same `grep` seven times after FixFirst had already named the renamed file.
4. **The tool alone is not enough.** In an earlier trial without the usage note, Gemma never called
   `fixfirst_check`.
5. **FixFirst's first step was right in all four cases**, but its output had noise. `ff_tool.py`
   prints the raw issue list, so Ruff style findings appeared as open problems; Qwen3.8-27B then edited
   a test file (one blank line) to satisfy Ruff. The web interface already keeps these out of the
   must-fix list (`workspace.build_view`); the MCP version should use that view.
6. **Fix quality differs.** On `lm_shadow_library`, 3 of 6 runs deleted the project file `yaml.py`
   instead of renaming it. FixFirst said "rename"; Gemma followed it, Qwen3.8-27B did not.

Limits: single-fault generated cases are too easy for a repair experiment, and the injected code is
usually unused, so deleting it also makes the tests pass. One run per cell is anecdotal. These four
cases were all decided by rules, so the decision tree (trained on all 215 cases) played no part.
`ff_tool.py` is kept as it was run, so the pilot can be repeated exactly.

## MCP arm check, 28 Sep (evening)

After `fixfirst mcp` was added, the `mcp` arm ran on the same four cases with the two fast models,
one run each (`mcp-check-2026-09-28/`). The baseline and `fixfirst` numbers are the pilot's, from a
few hours earlier, not a side-by-side rerun.

| Model | First green turn, sum of 4 cases (baseline / fixfirst / mcp) | Turns until the end (baseline / fixfirst / mcp) |
|---|---|---|
| Gemma-26B-A4B | 37 / 30 / **22** | 51 / 47 / **34** |
| Qwen3.6-35B-A3B | 19 / 23 / 20 | 28 / 36 / 32 |

All eight runs were fixed, no run changed a test file, and every run ended with `finish`. Both
models renamed `yaml.py` instead of deleting it. With the cleaner MCP output the weaker model was
faster than its baseline in all four cases; the stronger one stayed about level with its baseline.
Still one run per cell: the formal run repeats each cell three times.

## Before the formal run

- **MCP server**: done on 28 Sep (`fixfirst mcp`): tools `diagnose`, `check_again`, `explain`, output
  from `workspace.build_view` (steps that block the goal, with location, cause and rule; a clear
  "done" state), usage note as the server's instructions. `find_version` is not offered yet.
- **Cases**: new real projects as the main set; multi-fault and misleading cases; hidden behaviour
  checks so that deleting the faulty code does not pass; for generated cases, a decision tree retrained
  without the scenario under test.
- **Runs and metrics**: 3 runs per case and arm, compared per case; results reported per model; add
  destructive actions (deleted project files, edited tests) and whether the next action follows
  FixFirst's first step.
- **One-shot diagnosis baseline**: give each model the same evidence and ask only for the cause and
  the first step, with no tools. This separates knowing the answer from carrying it out.
