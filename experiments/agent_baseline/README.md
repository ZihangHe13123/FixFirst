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
  or the keychains. Cases run with this repository's `.venv` Python (3.12, real libraries). Real
  projects each get their own environment; see "Real projects" below.
- **Grader, independent of FixFirst**: run the full suite with the original tests. A case counts as
  fixed when pytest exits 0, the same number of tests pass as in the healthy template, nothing is
  skipped, and no test file was changed. (In the 28 Sep pilot and MCP check a run that edited a test
  file still counted as fixed once the original tests were put back; that is now reported as
  `passes_with_original_tests`, never as `fixed`.) After every turn that changes files, the grader also runs on a copy, which gives
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

Runs go to `../agent-runs/` next to the repository (`--out`), each in its own folder that is never reused; `results.jsonl` there has one row per run. The output folder must not be inside the repository or below any folder with pytest settings, which pytest in the runs would read. In zsh,
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

## Real projects (B7 preparation, 29 Sep)

B7 runs on real projects and with the network on, so that both arms can install packages. The
harness now does this for development projects from `examples/real-world/projects.toml`; the new
held-out projects are added only after A2's results are merged.

```bash
.venv/bin/python experiments/agent_baseline/agent_pilot.py --model Qwen3.6-35B-A3B-6bit \
    --projects cachetools --sources ../test-projects/generalisation --network on \
    --arms baseline mcp --runs 1 --max-turns 12 --run-timeout 900
```

- **Same start for both arms.** Every run exports the project from the source clone's commit
  (`git archive`, no history, nothing from the working tree) and rebuilds its own `.venv` with uv from
  the recorded snapshot (`examples/real-world/environments/<id>.txt`). Environments are rebuilt, never
  copied (a copied environment keeps absolute paths). The row records the commit, any snapshot pin the
  rebuilt environment lacks, and a digest of the starting state.
- **Where code runs.** Creating the environment and installing the snapshot's pinned packages happens
  outside the sandbox, before the agent starts; no project code runs there. After that the case's
  interpreter is never started outside the sandbox: its home folder and version come from `pyvenv.cfg`
  as written at creation, and pip freeze at start and end is read from the packages' metadata files,
  so a startup hook (`.pth`, `sitecustomize`) in the environment, one the agent adds included, only
  ever runs inside the sandbox. Everything that runs the project's code runs under `sandbox-exec`
  (`isolation.py`): installing the project itself (with the network, for its build requirements), the
  agent's commands, FixFirst's server and the checks it starts, the reference repair, and every test
  run of the grader and the reference.
- **What each process may touch.** The agent's commands write only to the run's `project`, `state`
  (HOME, pip's cache, FixFirst's store) and `tmp` (TMPDIR) folders, never the system temporary
  folder. Under the home folder, the output folder, the repository and the system temporary folders
  they read only the run's own folders and the interpreters, so `reference_repairs.toml`,
  `examples/real-world/LABELS.md`, the reference outcomes and other runs are out of reach (checked by
  real processes in `test_harness.py`); `~/.ssh`, `~/.omlx`, `~/.claude` and the keychains are never
  readable. FixFirst's server may also read FixFirst's `src` and `.venv`, not the rest of the
  repository. The network is on for the agent only with `--network on`.
- **One interpreter.** Commands, pytest, FixFirst's diagnosis and the grader all use the case's
  `.venv`, with nothing inherited from the harness's environment. The MCP `diagnose` call always
  gets the case's project and interpreter: a missing value is filled in (`mcp_arguments_filled`), a
  different one is overridden (`mcp_arguments_overridden`).
- **Time.** `--run-timeout` is the agent's budget. Model requests, every tool call, FixFirst's
  server and every process get only what is left; at the deadline the whole process tree is killed
  (FixFirst's checks run in their own sessions, so the harness finds them by parent process). Calls
  left in a turn are not carried out and a `finish` after the deadline is not taken: the run ends as
  `time_cap`. The harness's own checks (integrity, green checks) do not count against the budget and
  are listed as `harness_s`. A model request is cut at the deadline as a whole: it runs in a thread
  and its connection is closed then, since httpx's timeouts only limit each wait (a server that keeps
  sending slowly would never trip them). A command's result comes when its own process ends, with
  stdin closed and the last 1 MB of output kept (the model sees the last 6,000 characters): a process
  it leaves in the background does not keep the harness waiting, even while it holds the output pipe.
