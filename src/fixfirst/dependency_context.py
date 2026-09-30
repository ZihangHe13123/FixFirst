"""Target-environment requirements shared by repair advice and release searches."""

import hashlib
import json

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version


MARKER_KEYS = frozenset(default_environment())


def active_requirement(text: str, markers: dict, extras=()) -> Requirement | None:
    """Never evaluate a target marker using implicit host-machine values."""
    requirement = Requirement(text)
    if requirement.marker:
        if not MARKER_KEYS.issubset(markers):
            raise ValueError("Target environment markers are incomplete")
        if not any(requirement.marker.evaluate({**markers, "extra": extra}) for extra in {"", *extras}):
            return None
    return requirement


def context(environment: dict, project: dict) -> dict:
    records, notes, installed = [], [], {}
    markers = environment.get("markers", {})
    selected = {}
    packages = {canonicalize_name(p.get("name", "")): p for p in environment.get("packages", [])}
    for row in project.get("declarations", []):
        if row.get("group", "required") != "required" or row.get("constraint"):
            continue
        try:
            requirement = active_requirement(row.get("requirement", ""), markers)
        except (InvalidRequirement, ValueError, KeyError, TypeError):
            continue
        if requirement and requirement.extras:
            selected.setdefault(canonicalize_name(requirement.name), set()).update(requirement.extras)
    pending, visited = list(packages), set()
    while pending and len(visited) < 5000:
        owner = pending.pop()
        key = owner, tuple(sorted(selected.get(owner, ())))
        if key in visited:
            continue
        visited.add(key)
        for text in packages.get(owner, {}).get("requires", []) or []:
            try:
                requirement = active_requirement(text, markers, selected.get(owner, ()))
            except (InvalidRequirement, ValueError, KeyError, TypeError):
                continue
            if not requirement or not requirement.extras:
                continue
            target = canonicalize_name(requirement.name)
            current = selected.setdefault(target, set())
            if not requirement.extras <= current:
                current.update(requirement.extras)
                pending.append(target)
    if pending:
        notes.append("Explicit extra dependency traversal exceeded its limit")

    def add(text, source, refs, owner):
        try:
            requirement = active_requirement(text, markers, selected.get(owner, ()))
        except (InvalidRequirement, ValueError, KeyError, TypeError):
            notes.append(f"{source}: requirement could not be evaluated")
            return
        if requirement is None:
            return
        if requirement.url:
            notes.append(f"{source}: direct reference is not a version constraint")
            return
        records.append({"name": canonicalize_name(requirement.name),
                        "requirement": str(requirement), "specifier": str(requirement.specifier),
                        "source": source, "owner": owner, "refs": refs})

    env_ref = [f"{environment['_run_id']}:stdout:1"] if environment.get("_run_id") else []
    for package in environment.get("packages", []):
        name = canonicalize_name(package.get("name", ""))
        version = package.get("version", "")
        if not name or not version:
            continue
        if name in installed and installed[name] != version:
            notes.append(f"{name}: multiple installed versions")
        installed[name] = version
        for text in package.get("requires", []) or []:
            add(text, f"{name} {version} Requires-Dist", env_ref, name)
    project_ref = [f"{project['_run_id']}:stdout:1"] if project.get("_run_id") else []
    for row in project.get("declarations", []):
        if row.get("group", "required") != "required" and not row.get("constraint"):
            continue
        if row.get("installer", "pip") != "pip":
            continue
        add(row.get("requirement", ""), row.get("source", "project declaration"), project_ref, "project")
    # Scope includes every installed requirement, target marker and declaration.
    # A changed reverse dependency invalidates a prior result even if the searched
    # package itself has not changed version. Run IDs are deliberately excluded.
    identity = {"python": environment.get("python_version"), "markers": markers,
                "installed": installed,
                "requirements": [{k: r[k] for k in ("name", "requirement", "source", "owner")}
                                 for r in records],
                "requires_python": project.get("requires_python", []),
                "selected_extras": {name: sorted(extras) for name, extras in selected.items()},
                "notes": sorted(set(notes))}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return {"installed": installed, "requirements": records, "notes": sorted(set(notes)),
            "fingerprint": digest}


def requirements_for(data: dict, name: str) -> list[dict]:
    name = canonicalize_name(name)
    return [r for r in data["requirements"] if r["name"] == name and r["specifier"]]


def combined_specifier(data: dict, name: str, extra: str = "") -> str:
    specs = [r["specifier"] for r in requirements_for(data, name)]
    return str(SpecifierSet(",".join([*specs, extra])))


def contradicts(specifier: str) -> bool:
    """Prove simple empty intersections; absence of proof is not solvability."""
    specs = list(SpecifierSet(specifier))
    pins = [s.version for s in specs if s.operator in ("==", "===") and "*" not in s.version]
    if pins:
        try:
            return not any(SpecifierSet(specifier).contains(v) for v in pins)
        except InvalidVersion:
            return True
    lower, upper = [], []
    for spec in specs:
        try:
            version = Version(spec.version.rstrip(".*"))
        except InvalidVersion:
            continue
        if spec.operator in (">", ">="):
            lower.append((version, spec.operator == ">="))
        if spec.operator in ("<", "<="):
            upper.append((version, spec.operator == "<="))
        if spec.operator == "==" and spec.version.endswith(".*"):
            lower.append((version, True))
            release = list(version.release)
            release[-1] += 1
            upper.append((Version(".".join(map(str, release))), False))
        if spec.operator == "~=":
            lower.append((version, True))
            release = list(version.release[:-1])
            release[-1] += 1
            upper.append((Version(".".join(map(str, release))), False))
    if not lower or not upper:
        return False
    lo = max(lower, key=lambda pair: (pair[0], not pair[1]))
    hi = min(upper, key=lambda pair: (pair[0], pair[1]))
    return lo[0] > hi[0] or (lo[0] == hi[0] and not (lo[1] and hi[1]))


def bounded_adjustment(specifier: str, installed: str) -> str:
    """Bound an otherwise open upgrade to one release family, not a proven fix."""
    specs = list(SpecifierSet(specifier))
    if any(s.operator in ("<", "<=", "==", "===", "~=") for s in specs):
        return specifier
    anchors = []
    for text in [installed, *(s.version for s in specs if s.operator in (">", ">="))]:
        try:
            anchors.append(Version(text))
        except InvalidVersion:
            continue
    if not anchors:
        return specifier
    latest = max(anchors)
    limit = str(latest.major + 1) if latest.major else f"0.{latest.minor + 1}"
    return str(SpecifierSet(f"{specifier},<{limit}".strip(",")))


def trial_constraints(data: dict, changed: str) -> list[str]:
    """Keep other installed versions fixed while testing a single-package change."""
    changed = canonicalize_name(changed)
    constraints = []
    for name, version in data["installed"].items():
        if name != changed:
            try:
                constraints.append(str(Requirement(f"{name}=={version}")))
            except InvalidRequirement:
                continue
    constraints += [r["name"] + r["specifier"] for r in data["requirements"] if r["specifier"]]
    return sorted(set(constraints))
