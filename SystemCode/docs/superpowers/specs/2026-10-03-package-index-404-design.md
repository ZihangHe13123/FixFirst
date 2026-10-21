# Package project 404 feedback

The user approved this bounded follow-up while Claude independently checks
PR62. Start from `bab0ad66fd52b4b347f7b2dca87db536d3e34457` on a separate branch;
PR62's branch remains fixed.

## Problem and behavior

A recorded pip request for a misspelled package receives HTTP404 at the Simple
API project endpoint. The generic `Could not fetch URL` classifier currently
turns that into advice to restore connectivity/authentication.

Recognize a pip-reported HTTP404 for an HTTP(S) `/simple/<project>/` endpoint,
match its normalized project name to the failed requirement, and retain its
specific evidence reference. Report that this index project endpoint returned
not found. Ask the user to check spelling and the intended index. Do not infer
that a particular version, wheel or the project is absent from all indexes;
private repository access can also affect visibility.

Authenticated/private access failures, connection/TLS/DNS failures and server
errors keep access guidance. Root-index and artifact-download 404s do not prove
project absence. Another project's 404 cannot license a target-specific absence
claim or contaminate its failure with a false connectivity conclusion.

Requires-Python keeps its existing priority. A real access failure in a mixed
index log prevents a definitive project-absence diagnosis. A matching observed
source archive retains the existing no-wheel/manual-build route even if another
index returns a project404. No new online lookup, index switching, installation,
version relaxation or source-build policy is introduced.

The parser classification flows through both manual installation feedback and
explicit dependency trials. Project404 feedback offers a review step without an
unjustified build or replacement-version command.

## Verification and delivery

- Retain a before replay of the reported docoptt failure.
- Real pip against a local HTTP Simple index exercises logged project404 and
  access controls; offline log fixtures exercise mixed-index and name matching.
- Check the displayed next step, not just the parser code. Preserve 401/403,
  5xx, malformed/unrelated URL, source-archive and Python-requirement boundaries.
- Fixed before/after independent cases, targeted tests, one full regression,
  Ruff and an unchanged default model hash. No LLM or formal experiment.
- Publish a separate draft PR and wait for its CI; do not merge or change PR62.

## Sources and scope

The [Simple repository API](https://packaging.python.org/en/latest/specifications/simple-repository-api/)
defines project URLs relative to an index base and normalizes names by lowercasing
and collapsing runs of hyphens, underscores and periods. PyPI's base is `/simple/`;
the path recognition here is deliberately limited to that common shape. Other
layouts retain existing uncertain guidance rather than receiving an inferred
project-absence classification. The [pip install documentation](https://pip.pypa.io/en/stable/cli/pip_install/)
describes index options; this patch reads recorded failures and changes none of
those options.