- **Which processes are a run's.** This is decided by the sandbox alone. Every profile of a run names
  the run's random owner token (a Mach name that only that profile denies), and macOS gives every
  process started under a sandbox the same sandbox, which it can neither drop nor replace. So a
  process that cleared its environment, changed folder or left its session is still the run's, and a
  process that only works in the run's folder, or has the token in its command line or environment,
  is not. When the episode ends (finish, a cap, a model or harness error), and again when the run
  ends (also after a failed setup), the harness kills every process of the run, each one checked
  again just before (same start time, same sandbox), and then checks that none is left
  (`processes_stopped_at_end`); each grader check does the same for its own processes before it
  reads the report. Only the kernel's answer that a process no longer exists counts as gone: a
  process list that fails, may be cut short or lacks the harness itself, a process query or sandbox
  check that fails, and a process under the run's sandbox that cannot be read (it became another
  user) all mean that nothing can be shown. Then the run ends as `cleanup_failed` (the episode's end
  is kept in `episode_end`) and is not graded, and a reference is invalid. The profile refuses to
  have a process started outside the sandbox on the run's behalf (launchd jobs, LaunchServices
  `open`, Apple Events); other system services that run commands for a caller are outside what the
  harness supports.
- **Signals.** A command may signal itself and the processes it started, also detached ones, but not
  the harness, the user's processes or another run (`Operation not permitted`). macOS counts each
  `sandbox-exec` as its own sandbox, so a later command cannot signal what an earlier command of the
  same run left in the background; such processes end with the run.
- **Reference.** The known repair in `reference_repairs.toml` (the model never sees it) is applied to
  a separate copy in the sandbox, and the suite is run like a grader run. A reference counts only if
  every repair step exits 0 and its suite exits 0 with at least one passing test and none failing;
  otherwise the case's runs are recorded as `reference_invalid` and not graded. Preparing a reference
  is its own error boundary: a missing snapshot, a failed build or an unusable cache is recorded on
  every planned run of the case (with the error and any cache note) and the next case goes ahead. A
  cached reference is used only if it is complete, for the same key and still valid; it is written
  atomically, and an unusable one is renamed `*.unusable-<attempt>` (kept) and the reference built
  again. Unknown projects or projects without a known repair are refused before any run starts.
  Generated cases use
  the healthy template as their reference; scenarios that change test files or pytest settings have
  none and are recorded as `unsupported_case` (6 of the 44 scenarios, for example a bug in a fixture).
- **Grader.** The full suite runs offline on a fresh copy in the run's `grader/check-NNN` folder,
  which is all it may write. Fixed means: pytest exits 0; the same tests are collected as in the
  reference; nothing fails or errors; every test that passes in the reference passes; and no test
  file, `conftest.py` or test-selecting pytest setting (`addopts`, `testpaths`, `filterwarnings`, ...;
  `pythonpath` is allowed, since putting `src` on the path is an accepted repair) was ever changed.
- **Integrity over the run.** After every tool call that can change files, the harness compares
  those files and settings with the start. A change is recorded with its turn (`violations`) and
  stays recorded even if it is undone later; a run with a violation is never green and never fixed.
  The check sees the state between tool calls: a change made and undone inside one command is not
  seen.
- **Files the agent leaves.** The harness reads the agent's files outside the sandbox (integrity,
  digests, pip freeze, the JUnit report, the `read_file` and `write_file` tools), so it reads only
  regular files, opens them without waiting and never reads without limit: a test file replaced by a
  named pipe counts as changed, `read_file` and `write_file` refuse a pipe (`write_file` also refuses
  a link as the file name), and the grader's copy leaves pipes and sockets out.
