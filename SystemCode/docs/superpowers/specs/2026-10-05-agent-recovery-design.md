# Agent response recovery and persistent repair instructions

Approved by the user's instruction to continue after the 5 Oct development-run audit.
This changes the next development protocol; the completed 78 runs and their grades remain frozen.

## Scope

Change the agent harness, its common instructions, protocol identity, and offline tests.
Keep the product's rules, knowledge, default tree, grader, task starts, and reference repairs fixed.
Django-specific product guidance is a separate follow-up.

## Response handling

- Keep each completed API response, including all choices, finish reasons, message fields, and
  usage, in a run-local `responses.jsonl`. Write it before validating or executing any action.
  Do not store request headers or credentials. These raw responses are private run evidence and
  require sanitization before publication, just like transcripts.
- Continue only when the selected choice explicitly has `finish_reason=length` and has no tool
  calls. Append the returned assistant text and a neutral request to continue using the tools.
- Allow at most two such continuations per episode by default; expose
  `--max-length-continuations` (nonnegative integer). Each request consumes a normal turn and
  the existing time budget. Keep `max_tokens`, temperature, and seed unchanged.
- An exhausted allowance or a truncated reply containing tool calls ends as
  `response_truncated`. Do not execute a potentially partial action.
- An empty reply without calls ends as `empty_response`; retain raw message fields for diagnosis.
  Do not retry it. Complete nonempty replies without calls retain `stopped_without_tool`.
- Missing finish reasons never authorize continuation. HTTP failures and timed-out requests keep
  their current terminal behavior; no request with an unknown outcome is replayed.
- Record finish-reason counts, length responses, continuations, empty responses, and receipt count.
  If raw evidence cannot be saved, fail before any action from that response.

## Common instructions

All arms receive the same clarification: every command starts in a new shell in the project with
a clean environment; `export` and `cd` do not persist. The full original suite is graded again in
a fresh environment. A repair must persist in source, installed packages, or allowed project
configuration. Tests, `conftest.py`, and test-selection/outcome settings are protected throughout
the run, even if a change is later undone. Allowed configuration must not deselect or weaken tests.
Give no project-specific repair hint to the baseline.

## Identity and validation

Include the continuation allowance in protocol identity when the setting is present. Preserve
the exact protocol identity of legacy rows that lack it; do not pool the old and new runs.

Use scripted responses and a local stub API to test: successful continuation, allowance exhaustion,
partial-action refusal, empty versus ordinary stop, missing finish reasons, durable raw evidence,
turn/time limits, no timeout retry, and identical instructions across arms. Check legacy protocol
hashes, run the macOS sandbox harness tests and the normal full regression, and lint.

After the candidate and protocol are fixed, begin with a small separately registered development
pilot. Do not infer improved success from the offline tests or regrade old runs.
