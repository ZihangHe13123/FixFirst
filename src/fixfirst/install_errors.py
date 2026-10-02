"""Extract installation blockers and their local build context from pip output."""

import re
from urllib.parse import unquote, urlsplit

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name, parse_sdist_filename
from packaging.version import InvalidVersion, Version


DETAILS = (
    ("legacy_build_config", re.compile(r"use_2to3 is invalid|invalid command ['\"]bdist_wheel['\"]", re.I)),
    ("missing_build_tool", re.compile(r"pg_config (?:executable )?not found", re.I)),
    ("missing_build_tool", re.compile(r"Microsoft Visual C\+\+.*(?:required|not found)", re.I)),
    ("missing_build_tool", re.compile(r"(?:can't find|cannot find|no) (?:a )?Rust compiler|cargo.*not found", re.I)),
    ("missing_build_tool", re.compile(r"(?:gcc|clang|cc).*No such file or directory", re.I)),
    ("missing_build_tool", re.compile(r"(?:fatal error|cannot open include file).*Python\.h.*(?:not found|No such file)", re.I)),
)
INDEX_ERROR = re.compile(
    r"Could not fetch URL|(?:NewConnection|NameResolution|Proxy|SSLCertVerification|SSL)Error"
    r"|Connection (?:refused|reset)|Temporary failure in name resolution"
    r"|(?:401|403) (?:Client Error|Unauthorized|Forbidden)", re.I,
)


def source_archive(value):
    if "Skipping link: No sources permitted for" not in value:
        return None
    link = re.search(r"(?:https?|file)://[^\s]+", value)
    if not link:
        return None
    try:
        return parse_sdist_filename(unquote(urlsplit(link[0]).path.rsplit("/", 1)[-1]))
    except ValueError:
        return None


def parse_install(run, event):
    requests, failures, details, sources, access = {}, [], [], [], []
    python_version = next((r.get("python_version") for r in run.records
                           if r.get("type") == "installation_context"), None)
    build_request = None
    if (len(run.argv) > 4 and run.argv[1:4] == ["-m", "pip", "wheel"]
            and "--no-deps" in run.argv and any(r.get("type") == "installation_context" for r in run.records)):
        try:
            request = Requirement(run.argv[-1])
            if not request.url:
                build_request = request
                requests[canonicalize_name(request.name)] = (str(request), f"{run.run_id}:argv:{len(run.argv) - 1}")
        except InvalidRequirement:
            pass
    for stream in ("stdout", "stderr"):
        for line, value in enumerate(getattr(run, stream).splitlines(), 1):
            found = re.search(r"\bCollecting ([A-Za-z0-9_.-]+(?:\[[^\]]+\])?(?:[<>=!~][^\s(]+)?)", value)
            if found:
                name = re.split(r"[\[<>=!~]", found[1], 1)[0].lower().replace("_", "-")
                requests[name] = (found[1], f"{run.run_id}:{stream}:{line}")
            for code, pattern in DETAILS:
                if pattern.search(value):
                    details.append((code, value.strip(), f"{run.run_id}:{stream}:{line}"))
                    break
            archive = source_archive(value)
            if archive:
                spec = re.search(r"\(requires-python:([^)]*)\)", value, re.I)
                compatible = None
                if spec and python_version:
                    try:
                        compatible = Version(python_version) in SpecifierSet(spec[1])
                    except (InvalidSpecifier, InvalidVersion):
                        pass
                sources.append((*archive, f"{run.run_id}:{stream}:{line}", compatible))
            if INDEX_ERROR.search(value):
                access.append((value.strip(), f"{run.run_id}:{stream}:{line}"))
            build = (re.search(r"Failed building wheel for ['\"]?([A-Za-z0-9_.-]+)", value, re.I)
                     or re.search(r"Failed to build ['\"]([A-Za-z0-9_.-]+)['\"]", value, re.I)
                     or re.search(r"installing build dependencies for ([A-Za-z0-9_.-]+) did not run", value, re.I))
            unavailable = re.search(r"No matching distribution found for ([^\s]+)", value, re.I)
            python_mismatch = re.search(r"Package ['\"]([^'\"]+)['\"] requires a different Python", value, re.I)
            explicit_conflict = bool(re.search(r"conflicting dependencies|dependency conflict", value, re.I)
                                     or (re.search(r"\bERROR\b", value) and "ResolutionImpossible" in value))
            metadata_failure = bool(build_request and re.search(r"\bERROR\b", value) and re.search(
                r"Preparing metadata.*(?:exited with|did not run)|metadata[ -]generation[ -]failed", value, re.I))
            if not (build or unavailable or python_mismatch or explicit_conflict or re.search(
                    r"\bERROR\b|Could not find|Failed building", value)):
                continue
            conflict = explicit_conflict
            failure = build or unavailable or python_mismatch
            component = (re.split(r"[\[<>=!~]", failure[1], 1)[0].lower().replace("_", "-") if failure
                         else canonicalize_name(build_request.name) if metadata_failure else "")
            failures.append({"value": value, "line": line, "stream": stream, "component": component,
                             "code": "build_failure" if build or metadata_failure else "no_distribution" if unavailable
                             else "python_requires" if python_mismatch else "", "conflict": conflict})
    # Do not attribute an unscoped compiler message to several failed packages.
    build_names = {f["component"] for f in failures if f["code"] == "build_failure"}
    python_names = {f["component"] for f in failures if f["code"] == "python_requires"}
    results = []
    for failure in failures:
        name = failure["component"]
        request = requests.get(name)
        local = details if len(build_names) == 1 and name in build_names else []
        skipped, python_excluded = [], []
        if failure["code"] == "no_distribution":
            requested = re.search(r"No matching distribution found for ([^\s]+)", failure["value"], re.I)
            try:
                req = Requirement(requested[1])
                matching = [(ref, compatible) for n, version, ref, compatible in sources
                            if n == canonicalize_name(req.name) and version in req.specifier]
                skipped = [ref for ref, compatible in matching if compatible is not False]
                python_excluded = [ref for ref, compatible in matching if compatible is False]
            except (InvalidRequirement, TypeError):
                pass
        message = failure["value"]
        if request:
            message += f". Requested requirement: {request[0]}"
        if local:
            message += ". Build detail: " + "; ".join(d[1] for d in local[:3])
        if skipped:
            message += ". The pip log shows a matching source archive was excluded by the wheel-only request."
        code = local[0][0] if local else "no_wheel" if skipped else failure["code"]
        if failure["code"] == "no_distribution":
            if name in python_names or (python_excluded and not skipped):
                code = "python_requires"
                message += ". The recorded Python requirement rejects this interpreter; a source build does not bypass it."
            elif access:
                code = "index_access"
                message += ". Package index access was incomplete: " + "; ".join(value for value, _ in access[:2])
        item = event(run, message, stage="install",
                     kind="dependency_conflict" if failure["conflict"] else "install_failure",
                     component=name, code=code,
                     line=failure["line"], stream=failure["stream"])
        item.evidence_refs += (([request[1]] if request else []) + [d[2] for d in local[:3]]
                              + skipped[:3] + python_excluded[:3]
                              + ([ref for _, ref in access[:2]] if code == "index_access" else []))
        results.append(item)
    return results or [event(run,
        "No recognisable failure in the installation log; this does not prove installation succeeded",
        stage="install", kind="other_unknown")]
