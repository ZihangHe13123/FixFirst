"""Find the newest release of a library that still provides a name, by trying releases.

Rules can only say "an older release probably still has it"; which one depends on release
history FixFirst does not keep. This module finds out: it reads the release list from PyPI,
keeps the newest release of each release series (1.4.x, 1.5.x, ...) that has a prebuilt wheel
for the target Python and machine, and checks series in a throwaway environment: stepping back
1, 2, 4, 8 series from the installed one, then bisecting. Removals are usually a few series
back, so the search rarely depends on very old releases, which often no longer import next to
today's dependencies. Only wheels are installed (no build scripts run) and the project's own
environment is never touched.
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


def candidates(data: dict, installed: str, python_version: str, markers: dict) -> list[str]:
    """The newest usable release of each series older than the installed one, newest first."""
    python = Version(python_version)
    ceiling = Version(series(Version(installed)))
    found = []
    for text, files in (data.get("releases") or {}).items():
        try:
            version = Version(text)
        except InvalidVersion:
            continue
        if version.is_prerelease or version.is_devrelease or version >= ceiling:
            continue
        for item in files:
            if item.get("yanked") or item.get("packagetype") != "bdist_wheel":
                continue
            spec = item.get("requires_python")
            try:
                if spec and python not in SpecifierSet(spec):
                    continue
            except InvalidSpecifier:
                pass
            if wheel_fits(item.get("filename", ""), python, markers):
                found.append(version)
                break
    newest = {}
    for version in found:
        key = series(version)
        if key not in newest or version > newest[key]:
            newest[key] = version
    return [str(v) for v in sorted(newest.values(), reverse=True)]


class Sandbox:
    """A throwaway environment built from the target interpreter."""

    def __init__(self, python: str, timeout: float = 180):
        self.folder = Path(tempfile.mkdtemp(prefix="fixfirst-versions-"))
        self.timeout = timeout
        self.uv = shutil.which("uv")
        env_dir = self.folder / "env"
        if self.uv:
            self._run([self.uv, "venv", "-q", "-p", python, str(env_dir)])
        else:
            self._run([python, "-m", "venv", str(env_dir)])
        self.python = str(env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))

    def _run(self, argv) -> int:
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")}
        try:
            done = subprocess.run(argv, cwd=self.folder, env=env, capture_output=True, timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired):
            return -1
        return done.returncode

    def provides(self, dist: str, version: str, module: str, name: str) -> str:
        """'provides', 'missing' (module imports, name absent) or 'failed' (cannot tell)."""
        if self.uv:
            install = [self.uv, "pip", "install", "-q", "--python", self.python, "--only-binary", ":all:",
                       f"{dist}=={version}"]
        else:
            install = [self.python, "-m", "pip", "install", "-q", "--disable-pip-version-check",
                       "--only-binary=:all:", f"{dist}=={version}"]
        if self._run(install) != 0:
            return "failed"
        code = self._run([self.python, "-c", CHECK, module, name])
        return {0: "provides", 4: "missing"}.get(code, "failed")

    def close(self):
        shutil.rmtree(self.folder, ignore_errors=True)


def search(python: str, python_version: str, markers: dict, dist: str, installed: str, api: str,
           fetch=fetch_json, sandbox=Sandbox) -> dict:
    """The newest release of `dist` that still provides `api` (module.name), by trying releases."""
    module, _, name = api.rpartition(".")
    result = {"dist": dist, "api": api, "installed": installed, "python": python_version,
              "checked": [], "provides": None, "below": None, "first_without": None, "status": "not_found"}
    try:
        versions = candidates(fetch(PYPI.format(dist)), installed, python_version, markers)
    except (OSError, ValueError) as error:
        return {**result, "status": "offline", "error": str(error)[:300]}
    if not versions or not module:
        return {**result, "status": "no_candidates"}
    box = sandbox(python)
    try:
        def check(index):
            outcome = box.provides(dist, versions[index], module, name)
            result["checked"].append({"version": versions[index], "result": outcome})
            return outcome

        # Step back 1, 2, 4, 8, ... series until one has the name, never past the oldest. A
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
                    return result  # even the oldest usable series lacks it
                index, step = min(index + step, len(versions) - 1), step * 2
            else:
                versions.pop(index)
        if found is None:
            result["status"] = "not_judged"
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
        provides = Version(versions[high])
        # Installing below the next series always picks the verified release (or a newer patch
        # of it), even if a series in between could not be judged here.
        result.update(provides=versions[high], below=f"{provides.major}.{provides.minor + 1}",
                      first_without=series(Version(versions[low])) if low >= 0 else series(Version(installed)),
                      status="found" if high - low == 1 else "partial")
        return result
    finally:
        box.close()
