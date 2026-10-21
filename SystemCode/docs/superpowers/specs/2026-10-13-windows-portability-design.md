# Windows portability corrections

This implements the user-supplied 13 October Windows modification card against
`ae6c4ec`. The package version remains `0.8.0rc5` until the user names the next release.

- Normalise decoded subprocess CRLF to LF before redaction and parsing on every host.
  Keep isolated carriage returns. Byte limits still apply to the original pipe bytes.
- Preserve checked-in bytes by default in Git, enforce LF for authored source, and keep
  the existing CRLF launcher exceptions. Record the 39 published text files containing
  carriage returns and verify that their bytes, all published results and frozen tags stay intact.
- Render the package version and goal state in the HTML report, using the existing
  version source and goal states.
- Skip symlink fixtures only when Windows actually refuses symlink creation; guard
  FIFO tests and skip POSIX-path sandbox-profile tests only on Windows, shorten the long parameter IDs, and decode UTF-8
  explicitly in the affected test clients. Preserve all original assertions.
- Make the hard-case writer preserve the registered test bytes. Do not rewrite its
  published results or manifests, or change the two timing tests.
- Investigate saved-session replay before changing it. A small adapter may translate
  the dataset's portable interpreter identity at load time if macOS predictions remain
  identical and stale/foreign evidence is still rejected. Otherwise document and skip
  the unsupported replay, as the card permits.

Validation covers real CRLF child output, redaction order, isolated CR, HTML state/version,
saved-case comparisons, a `core.autocrlf=true` export, the full development suite and Ruff.
Windows operation still requires the teammate's real-machine rerun. Rules, knowledge entries,
features, model weights, MCP schemas and frozen evaluation artifacts are outside this change.
If code-bound verification receipts expire, regenerate their recorded product runs rather than
editing hashes by hand, and list that derived receipt update separately.