- **Records, never overwritten.** Each run has its own folder,
  `runs/<case>--<arm>--r<n>--<model>--<attempt>`, where the model part is a safe name plus a hash and
  the attempt is the invocation's time and a random suffix (or `--attempt NAME`, which is refused if
  already used). The folder keeps the transcript and `commands.jsonl` written as they happen, pip
  freeze at start and end, `setup.json`, the sandbox profiles, every grader check and `row.json`; the
  row in `results.jsonl` names its folder (`run_dir`). Every planned run gets a row, also when setup,
  the model, FixFirst's server, the harness or the grader fails: `end` (`finish`, `turn_cap`,
  `time_cap`, `stopped_without_tool`, `model_error`, `mcp_start_failed`, `setup_failed`,
  `reference_invalid`, `unsupported_case`, `harness_error`, `cleanup_failed`), `error` with the stage, and `grading`
  (`graded`, `not_graded`, `grading_error`); `fixed` is empty unless the run was graded. Arms
  alternate per case and run.
- **Harness checks without a model.** `--model fake:SCRIPT.json` replays scripted replies, including
  malformed ones and slow ones. `experiments/agent_baseline/test_harness.py` (macOS, real sandboxed
  processes, offline; run it explicitly: `.venv/bin/python -m pytest -q experiments/agent_baseline/test_harness.py`)
  and `tests/test_agent_real_cases.py` (any platform) check isolation, grading, time, bookkeeping and
  integrity.

### Dry run with scripted replies (cachetools, 29 Sep, before the review fixes)

Reference: `python -m pip install -e .` gives 215 passed. Each script ran in its own rebuilt copy
with the network on:

| Script | Ended | Fixed | Why not |
|---|---|---|---|
| run the tests, `pip install -e .`, run them, finish | finish | yes (green at turn 2) | |
| `diagnose` with a wrong project and interpreter, install, `check_again`, finish | finish | yes (arguments overridden; FixFirst named D13 and then confirmed 215 passed) | |
| `pythonpath = ["src"]` for pytest (an accepted repair) | finish | yes | |
| `sys.path` in a new `tests/conftest.py` | finish | no | conftest changed |
| `PYTHONPATH=src python -m pytest` only | finish | no | fails in the grader's clean environment |
| delete `tests/` | finish | no | tests changed; no test ran |
| `pytest.ini` with `--ignore=tests` | finish | no | pytest setting changed; no test ran |
| the model request fails | model_error | no | recorded, graded as left |
| endless commands, 3 turns / 0 seconds | turn_cap / time_cap | no | |

### Smoke run with a model (`dev-smoke-2026-09-29/`)

**Made with the harness before the 29 Sep review fixes** (commit `ddb0f9d`: its grader still ran
outside the sandbox, the agent could read the repository, and the time cap was checked only between
turns). It shows the tool flow with a real model; it was not repeated after the fixes. **A development
smoke test of the harness, not a result**: one development project (cachetools
5.5.0 on the macOS system Python 3.9.6: src layout, the project not installed), one fast local model
(`Qwen3.6-35B-A3B-6bit` through omlx, started with environment variables and stopped afterwards; its
settings files were unchanged), each arm once, at most 12 turns and 15 minutes, network on, harness
commit `ddb0f9d`.

| Arm | Ended | Fixed | First green turn | Turns | FixFirst calls | Installs | Tokens (prompt / completion) | Model time |
|---|---|---|---|---|---|---|---|---|
| baseline (first) | finish | yes | 3 | 5 | 0 | 1 | 13,836 / 543 | 85.8 s |
| mcp (second) | finish | yes | 3 | 5 | 1 | 1 | 11,219 / 646 | 15.9 s |

Both arms installed the project with `pip install -e .` and changed no file. They started from the
same state (same digest, no missing pin). The baseline's model time includes loading the model on the
first request. In the mcp run the model passed the right project but no interpreter; this smoke run
still counted that as `mcp_arguments_overridden: 1`, and the harness now records it as
`mcp_arguments_filled`. One easy case and one run per arm say nothing about FixFirst's effect.

