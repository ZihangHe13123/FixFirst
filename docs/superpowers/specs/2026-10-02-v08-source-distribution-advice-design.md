# v0.8 source-distribution advice

Status: approved implementation scope; prepared before production edits.
Base: `91f1a98`. This change preserves the existing manual wheel preparation,
saved installation feedback and wheel-only isolated trial boundaries.

## Problem

A wheel-only request can reject an available source archive. That outcome must
not imply that a version does not exist or that Python is incompatible. Existing
manual-build advice also needs accurate evidence and a useful next step after a
build prerequisite fails, without repeating the unsuccessful install/build.

## Small mechanism

1. Preserve release-filter reasons in version searches: usable wheels, matching
   source archives, Requires-Python exclusions, platform wheel exclusions and
   declared-version exclusions. Only usable wheels reach the isolated probe.
   A source archive does not establish that its build or application will work.
2. Read explicit pip/uv failure evidence, including local `file:` source links.
   Distinguish a wheel restriction from a missing release, index/network access,
   an explicit Requires-Python rejection, declaration conflicts and a source
   build missing tools such as `pg_config`. Ambiguous output stays uncertain.
3. Reuse the existing manually chosen `pip wheel` operation and bound log import.
   Explain that source build scripts run, build dependencies may be needed, and
   native tools/headers are unknown until documented or observed. Ordinary scans
   do not execute this operation. Failed feedback must address its blocker and
   suppress the original failing command. A validated prepared wheel can rejoin
   the existing wheel-only dependency trial; neither step verifies application
   behavior.

No global removal of `--only-binary`, system installation, sudo, new rule IDs,
domain knowledge edits or classifier changes are planned. The work stays in the
installation/version-advice modules and the release-result parser wording.

## Verification

Use deterministic mechanism cases plus a local no-network source archive with
a self-contained build backend. Exercise wheel rejection, explicit manual
wheel build, feedback, wheel reuse and failure suppression. Cover a usable
wheel, pure-Python sdist, missing native build tool, unavailable index/network,
Requires-Python refusal and declaration conflict. Preserve existing feedback
context, interpreter, constraints and artifact validation regressions.

No historical third-party source package will be built for this check. No LLM,
formal evaluation, held-out input or A2 rerun is involved. Windows-shaped input
checks do not constitute real Windows acceptance.

## Implementation validation

- Focused installation/version/reasoning checks: 131 passed.
- Full suite: 1,254 passed, 1 skipped. Ruff and whitespace checks passed.
- The local no-network fixture actually rejects an sdist in a wheel-only
  request, builds its self-contained pure-Python backend only after the explicit
  manual command, then installs its prepared wheel and passes `pip check` in a
  disposable environment. A second controlled backend reports a `pg_config`
  prerequisite failure; feedback blocks both the build and original install
  from being offered repeatedly. This is not a real PostgreSQL extension build.
- The pip fallback trial also retains source-archive evidence without running
  that backend. Existing uv wheel-only and declaration-conflict checks pass.
