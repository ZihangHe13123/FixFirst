"""Find an older release of a library that provides a name, by trying releases.

Rules can only say "an older release probably still has it"; which one depends on release
history FixFirst does not keep. This module finds out: it reads the release list from PyPI,
keeps releases with a prebuilt wheel for the target Python and machine, including earlier
patches of the installed series. It first searches those patches and older series heads by
doubling steps and bisection. If that finds nothing, the remaining budget checks skipped
patches. At most 12 releases are tried in a throwaway environment. A result recommends the
exact verified version; a bounded search need not find the newest working release. Only
wheels are installed (no build scripts run) and the project's environment is never touched.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from .processes import ManagedProcess

PYPI = "https://pypi.org/pypi/{}/json"
MAX_PROBES = 12
CHECK = (
    "import importlib, sys\n"
    "try:\n    m = importlib.import_module(sys.argv[1])\n"
    "except Exception:\n    sys.exit(3)\n"
    "sys.exit(0 if hasattr(m, sys.argv[2]) else 4)\n"
)


def fetch_json(url: str, timeout: float = 20) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (fixed https URL)
        return json.loads(response.read().decode("utf-8"))


def wheel_fits(filename: str, python: Version, markers: dict) -> bool:
    """Whether a wheel file name can install on this interpreter and machine (by its tags)."""
    try:
        python_tags, abi, platforms = filename[:-4].split("-")[-3:]
    except ValueError:
        return False
    here = f"cp{python.major}{python.minor}"
    fits_python = False
    for tag in python_tags.split("."):
        if tag in (here, "py3", f"py{python.major}{python.minor}", "py2.py3"):
            fits_python = True
        elif abi == "abi3" and tag.startswith("cp3") and tag[3:].isdigit() and int(tag[3:]) <= python.minor:
            fits_python = True
    if not fits_python or not (abi in ("none", "abi3") or abi == here):
        return False
    if platforms == "any":
        return True
    system = markers.get("platform_system", "")
    machine = markers.get("platform_machine", "").lower()
    machine = {"amd64": "x86_64", "arm64": "arm64", "aarch64": "aarch64"}.get(machine, machine)
    for platform in platforms.split("."):
        if system == "Darwin" and platform.startswith("macosx") and (
            machine in platform or "universal2" in platform
        ):
            return True
        if system == "Linux" and "linux" in platform and machine in platform:
            return True
        if system == "Windows" and (
            (machine == "x86_64" and platform == "win_amd64") or (machine == "arm64" and platform == "win_arm64")
        ):
            return True
    return False


def series(version: Version) -> str:
    return f"{version.major}.{version.minor}"


def candidates(data: dict, installed: str, python_version: str, markers: dict,
               specifier: str = "") -> list[str]:
    """Every usable release older than the installed version, including earlier patches."""
    python = Version(python_version)
    ceiling = Version(installed)
    allowed = SpecifierSet(specifier)
    found = set()
    for text, files in (data.get("releases") or {}).items():
        try:
            version = Version(text)
        except InvalidVersion:
            continue
        if version.is_prerelease or version.is_devrelease or version >= ceiling or version not in allowed:
            continue
        for item in files:
            if item.get("yanked") or item.get("packagetype") != "bdist_wheel":
                continue
            spec = item.get("requires_python")
            try:
                if spec and python not in SpecifierSet(spec):
                    continue
            except InvalidSpecifier:
                continue
            if wheel_fits(item.get("filename", ""), python, markers):
                found.add(version)
                break
    return [str(v) for v in sorted(found, reverse=True)]


class Sandbox:
    """A throwaway environment built from the target interpreter."""

    def __init__(self, python: str, timeout: float = 180):
        self.folder = Path(tempfile.mkdtemp(prefix="fixfirst-versions-"))
        self.timeout = timeout
        self.base_python = python
        self.last_error = ""
        self.uv = shutil.which("uv")
        self.env_dir = self.folder / "env"
        self.python = str(self.env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
        self._reset()

    def _reset(self):
        # A failed previous candidate must not leave packages in the next trial.
        if self.uv:
            return self._run([self.uv, "venv", "-q", "--clear", "-p", self.base_python, str(self.env_dir)])
        else:
            return self._run([self.base_python, "-m", "venv", "--clear", str(self.env_dir)])

    def _run(self, argv) -> int:
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")}
        try:
            with ManagedProcess(argv, cwd=self.folder, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as done:
                done.wait(timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired):
            return -1
        return done.returncode

    def provides(self, dist: str, version: str, module: str, name: str, *, constraints=()) -> str:
        """'provides', 'missing' (module imports, name absent) or 'failed' (cannot tell)."""
        if self._reset() != 0:
            return "failed"
        constraint_file = self.folder / "constraints.txt"
        constraint_file.write_text("\n".join(constraints) + "\n", encoding="utf-8")
        if self.uv:
            install = [self.uv, "pip", "install", "-q", "--python", self.python, "--only-binary", ":all:",
                       "-c", str(constraint_file), f"{dist}=={version}"]
        else:
            install = [self.python, "-m", "pip", "install", "-q", "--disable-pip-version-check",
                       "--only-binary=:all:", "-c", str(constraint_file), f"{dist}=={version}"]
        if self._run(install) != 0:
            return "failed"
        code = self._run([self.python, "-c", CHECK, module, name])
        return {0: "provides", 4: "missing"}.get(code, "failed")

    def close(self):
        shutil.rmtree(self.folder, ignore_errors=True)


def search(python: str, python_version: str, markers: dict, dist: str, installed: str, api: str,
           fetch=fetch_json, sandbox=Sandbox, *, specifier="", constraints=(), context_fingerprint=None) -> dict:
    """Find a verified release of `dist` providing `api` (module.name) within a trial budget."""
    module, _, name = api.rpartition(".")
    result = {"dist": dist, "api": api, "installed": installed, "python": python_version,
              "checked": [], "provides": None, "below": None, "first_without": None, "status": "not_judged",
              "specifier": specifier, "context_fingerprint": context_fingerprint,
              "constraints": list(constraints)}
    try:
        data = fetch(PYPI.format(dist))
        available = candidates(data, installed, python_version, markers, specifier)
    except (OSError, ValueError) as error:
        return {**result, "status": "offline", "error": str(error)[:300]}
    if not available or not module:
        status = "constraints_exclude_candidates" if specifier and candidates(
            data, installed, python_version, markers) else "no_candidates"
        return {**result, "status": status}
    # Include every patch before the installed release, then the newest of each older
    # series. The remaining patches stay available for a fallback if this search fails.
    current_series = series(Version(installed))
    versions, seen = [], set()
    for release in available:
        family = series(Version(release))
        if family == current_series or family not in seen:
            versions.append(release)
        seen.add(family)
    box = sandbox(python)
    try:
        outcomes = {}

        def check_release(release):
            if release not in outcomes:
                outcome = (box.provides(dist, release, module, name, constraints=constraints) if constraints
                           else box.provides(dist, release, module, name))
                outcomes[release] = outcome
                result["checked"].append({"version": release, "result": outcome})
            return outcomes[release]

        def check(index):
            return check_release(versions[index])

        def found_result(release):
            provided = Version(release)
            newer = [v for v in available if Version(v) > provided]
            same_series = [v for v in [*newer, installed] if series(Version(v)) == series(provided)]
            # Keep the legacy range metadata, but never let it include a newer patch in
            # the same series. Installation advice pins the exact release we tried.
            below = min(same_series, key=Version) if same_series else f"{provided.major}.{provided.minor + 1}"
            without = next((v for v in reversed(newer) if outcomes.get(v) == "missing"), installed)
            result.update(
                provides=release, below=below,
                first_without=without if series(Version(without)) == series(provided) else series(Version(without)),
                status="found" if all(outcomes.get(v) == "missing" for v in newer) else "partial",
            )
            return result

        # Step back 1, 2, 4, 8, ... candidates until one has the name, never past the oldest. A
        # release that cannot be judged (does not install or import) is dropped and the next
        # older one takes its place.
        missing, index, step, found = -1, 0, 1, None
        while len(result["checked"]) < MAX_PROBES and index < len(versions):
            outcome = check(index)
            if outcome == "provides":
                found = index
                break
            if outcome == "missing":
                missing = index
                if index == len(versions) - 1:
                    break  # Other patches may still have a name introduced and later removed.
                index, step = min(index + step, len(versions) - 1), step * 2
            else:
                # A broken old release says nothing about versions skipped by
                # the doubling step. Inspect that nearer gap before spending
                # the budget on still older releases which may all fail import.
                if index > missing + 1:
                    index = missing + 1
                else:
                    versions.pop(index)
        if found is None:
            for release in available:
                if len(result["checked"]) >= MAX_PROBES:
                    break
                if release not in outcomes and check_release(release) == "provides":
                    return found_result(release)
            if len(outcomes) == len(available) and all(v == "missing" for v in outcomes.values()):
                result["status"] = "not_found"
            return result
        # Bisect between the newest series known to lack the name and the one that has it.
        low, high = missing, found
        while high - low > 1 and len(result["checked"]) < MAX_PROBES:
            middle = (low + high) // 2
            outcome = check(middle)
            if outcome == "provides":
                high = middle
            elif outcome == "missing":
                low = middle
            else:
                versions.pop(middle)
                high -= 1
        return found_result(versions[high])
    finally:
        box.close()
