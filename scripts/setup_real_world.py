"""Prepare the held-out real-world projects listed in examples/real-world/projects.toml.

Usage: python scripts/setup_real_world.py [target-dir] [--only ID ...]

Clones each project at its tag, creates its environment and installs it the way the manifest
describes. Uses uv when it is available (fast, and it provides the listed Python versions);
otherwise `python -m venv` and pip with the current interpreter's version. The installed
package list is saved next to the manifest so that results can be reproduced.
"""

import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

HERE = Path(__file__).resolve().parent.parent / "examples" / "real-world"


def run(argv, cwd=None, env=None):
    print("  $", " ".join(str(a) for a in argv), flush=True)
    return subprocess.run([str(a) for a in argv], cwd=cwd, env=env, check=False)


def venv_python(folder: Path) -> Path:
    return folder / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", nargs="?", default="../test-projects/generalisation")
    parser.add_argument("--only", nargs="*", default=[])
    args = parser.parse_args()
    target = Path(args.target).resolve()
    target.mkdir(parents=True, exist_ok=True)
    uv = shutil.which("uv")
    projects = tomllib.loads((HERE / "projects.toml").read_text("utf-8"))["project"]
    (HERE / "environments").mkdir(exist_ok=True)
    failed = []
    for project in projects:
        if args.only and project["id"] not in args.only:
            continue
        print(f"== {project['id']} ({project['repo']} {project['ref']})", flush=True)
        folder = target / project["id"]
        if not folder.exists():
            run(["git", "clone", "-q", "--depth", "1", "--branch", project["ref"],
                 f"https://github.com/{project['repo']}", folder])
        env_dir = folder / ".venv"
        if env_dir.exists():
            shutil.rmtree(env_dir)
        with_pip = project.get("pip", True)
        if uv:
            version = "/usr/bin/python3" if project["python"] == "system" else project["python"]
            run([uv, "venv", "-q", *(["--seed"] if with_pip else []), "-p", version, env_dir])
        else:
            base = "/usr/bin/python3" if project["python"] == "system" and os.name != "nt" else sys.executable
            run([base, "-m", "venv", *([] if with_pip else ["--without-pip"]), env_dir])
        python = venv_python(env_dir)
        env = {**os.environ, "SETUPTOOLS_SCM_PRETEND_VERSION": project["ref"].lstrip("v")}
        for line in project["install"]:
            if uv:
                argv = [uv, "pip", "install", "-q", "--python", python, *shlex.split(line)]
            else:
                argv = [python, "-m", "pip", "install", "-q", *shlex.split(line)]
            if run(argv, cwd=folder, env=env).returncode != 0:
                failed.append(f"{project['id']}: pip install {line}")
        freeze = [uv, "pip", "freeze", "--python", python] if uv else [python, "-m", "pip", "freeze"]
        listing = subprocess.run([str(a) for a in freeze], capture_output=True, text=True, check=False)
        version = subprocess.run([str(python), "-c", "import sys; print(sys.version.split()[0])"],
                                 capture_output=True, text=True, check=False).stdout.strip()
        lines = [line for line in listing.stdout.splitlines() if not line.startswith("-e ")]
        (HERE / "environments" / f"{project['id']}.txt").write_text(
            f"# Python {version}\n" + "\n".join(lines) + "\n", encoding="utf-8"
        )
    if failed:
        print("\nSome installs failed (recorded as part of the scenario):", *failed, sep="\n  ")
    print(f"\nReady in {target}. Each project has its interpreter in .venv.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
