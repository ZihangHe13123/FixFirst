"""Reconcile all registered toolchain attempts before evaluating a new suite."""


def validate(manifest, *, complete=True):
    if manifest.get("schema_version", 1) < 2:
        return  # Historical intake has a separately documented selection ledger.
    if complete and manifest.get("completion") != "complete":
        raise ValueError("Toolchain generation did not complete; partial suites cannot be evaluated")
    templates = manifest.get("templates", [])
    scenarios = [row["id"] for row in manifest.get("scenarios", [])]
    if (not templates or not scenarios or len(set(templates)) != len(templates)
            or len(set(scenarios)) != len(scenarios)):
        raise ValueError("Toolchain roster must contain unique templates and scenarios")
    expected = {f"{template}--{scenario}" for template in templates for scenario in scenarios}
    seen, not_attempted = set(), set()
    for kind in ("cases", "unparsed", "rejected", "inapplicable"):
        for row in manifest.get(kind, []):
            key = row["case_id"]
            if key in seen or key not in expected:
                raise ValueError("Toolchain attempt appears twice or outside the registered roster")
            seen.add(key)
            if kind == "inapplicable":
                not_attempted.add(key)
    if seen != expected:
        raise ValueError("Toolchain ledger does not account for every registered combination")
    audit = manifest.get("audit_files", [])
    required = {f"audit/{case_id}.json" for case_id in seen - not_attempted}
    if len(set(audit)) != len(audit) or set(audit) != required:
        raise ValueError("Toolchain audit roster does not match its attempted cases")
