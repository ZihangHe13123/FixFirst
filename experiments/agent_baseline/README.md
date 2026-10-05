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
  different one is overridden (`mcp_arguments_overridden`). In every case, real or generated, `diagnose` and `observe`
  also get the grader's goal (`pass_tests`: the full suite, with pytest), counted as `mcp_goal_filled`
  or `mcp_goal_overridden`, and so do the harness's own first calls under `scheduled`. In the
  2026-10-01 smoke Qwen3.8 passed no goal; FixFirst guessed unittest for cachetools (all its tests are
  unittest-style and no pytest section is configured) and kept reporting a failure after the pytest
  suite passed, so the agent spent another ~720 s on it. The goal carries no test content.
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
- **A registered failing install is the start, not an error.** Some real projects begin with the
  project itself failing to install (parsel 1.6.0: its `setup.py` imports `pkg_resources`, which
  today's setuptools no longer ships). The manifest registers such lines before any run with
  `install_fails`. Only a plain install of the project itself can be registered (`.`, `.[extras]`,
  `-e .` or `-e .[extras]`); a line that installs anything else as well, or that names the project's
  folder only as another option's value (`-r ./requirements.txt`, `--find-links . pytest`), is refused
  up front. Every arm and the reference then start from the same state: the registered step runs in
  the sandbox and must fail, as it did when the case was recorded, and the run continues from there.
  The step must run to completion and exit with an error of its own. If it succeeds, is stopped at its
  time limit, is ended by a signal, or (in a cached reference) has no record that it ran to completion,
  the start is not the registered one: the run ends as `setup_failed` with that reason before any
  episode, and the reference is invalid and never cached; nothing is skipped silently. A step that is
  not registered must still succeed. Every real-project row records `install_fails_registered` (also
  when its reference or environment failed), every install step records whether it was `stopped`, and
  the registration is part of the reference's cache key.
- **Projects the sandbox cannot support are excluded by a rule fixed in advance.** A project whose
  reference stays invalid only because its tests need what the sandbox denies (listing processes,
  files in the user's home, the network while grading) is left out of the main analysis, and the
  number and the reasons are reported. A reference that is invalid for any other reason (an incomplete
  repair, an install problem a repair can fix) is not excluded by this rule: it is repaired, or
  reported as invalid. Tests are never deselected to make a case pass; a common test
  subset would need a protocol change first and would be reported apart, never as passing the full
  original suite. Example: typer 0.3.2. Its repair needs both `shellingham` and `coverage` from the
  `[test]` extra (153 tests run the `coverage` command); with both, two tests still fail under the
  sandbox (`shellingham` runs `ps`, and one test expects a `~/.bashrc`).
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

## Three arms: FixFirst's facts or its full diagnosis (30 Sep, scripted checks only)

To tell whether an agent gains from the facts FixFirst collects or from its diagnosis, a third arm
gets only the facts:

| Arm | Tools |
|---|---|
| `baseline` | `run_command`, `read_file`, `write_file`, `finish` |
| `facts` | the same, plus FixFirst's facts (`fixfirst mcp --facts`, one tool: `observe`) |
| `mcp` | the same, plus FixFirst's full diagnosis (`diagnose`, `check_again`, `explain`) |

`observe` runs the same checks as `diagnose` and returns what they showed, as JSON: the interpreter,
how each check ended (exit code, test counts), each current failure's exception, message, where it
was raised (project, library or standard library) and the names involved, what the environment and
the project say about each module involved (installed and which version, standard library, project
file, similarly named project file, declared where) and pip check's conflicts. It never contains a
root cause or parser category, a rule, a knowledge-base fact, a model prediction, an order of
importance, a release search or a fix (`src/fixfirst/facts.py` builds it from an allowlist;
`tests/test_mcp_facts.py`). The facts server still works out a diagnosis while it ingests a check,
but keeps its sessions in its own memory and writes none to disk, and its sandbox has no access to
a session store: its checks run the project's own code under that sandbox, and that code (which
the agent may change) must not find a diagnosis to read. `test_harness.py` checks this with the
real stored diagnosis field, not only a marker. This closes the route by which a diagnosis could be
read from disk; it is not full process isolation between the server and the project code its
checks run, which share one sandbox (that code could, for example, stop the server). The full
arm's sessions are kept in the run's `fixfirst-store`, which the agent's commands cannot read.

`--call-policy` sets how the two FixFirst arms call it:

- `server` (default, B7's protocol): the tools, and each server's own instructions.
- `scheduled`: the harness calls FixFirst itself before the first turn and after every turn that
  changed the project, by the same rule in both arms, and gives the model the report (not the
  tools). Its time counts against the agent's budget (`fixfirst_s`); its text is part of the prompt,
  so the model's tokens include it (`fixfirst_output_chars` measures it independently of a model).
  The three arms are compared under this policy first.
- `required` and `on_demand`: the tools, with the same instruction to call them before changing
  anything and after each change, or only the note that they are available. These compare forced
  and on-demand calls.

Every arm starts from the same copy with the same permissions, budget and external grader. Each row
also records `first_green_s`, `fixfirst_calls`, `fixfirst_reports`, `fixfirst_s` (the time of every
FixFirst call, the model's own and the scheduled ones, also when a call fails), `usage_reported`
(whether the model server reported tokens at all), `facts_only_verified` (every facts report held
only facts' fields) and, in the full arm on generated cases whose cause is known,
`fixfirst_first_cause` and `wrong_first_cause`. Arms rotate which goes first per case and run. A
FixFirst server that exits fails the call at once instead of waiting for its timeout.

```bash
.venv/bin/python experiments/agent_baseline/agent_pilot.py --model fake:SCRIPT.json \
    --cases pkg-inventory:lm_renamed --arms baseline facts mcp --call-policy scheduled --runs 3
.venv/bin/python experiments/agent_baseline/compare_arms.py ../agent-runs/results.jsonl --json arms.json
```

`compare_arms.py` reports per model, policy and arm the fixed rate with a Wilson interval, turns and
seconds to the first green check, tokens, calls and FixFirst's cost, and pairs arms on the same case
and run (exact McNemar for fixed, sign tests for turns and tokens); runs that were not graded are
counted apart, never as failures. Runs are pooled or paired only under the same protocol (model
settings, budget, call policy, network and harness version, a harness with uncommitted changes
counting as its own), shown as a protocol id; the same run read twice counts once and two
different results for one run are refused; tokens a server did not report count as missing, not
zero. So far this was checked with scripted replies only, on public
development cases; the model and budget for a real comparison are not chosen yet.

`task_analysis.py` is the preregistered main analysis; `compare_arms.py` stays the auxiliary one. It
takes the task as the unit: per model, protocol and kind of case (real projects and generated hard
cases are never pooled), each task gets one fix rate per arm over its graded runs, and arms are
compared task by task (mcp − baseline, mcp − facts, facts − baseline). It reports the mean difference
with a 95% t-interval, a bootstrap interval as a sensitivity check, and an exact sign test; with
`--labels` (keys `kind:case`, or `case` when case names are unique across kinds) also per fault type.
Episodes a model ended are graded and count. A run is identified as in `compare_arms.py` (model, call
policy, protocol, kind, case, arm, run, attempt); it may be retried once, in a later attempt and only
after setup_failed, mcp_start_failed, cleanup_failed or harness_error, with the attempts in a known order
(started_utc, or the time in an automatic attempt id); anything else is a deviation, left out and
listed. Every run used must record its source identity (a real task's source commit, a generated
case's harness commit), and every attempt of a task that recorded one must agree on it, or the task is
left out and listed. A comparison whose two arms were run but one has no graded runs is shown with 0
tasks; all tasks agreeing (within 1e-9) is flagged degenerate with no interval; a ledger gives per group
and arm the rows read and kept and the runs used, never graded, retried and left out; a bare-case label
shared by several kinds is listed and not applied. The JSON also records the inputs' names, digests and
rows and the analysis code's digests, with its commit only when both files are that commit's. `--simulate` checks the analysis on synthetic tasks. In the
eleven settings tried (6–8 tasks, 3–5 runs, 2000 replicates each) the t-interval's false positives with
no effect were 1.5–5.9% and its coverage 90.6–96.4%, against 8.8–11.8% and 82.3–90.7% for the
percentile bootstrap, which is why the t-interval is the main one; neither has a general guarantee with
so few, bounded and discrete task differences, and the sign test (ties dropped) cannot reach p < 0.05
with fewer than six non-zero differences.
It also compares how fast the fix came, task by task: the turns to the first fix (a difference) and the
time to the first fix (a ratio of geometric means, on the log scale). The time is the harness's agent
time to the end of the turn after which the grader's check first passed (`first_green_s`), never the
episode's length (`agent_s`, `total_s`), which also counts what the agent did after the fix. As
preregistered only fixed runs count; because that favours an arm that fixes only the easy runs, it is
always shown with a failure-penalized version that keeps every graded run and counts one not fixed as its
whole budget (a score, not a time to fix). Speed is secondary: neither replaces the fix rate.

With `--family FAMILY.json` the report starts with the confirmatory family, as registered before the run:
mcp − baseline on real projects, one comparison per model, each model with its one protocol id and its
task set. Its decision is Holm's step-down procedure at 0.05 on the two-sided p-values of the paired
t-test (the test the t-interval belongs to, at full precision); the intervals shown stay the usual 95%
ones and are not adjusted. Only the registered tasks enter: a registered task without a graded run in
both arms is listed (the estimate is then over the tasks used, not the whole registered set), and so is
a task that was not registered. A model that cannot be estimated (no
data under its protocol, fewer than two tasks, or every task differing by the same amount) stays in the
family and counts as not rejected, so the family never shrinks after the results are seen. Everything
else in the report is exploratory. Holm's adjustment does not repair a t-test that is itself off with so
few tasks, so the family-wise error rate is not guaranteed; `--simulate --family-runs` shows how the
family behaves under chosen settings. In the thirteen settings of `family-evidence-c464214/` (three
models with 5, 5 and 3 runs per arm, 8 tasks, 2000 replicates each), where no model had an effect Holm's
procedure rejected at least one in 1.15–4.85% of replicates (11.35–17.70% with unadjusted p-values); where
every model truly gained 0.275 it rejected a 5-run model in 58.75% and 55.65% and the 3-run model in
40.35% (74.00%, 73.10% and 55.90% unadjusted). The adjustment costs power, and none of this is a guarantee.

With `--hard-selection SELECTION.json --hard-selection-sha256 HEX` the generated hard instances are held
to the selection frozen before the runs: the record `qualify_hard.py` wrote, and the SHA-256 registered
for that file, which the file must have. What is expected comes from that record, never from the rows:
which scenarios are hard, and which instance of each is the formal one. The formal instances are then a
kind of their own in the report (`hard`), apart from other generated cases. A run of one counts only if
every attempt of it, failed ones replaced by a retry included, ran under that selection
(`hard_selection`) in the formal role (`hard_role`), and no attempt recorded another instance
(`hard_instance`) than the selection's for its case; the graded attempt must record it. A run that fails
this is left out and listed with the protocol deviations, and a later attempt does not undo it. An attempt
that failed before its instance was built recorded none: it is counted, confirms nothing and contradicts
nothing. A hard case that is not a formal instance (a development instance, another template, any row
with hard-instance fields) is counted and analysed nowhere in that report; a formal instance's row
without the fields is not an ordinary generated case, it is left out. Formal instances without a run
used are listed per model and protocol. Real projects and other generated cases keep their own path, the
confirmatory family is untouched, and the protocol id still keeps budgets apart (a rehearsal at another
time limit is another group). Without the option, rows with those fields are analysed as generated
cases and the report says that nothing about their instances was checked: that is for development runs,
not for the formal hard analysis.

```bash
.venv/bin/python experiments/agent_baseline/task_analysis.py ../agent-runs/results.jsonl --labels labels.json --json tasks.json
.venv/bin/python experiments/agent_baseline/task_analysis.py ../agent-runs/results.jsonl --family family.json --json tasks.json
.venv/bin/python experiments/agent_baseline/task_analysis.py ../agent-runs/results.jsonl \
    --hard-selection experiments/agent_baseline/hard-selection.json --hard-selection-sha256 HEX --json tasks.json
.venv/bin/python experiments/agent_baseline/task_analysis.py --simulate --family-runs 5 5 3 --effects 0 0 0 --tasks 8 --replicates 2000
.venv/bin/python experiments/agent_baseline/task_analysis.py --simulate --tasks 8 --runs 3 --replicates 2000 \
    --baseline beta:0.5:0.5 --effect-model half --correlation 0.7
```

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

## H5 grading: persistent pytest configuration (5 Oct)

`--grading-policy h5-v1` selects the new rule. The default is `legacy`; old rows,
reference caches and protocol IDs keep their original interpretation.

- Test files, every `conftest.py`, and all files in `tests/`, `test/`, `testing/`
  stay unchanged. Violations seen after tools remain recorded after restoration.
- In root pytest configuration, only `pythonpath` and `DJANGO_SETTINGS_MODULE`
  may change. Every other option is protected, including plugin and future
  options. Cover `pytest.ini`, `.pytest.ini`, `pytest.toml`, `.pytest.toml`, both
  pyproject pytest tables, `tox.ini`, and `setup.cfg`. Native and ini tables are
  inspected separately; malformed, duplicate, oversized or nonregular files do
  not authorize a repair. Option names retain their case. `addopts` spacing is
  compared as shell tokens; multiline setting contents stay distinct.
- If configuration existed at the start, its carrier-file set cannot change.
  Otherwise at most one new location is allowed, containing only the two allowed
  options. This prevents new files from disabling existing settings, including
  settings absent from the harness's classification list.
- The full-suite grader imports its own probe before project collection, then
  restores the normal import path. It records the loaded configuration, raw and
  effective explicit protected options, exact collected nodes and their outcomes
  in `grader/check-NNN/{h5-observation,suite}.json`. The reference repair must
  meet the same static rule. Require the reference's node set, protected effective
  settings, and every reference-passing node to pass, as well as the JUnit checks.
  Incomplete observations produce `grading_error`, `fixed=null`, except that a
  confirmed static protection breach is already a graded failure and remains in
  the denominator even if its observation breaks. A trusted startup record plus
  a normal pytest failure exit (1–5) also establishes failure, including broken
  pytest imports and usage/configuration errors. Missing startup, stopped
  processes, and incomplete exit-0 observations remain ungraded. A pytest version
  that ignores the highest-priority configuration format or cannot recognize an
  active protected option also cannot grade; unchanged version-dependent defaults
  are not compared across tool upgrades.
- All arms receive exactly the same H5 instruction, naming the allowed keys.
  The rule is visible to the agent; any hint is shared by baseline, facts and MCP.
  `violations` includes the first observation and category. `violation_categories`
  distinguishes test content, selection/outcome options, other pytest options and
  carrier changes. Descriptive sensitivity analysis may list runs whose only
  violation was another option; it does not relax the primary grading rule.
- H5 rows, caches and hard manifests bind the policy and grading implementation
  SHA-256. `compare_arms.protocol` keeps different policies/implementations apart.
  Requalify and freeze future hard selections with the same explicit policy.

```bash
.venv/bin/python experiments/agent_baseline/qualify_hard.py \
  --out ../agent-runs/new-hard-h5 --grading-policy h5-v1
# Include --grading-policy h5-v1 in every run of the new registered batch.
```

Synthetic sandbox acceptance (no model):

```bash
.venv/bin/python -m pytest -q tests/test_h5_grading.py
.venv/bin/python -m pytest -q experiments/agent_baseline/test_h5_harness.py
```

The static snapshot and grader reports are structured observations inside the
existing sandbox grading boundary, not signed independent measurements of
malicious test code. There is no change to FixFirst product code or its model.

## Hard scenarios as agent tasks (2 Oct, scripted checks only)

The six hard scenarios (`src/fixfirst/hard_cases.py`) could not be run: `--cases` looked only at the
main scenarios, and five of the six append a test, which the harness refuses for a generated case
because the healthy template is then no reference. `hard_instances.py` adds them as tasks; an instance
is one template with one hard scenario applied.

- **What a scenario may add.** `hard_cases.toml` is the harness's own whitelist: per scenario the one
  check it may append to the template's test module (function name and body), the text its failure must
  show, and the repair. A start is admitted only if its tests and pytest settings are the healthy
  template's plus exactly that check, byte for byte (other line endings are another file); another test
  file, a changed conftest.py or pytest setting, an extra or altered test make it `unsupported_case`. The
  scenario without a check (`ml_renamed_then_alias`) must leave them unchanged.
- **Reference.** The start with the registered repair applied to a separate copy, never to a test; for
  the scenario without a check, the healthy template. It must pass cleanly with every test actually
  passing, the registered check among them (a skipped check proves nothing). The repair was written
  before any run; these fixes were known when FixFirst's rules were written, so hard cases stay
  development data and are reported apart from real projects.
- **During a run** nothing changes: the start's tests and settings are the baseline that must not
  change, the grader runs the whole suite offline on a copy and compares it test by test with the
  reference. Deleting the appended check, or replacing the faulty call by something that returns the
  wrong value, is not a fix. The agent's sandbox cannot read the registration, the repair, the reference
  or the other copies.
- **Answers kept out of reach.** A frozen selection carries the registered repairs, `--repairs` the known
  repairs of real projects, `--sources` their clones with the later history. A sandbox reads everything
  outside the home folder, the output folder, the repository and the system temporary folders, and
  inside those what it is given. So each of the three must lie in the home folder, the repository or a
  system temporary folder and share no path with anything a sandbox may be given: the output folder
  (every run's folders are made in it), FixFirst's code (`src/`), its environment and the interpreter
  that environment was made from, the 28 Sep tool and uv. Sharing counts both ways, answers inside such
  a folder or a folder of answers around one; otherwise the invocation is refused before any run. The
  interpreter a real project's own environment is made from is known only once that environment exists:
  every sandbox profile is held against the answers when it is written, so a run that would share a path
  with the clones ends as `setup_failed` (its reference as invalid) before any sandbox of it starts. On
  top of that every profile denies the selection and the repairs file by name, and the folder of clones
  with everything below it.
  A name is all the rule for a file knows: it holds where the sandbox cannot rename the file, which is
  why no file of answers may lie where a sandbox writes.
- **Identity.** An instance is the digest of its manifest: the registration, the appended check, every
  file of the start and of the reference, the tests and settings, the generator's and the harness's code
  by content, the interpreter and its installed distributions (names and versions, no paths), and how
  the suite is graded. The reference outcome is cached under that digest; every run copies the start and
  is checked file by file against the manifest; each row records `hard_instance`. The harness's code
  (the qualification script included) enters by content, not by commit, so that committing a record of
  the selection does not change the instances it records; the commit is still in every row and in the
  protocol id.
- **Environment.** Generated cases run offline with this repository's `.venv`; the sandbox does not let
  a run write to it, so changing a dependency's version is not a repair an agent can make here. The
  scenarios need NumPy 2, PyYAML 6, pydantic 2 and Click 8.2 or later installed there; a start that
  fails because a library is missing does not show the registered fault and does not qualify.
- **Qualification** (`qualify_hard.py`, no model): an instance qualifies when its start is admitted, its
  reference passes as above, and its start shows the registered fault: the check fails with the
  registered text and nothing else fails (without a check: the template's test module fails to load
  because the renamed helper is missing, and that loading error is the only thing the suite reports). A
  suite that did not run to a verdict says nothing about the instance: stopped at its time limit, ended
  by a signal, no exit code, pytest's own internal or usage error, or the sandbox or harness failing. Such
  a check is tried once more and then counts as not qualified. The record keeps, per attempt, the
  instance's whole manifest and what each failure said, so it can be checked without the run folders.
- **Which template.** Six scenarios, five templates. Each scenario has the templates in a fixed order:
  sorted by name, starting at the scenario's place among the sorted scenarios. Going through them, the
  first instance that qualifies is the formal one and the next that qualifies the development one, so
  the two always differ; then the scenario is done. One qualified instance is the formal one; none
  means the scenario cannot run, and it stays listed. `qualify_hard.py --out DIR` writes
  `hard-selection.json` with every attempt, its reason and digests. It must be made and committed
  before any model runs a hard instance; nothing in it depends on a model.
- **Frozen runs.** `agent_pilot.py --hard-selection FILE --hard-role formal|development` runs only the
  instances selected for that role and only while their digest is the recorded one; otherwise the case
  is refused before any run, or its rows are `reference_invalid`. Rows record `hard_role` and the
  selection file's digest.

Rotating the templates uses all five (two formal instances share one), but the six tasks are not
independent for that: they share templates and one generator, a template that is formal for one scenario
is the development template of another, and with six equally weighted instances the templates do not
weigh the same. Hard cases remain exploratory.

```bash
.venv/bin/python experiments/agent_baseline/qualify_hard.py --out ../agent-runs/hard
.venv/bin/python experiments/agent_baseline/agent_pilot.py --model M --cases fixture-orders:vb_yaml_loader \
    --arms baseline facts mcp --hard-selection ../agent-runs/hard/hard-selection.json --hard-role formal
```

Checked with scripted replies and the real suites only (2 Oct): all 30 template and scenario pairs are
admitted and take their repair; in this environment every start shows its registered fault and every
reference passes. No model has run a hard instance yet.
