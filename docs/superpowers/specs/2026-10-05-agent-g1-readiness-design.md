# G1 harness completion (H3, H4, H7)

Scope follows the user-confirmed experiment plan v1.4, section 6, and Codex's
READINESS handoff. Implementation choices are delegated to Codex. No model runs,
sealed tasks, product changes, historical regrading or analysis-family changes.

## Interfaces

- Keep old defaults and the tail/paged tools. Add explicit `--file-read-mode
  lines`: one-based start_line and line_count, UTF-8 text with original newline
  spelling; retain mutually exclusive offset/limit character reads for long lines.
  Pages report total size, next position, EOF and omitted characters. Clip long
  selected text, command output and MCP output to head plus tail with an exact
  omission count, rather than dropping the useful beginning.
- Only lines mode offers edit_file. Replace exact old/new text in an existing
  bounded regular file. Default expected_count=1; multiple replacements require
  the exact count (1–1000). Missing/ambiguous text is an error without a write.
  Preserve newlines and permissions; atomically replace using an opened project
  directory, rejecting links/special files and outside paths. Do not weaken H5:
  protected edits remain recorded violations, including when restored.
- Permit 0–3 no-tool reminders per episode, retaining existing eligibility and
  deadline rules. `--max-length-continuations budget` explicitly means no extra
  allowance beyond the original turn/time budgets; numeric defaults remain.
  A length-truncated choice containing calls never executes or retries them.

## Measurement

Every row, including setup/reference failure, has diagnose/check_again called,
call counts and first turns (0 means a scheduled call before the first response).
Count actual dispatch attempts; invalid/nonexecuted calls do not count.

Finish is terminal: later calls in the same reply are recorded as not executed.
Record finish_called and finish_turn. Reuse the independent final grader after
agent processes stop; do not add an extra check to the agent's budget.
finish_check_status is not_called, passed, failed or not_checked; preserve its
raw exit code separately. Passed requires the original test contents, scope and
complete reference checks. Missing/invalid observations and stopped processes
stay not_checked. finish_fixed separately records final policy-qualified success,
so restored violations can leave checks passing while repair credit stays false.
Cleanup failure invalidates the finish verification. Never equate unknown with
failed or a model's finish claim with success.

## Binding and verification

Bind the new file-tools module into H5 identity and hard-instance tooling hashes.
New mode, reminder allowance and continuation setting already enter protocol
identity. Old saved rows and their default grouping remain untouched.

Verify reminder/continuation budgets, partial-call refusal and terminal finish
with fake replies. Verify exact edits, ambiguity, CRLF/Unicode, bounds and file
boundaries with temporary files. Exercise legal and protected edits through real
macOS sandbox grading, all arm prompts, successful/failed/unknown finish and
cleanup. Run knowledge guards, full suite, legacy-summary comparison, lint and
CI. Deliver a draft PR for Claude's independent acceptance; G1 service-parameter
verification and baseline calibration follow acceptance, not these offline tests.
