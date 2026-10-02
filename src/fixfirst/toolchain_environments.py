"""Exact replay identities for the development toolchain generator."""

import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version


def command(argv):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=900)
    if result.returncode:
        raise ValueError(f"Environment preparation failed: {result.stderr[-400:]}")
    return result.stdout.strip()


def interpreter(folder):
    return folder / ("Scripts/python.exe" if platform.system() == "Windows" else "bin/python")


def identity(folder):
    program = (
        "import importlib.metadata as m,json,platform; "
        "print(json.dumps({'python':platform.python_version(),"
        "'implementation':platform.python_implementation(),'system':platform.system(),"
        "'machine':platform.machine(),'packages':sorted("
        "d.metadata['Name'].lower().replace('_','-')+'=='+d.version for d in m.distributions())}))"
    )
    return json.loads(command([str(interpreter(folder)), "-I", "-c", program]))


def read_lock(path, environments, uv):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Unsupported toolchain environment lock")
    if (data.get("system"), data.get("machine"), data.get("uv")) != (
        platform.system(), platform.machine(), command([uv, "--version"])
    ):
        raise ValueError("Toolchain lock OS, architecture or uv version differs")
    entries = data.get("environments")
    if not isinstance(entries, dict) or set(entries) != set(environments):
        raise ValueError("Toolchain lock must contain every declared environment exactly once")
    for key, item in entries.items():
        if not isinstance(item, dict) or set(item) != {"python", "packages"}:
            raise ValueError(f"Invalid environment lock entry: {key}")
        version = item["python"]
        if (not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version)
                or not version.startswith(environments[key].python + ".")):
            raise ValueError(f"Exact Python patch version required: {key}")
        packages = item["packages"]
        if not isinstance(packages, list) or not packages:
            raise ValueError(f"Complete package pins required: {key}")
        pins = {}
        for pin in packages:
            if not isinstance(pin, str):
                raise ValueError(f"Invalid package pin: {key}")
            req = Requirement(pin)
            specs = list(req.specifier)
            if (req.url or req.extras or req.marker or len(specs) != 1
                    or specs[0].operator != "==" or "*" in specs[0].version):
                raise ValueError(f"Exact package pin required: {key}")
            name = canonicalize_name(req.name)
            if name in pins:
                raise ValueError(f"Duplicate package pin: {key}")
            pins[name] = Version(specs[0].version)
        for declared in environments[key].packages:
            req = Requirement(declared)
            if (canonicalize_name(req.name) not in pins
                    or pins[canonicalize_name(req.name)] not in req.specifier):
                raise ValueError(f"Lock contradicts declared environment: {key}")
    return data


class Environments:
    """Create fresh isolated environments; never trust an existing directory."""

    def __init__(self, root, definitions, lock=None):
        self.root, self.definitions = Path(root), definitions
        self.uv = shutil.which("uv")
        if not self.uv:
            raise ValueError("uv is required to build toolchain environments")
        self.lock = read_lock(lock, definitions, self.uv) if lock else None
        self.records = {}
        self.uv_version = command([self.uv, "--version"])

    def build(self, key):
        folder = self.root / key
        if key in self.records:
            if identity(folder) != self.records[key]:
                raise ValueError(f"Environment changed after creation: {key}")
            return folder
        if folder.exists() or folder.is_symlink():
            raise ValueError(f"Refusing an unowned existing environment: {key}")
        definition = self.definitions[key]
        entry = self.lock["environments"][key] if self.lock else None
        python = entry["python"] if entry else definition.python
        # Locked runs start without seed packages; the lock supplies pip too.
        seed = [] if entry else ["--seed"]
        command([self.uv, "venv", "-q", *seed, "--python", python, str(folder)])
        pins = entry["packages"] if entry else list(definition.packages)
        no_deps = ["--no-deps"] if entry else []
        command([self.uv, "pip", "install", "-q", "--python", str(interpreter(folder)), *no_deps, *pins])
        observed = identity(folder)
        if entry:
            expected = {canonicalize_name(Requirement(p).name): str(next(iter(Requirement(p).specifier)).version)
                        for p in pins}
            actual = {canonicalize_name(p.split("==")[0]): p.split("==")[1] for p in observed["packages"]}
            if (observed["python"] != python or observed["implementation"] != "CPython"
                    or actual != expected):
                raise ValueError(f"Installed environment differs from lock: {key}")
        self.records[key] = observed
        return folder

    def export_lock(self):
        return {"schema_version": 1, "system": platform.system(), "machine": platform.machine(),
                "uv": self.uv_version, "environments": {
                    key: {"python": row["python"], "packages": row["packages"]}
                    for key, row in sorted(self.records.items())}}


def source_identity():
    root = Path(__file__).parent
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*"))
            if path.is_file() and (path.suffix == ".py" or path.parent.name == "knowledge")}
