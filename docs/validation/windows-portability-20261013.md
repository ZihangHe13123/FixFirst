# Windows portability corrections — 13 October 2026

Candidate for independent review and a Windows rerun. The version remains
`0.8.0rc5`; this is not a new frozen release or a Windows acceptance result.
Base: `ae6c4ec35d2614cfcd561eb0869e2cc27cf19119`.

## Changes

- Captured child stdout/stderr normalise CRLF to LF **before** redaction and parsing,
  on every host. Bare CR and LF-only output are preserved; the capture size limit
  still counts raw bytes. Other text-mode child reads already use universal newlines;
  JSONL readers split record separators rather than expose them as error text.
- Git preserves bytes by default (`* -text`), with LF for authored Python, TOML,
  Markdown, shell, YAML and report templates. The existing BAT/PowerShell CRLF
  exceptions remain. Published captures, result tables and manifests are unchanged.
- HTML reports use the package's actual version and goal status in their footer
  and subtitle.
- The offline dataset loader translates only the recorded identity of the literal
  `/venv/bin/python` placeholder into the current host's identity. Windows normalises
  that path differently; previously this made valid recorded issues look stale.
  Genuine interpreter paths and foreign/stale identities retain their checks. No
  saved case is rewritten, and runtime interpreter identity calculation is unchanged.
- Hard-case generation writes exact LF bytes, including when a template's service
  file is also a protected test. Existing integrity assertions remain intact.

### Test portability

Symlink tests run on Windows when creation succeeds. Actual `WinError 1314`
(privilege denied) or `50` (unsupported) skips the link-dependent case with a reason;
other errors still fail. The pre-existing blanket Windows skip on the resolved-path
comparison was removed. FIFO tests skip where `os.mkfifo` is unavailable.

Three tests inspect macOS sandbox profile syntax and run only on macOS: the two
profile-policy tests in the card, plus `test_profile_paths_are_real_paths`. The latter
also asserts POSIX quoting and would fail on Windows even if symlink creation were
permitted. This does not skip a product execution check. Long file-page parameter
values have short IDs, and the affected UTF-8 JSON/MCP test clients decode explicitly.
The two timing tests and all original assertions are unchanged.

## Checks

Validation was run on macOS with Python 3.12.14; Windows still needs a real-machine
rerun. The source, tests and support scripts pass Ruff and `git diff --check`.

| Check | Result |
|---|---|
| Windows-style CRLF pipe simulation, original affected cases | 15 passed |
| Windows portable-identity simulation, original affected cases | 14 passed |
| Stored B3 cases (220 diagnosis + 30 hard) | All native reports and diagnostic rows unchanged |
| Same rows with simulated Windows identity | Diagnostic rows unchanged; 20 reports only change the environment-ID component of pip log paths |
| Initial MCP reports for the 22 released evaluation tasks | Unchanged after replacing session IDs and elapsed seconds; fresh task environments, no repairs or model calls |
| `core.autocrlf=true` archive and checkout | All 1,790 tracked files byte-identical at implementation commit `dde7f3d` |
| Previously published CR-containing text files | All 39 byte-identical |
| Protected results, knowledge, model and source interfaces | 1,380 files unchanged; all 11 existing tags unchanged |

The 26 test files implicated in the Windows log passed in a separate editable install
of the exported tree: **991 passed, 14 skipped**. Its environment did not inherit
`PYTHONPATH`. The main suite excluding the three knowledge-receipt files passed:
**2,481 passed, 41 skipped**. Those three files passed **170 tests** after the fresh owners run, for **2,651 passed,
41 skipped, 0 failed** across the complete suite in two invocations.

The clean-environment owners run passed **155 keys and 23 merged keys**, with **0
stored-receipt audit problems** (692 seconds). Its only changed bound execution file
is `runner.py`. Fifteen recorded rows also reflect current NumPy, Pydantic and OpenAI
package releases; their owner checks still pass. The 23 merged records are unchanged.

Model SHA-256 remains
`189f712ea75bcb117f96aae879fd0c9bdab9ee6531475d1a95faf01ec2738d30`.
The owners receipt is regenerated because it binds `runner.py`; the knowledge matrix
is not rerun or edited. No experimental result is relabelled as belonging to this candidate.

## Windows rerun notes

- Two `sys.orig_argv` comparisons remain outside this correction. In the submitted
  Windows log, direct execution reports the base Conda interpreter as its first
  original argument; the native observer reconstructs it with `sys.executable`, the
  selected virtual-environment interpreter. The other ten compared fields agree.
  These assertions have not been skipped or relaxed.
- The reported movement of `ERROR` to the end of an installation hint was not
  reproduced. The template and inspected English screenshot place it correctly;
  there is no change to that hint.
- Chinese text corruption in the task terminal was not reproduced on macOS. The
  child environment already requests UTF-8, but the supplied terminal logs are not
  valid UTF-8. Their bytes alone do not establish which Windows console/redirect
  stage caused it. Real PowerShell/console reproduction remains necessary.
- The original C3 PowerShell command is unchanged. The reported quotation failures
  came from altered commands, not a proven defect in the task card.
