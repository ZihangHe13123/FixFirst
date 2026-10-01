"""365aa84's counterexample run on both builds, plus two harmless-orphan neighbours (offline wheels, real uv).

  FF_TESTS=<checkout>/tests FF_OUT=out.jsonl <build venv>/bin/python -m pytest -q -p no:cacheprovider probes/test_orphans.py

Uses only collect() and the checkout's own fixtures, so the same file runs on 27afb06 and 365aa84.
The tests record results and assert nothing; the expectations are in each docstring.
"""
import io
import json
import os
import tarfile

from fixfirst.dependency_resolution import collect
from test_dependency_resolution import fixture_session, wheel


def sdist(folder, name, version):
    base = f"{name.replace('-', '_')}-{version}"
    data = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n".encode()
    with tarfile.open(folder / f"{base}.tar.gz", "w:gz") as tar:
        info = tarfile.TarInfo(f"{base}/PKG-INFO")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))


def setup(tmp_path, offline_resolver, obsolete_requires, obsolete_wheel=True, obsolete_versions=("1.0",),
          helper_installed=True):
    session, _ = fixture_session(tmp_path / "project", "ff-trial-base==1.0\nff-trial-ext\n")
    session.environment["packages"][0]["requires"] = ["ff-trial-obsolete"]
    session.environment["packages"].append(
        {"name": "ff-trial-obsolete", "version": "1.0", "requires": list(obsolete_requires)})
    if helper_installed:
        session.environment["packages"].append({"name": "ff-trial-helper", "version": "1.0", "requires": []})
    wheels = offline_resolver[2]
    for version in ("1.0", "2.0"):
        wheel(wheels, "ff-trial-helper", version)
    for version in obsolete_versions:
        if obsolete_wheel:
            wheel(wheels, "ff-trial-obsolete", version, list(obsolete_requires))
        else:
            sdist(wheels, "ff-trial-obsolete", version)
    wheel(wheels, "ff-trial-base", "2.0", ["ff-trial-helper>=2"])
    result = json.loads(collect(session, ["ff-trial-base", ">1.0"], 20).stdout)
    with open(os.environ["FF_OUT"], "a") as fh:
        fh.write(json.dumps({"case": os.environ.get("PYTEST_CURRENT_TEST", "").split("::")[-1].split(" ")[0],
                             "status": result["status"], "blocked": result.get("blocked_requirement"),
                             "install_requests": result.get("install_requests"), "error": result.get("error"), "requests": result.get("requests"), "last": (result["checks"][-1]["output"][-600:] if result.get("checks") else None)}) + "\n")
    return result


def test_codex_counterexample(tmp_path, offline_resolver):
    """Codex: base1 -> obsolete1 -> helper<2, base2 -> helper>=2. Expected: not_resolved."""
    setup(tmp_path, offline_resolver, ["ff-trial-helper<2"])


def test_harmless_orphan_with_wheel(tmp_path, offline_resolver):
    """obsolete1 needs nothing and helper is new: the in-place install stays consistent. Expected: resolved."""
    setup(tmp_path, offline_resolver, [], obsolete_versions=("1.0", "2.0"), helper_installed=False)


def test_harmless_orphan_sdist_only(tmp_path, offline_resolver):
    """Same harmless orphan, but it was built from an sdist (no wheel exists)."""
    setup(tmp_path, offline_resolver, [], obsolete_wheel=False, helper_installed=False)
