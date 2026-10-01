"""Extract installation blockers and their local build context from pip output."""

import re
from urllib.parse import unquote, urlsplit

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name, parse_sdist_filename


DETAILS = (
    ("legacy_build_config", re.compile(r"use_2to3 is invalid|invalid command ['\"]bdist_wheel['\"]", re.I)),
    ("missing_build_tool", re.compile(r"pg_config (?:executable )?not found", re.I)),
    ("missing_build_tool", re.compile(r"Microsoft Visual C\+\+.*(?:required|not found)", re.I)),
    ("missing_build_tool", re.compile(r"(?:can't find|cannot find|no) (?:a )?Rust compiler|cargo.*not found", re.I)),
    ("missing_build_tool", re.compile(r"(?:gcc|clang|cc).*No such file or directory", re.I)),
    ("missing_build_tool", re.compile(r"(?:fatal error|cannot open include file).*Python\.h.*(?:not found|No such file)", re.I)),
)


def source_archive(value):
    if "Skipping link: No sources permitted for" not in value:
        return None
    link = re.search(r"https?://[^\s]+", value)
    if not link:
        return None
    try:
        return parse_sdist_filename(unquote(urlsplit(link[0]).path.rsplit("/", 1)[-1]))
    except ValueError:
        return None


def parse_install(run, event):
    requests, failures, details, sources = {}, [], [], []
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
                sources.append((*archive, f"{run.run_id}:{stream}:{line}"))
            build = (re.search(r"Failed building wheel for ['\"]?([A-Za-z0-9_.-]+)", value, re.I)
                     or re.search(r"Failed to build ['\"]([A-Za-z0-9_.-]+)['\"]", value, re.I)
                     or re.search(r"installing build dependencies for ([A-Za-z0-9_.-]+) did not run", value, re.I))
            unavailable = re.search(r"No matching distribution found for ([^\s]+)", value, re.I)
            python_mismatch = re.search(r"Package ['\"]([^'\"]+)['\"] requires a different Python", value, re.I)
            explicit_conflict = bool(re.search(r"conflicting dependencies|dependency conflict", value, re.I)
                                     or (re.search(r"\bERROR\b", value) and "ResolutionImpossible" in value))
            if not (build or unavailable or python_mismatch or explicit_conflict or re.search(
                    r"\bERROR\b|Could not find|Failed building", value)):
                continue
            conflict = explicit_conflict
            failure = build or unavailable or python_mismatch
            component = re.split(r"[\[<>=!~]", failure[1], 1)[0].lower().replace("_", "-") if failure else ""
            failures.append({"value": value, "line": line, "stream": stream, "component": component,
                             "code": "build_failure" if build else "no_distribution" if unavailable
                             else "python_requires" if python_mismatch else "", "conflict": conflict})
    # Do not attribute an unscoped compiler message to several failed packages.
    build_names = {f["component"] for f in failures if f["code"] == "build_failure"}
    results = []
    for failure in failures:
        name = failure["component"]
        request = requests.get(name)
        local = details if len(build_names) == 1 and name in build_names else []
        skipped = []
        if failure["code"] == "no_distribution":
            requested = re.search(r"No matching distribution found for ([^\s]+)", failure["value"], re.I)
            try:
                req = Requirement(requested[1])
                skipped = [ref for n, version, ref in sources
                           if n == canonicalize_name(req.name) and version in req.specifier]
            except (InvalidRequirement, TypeError):
                pass
        message = failure["value"]
        if request:
            message += f". Requested requirement: {request[0]}"
        if local:
            message += ". Build detail: " + "; ".join(d[1] for d in local[:3])
        if skipped:
            message += ". The pip log shows a matching source archive was excluded by the wheel-only request."
        item = event(run, message, stage="install",
                     kind="dependency_conflict" if failure["conflict"] else "install_failure",
                     component=name, code=local[0][0] if local else "no_wheel" if skipped else failure["code"],
                     line=failure["line"], stream=failure["stream"])
        item.evidence_refs += ([request[1]] if request else []) + [d[2] for d in local[:3]] + skipped[:3]
        results.append(item)
    return results or [event(run,
        "No recognisable failure in the installation log; this does not prove installation succeeded",
        stage="install", kind="other_unknown")]