### After the review fixes (29 Sep): scripted checks

With the repaired harness, scripted replies on cachetools (network on): the reference repair ran in
the sandbox and the reference passed validation (215 passed); the baseline script (install the
project, finish) and the MCP script (`diagnose` with a wrong project, install, `check_again`) were both
fixed at turn 2, FixFirst's diagnosis running under the restricted profile. The review's
reproductions give: the agent cannot read the repair or the labels; the grader's project code
cannot write outside its copy; a timeout or a reference with an error never grades as fixed; a
0.05-second budget stops a 0.3-second command and the `finish` after it; a malformed tool call is
recorded and the transcript saved; a test edited and put back stays a violation; a repeat keeps the
first run's folder.

### After the third review (29 Sep): scripted checks

The review's three remaining gaps, reproduced and then re-checked: a `.pth` hook in the case's
environment no longer runs when the harness reads the interpreter's paths, its version or pip freeze
(it did in all three before), and a hook the agent adds during a run never writes outside the
sandbox; a model reply that keeps trickling is cut at 0.21 s for a 0.2 s budget and the server sees
the connection closed (the reply ran to its end after about 0.6 s before); a child that left its
parent is stopped when the run ends (it wrote after the run before); a half-written reference cache
and a missing snapshot are recorded on their cases' runs and the batch goes on (the cache error
escaped and stopped the batch before).

Four more ways the agent could stall the harness came up in the same round and were fixed, each
reproduced on the previous head first: a named pipe in the workspace made the integrity check, the
digest, the pytest settings and the JUnit report wait forever, and `write_file` onto one as well (a
scripted run was still stuck after 150 s); a detached child that kept the output pipe made a
finished command wait for it (12.1 s for a 3 s cap, now 1.1 s; in the grader 100 s, now 2 s, and a
longer-lived child would have stopped the check and failed the run); 400 MB of output was all kept
(1.3 GB more memory, now 1 MB kept and 7 MB more); and a command that read stdin waited on the
harness's input until its timeout. With scripted replies on cachetools, both arms were still fixed at
turn 2 and the rebuilt reference passed (215 passed).

### After the fourth review (30 Sep): process ownership

The review's two remaining findings, reproduced on `1fa6c65` first: the clean-up killed processes it
did not own (of three test processes, the one that only worked in the run's folder and the one that
only had the mark in its command line were killed along with the run's own), and it missed one it
did own (a child started by `run_command` with a clean environment, working folder `/` and its own
session wrote into the case after the run had returned as fixed). With ownership taken from the
sandbox, only the process under the run's profile is killed, and the hidden child is stopped when
the run ends (`processes_stopped_at_end` 1, nothing written after the trigger). The same holds when
the run ends with `finish`, a time cap, a model error, an answer without a tool call, a failed
install, a broken grader report or a harness error; a run whose processes cannot be shown stopped is
`cleanup_failed` and not graded.

### After the fifth review (30 Sep): signals and failed process queries

Both reproduced on `f380074` first, on processes created for the check and signalled by exact pid: a
sandboxed command could kill a process outside any sandbox and another run's process (both exited
with -15; now `denied 1`, both still running, while its own children, also detached ones, still end
on SIGTERM). And with the process list failing (EIO), a process query failing (EPERM) or a sandbox
check failing (-1), the clean-up reported success while the run's process was still alive; now each
is an error, and a whole run with such a failure ends as `cleanup_failed`, not graded.

### Not done yet

- The hard cases in B7 (six scenarios) still run with this repository's shared `.venv`. With the
  network on they need their own environments too, so that installing a package cannot touch
  FixFirst's environment; the sandbox already refuses such writes.
- Reference repairs exist for cachetools and typer only. The held-out projects get theirs from A2's
  verified repairs after A2's results are merged.
- The formal models' exact weights, quantisation and settings are fixed before the freeze; the
  formal run is 3 models × 2 arms × 3 runs (task B7).
- macOS only (`sandbox-exec`).

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
