"""Run the eleven simulation settings of the B7 analysis with commit e9f5b90 and record what was run: each
setting's parameters and seed, the exact command (relative to the repository root), the code's commit
and its files' SHA-256, and every output's SHA-256.

    python make_evidence.py PYTHON CHECKOUT

CHECKOUT must be a git checkout whose HEAD is exactly COMMIT below, with no uncommitted change anywhere in
its working tree except this folder (tracked or untracked). The interpreter's version is recorded, not
enforced. Outputs go to results/ next to this file and are overwritten. Synthetic only: no experiment's
results are read.
"""
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMMIT = "e9f5b9034554965606ffbba810ae20301305bb8f"
SCRIPT = "experiments/agent_baseline/task_analysis.py"
CODE = ("experiments/agent_baseline/task_analysis.py", "experiments/agent_baseline/compare_arms.py")
SEED, REPLICATES, RESAMPLES = 20261001, 2000, 1000
EFFECTS_F = ("0", "0.1", "0.2", "0.3", "0.4")

# id: (description, tasks, runs per arm, baseline, effect model, correlation, effects); the same eleven
# settings, in the same order and with the same effect lists, as simulation-evidence-20261002/
SETTINGS = {
    "F8x3": ("8 tasks x 3 runs, baselines uniform 0.1-0.9", 8, 3, "uniform:0.1:0.9", "shift", 0.0, EFFECTS_F),
    "F6x3": ("6 tasks x 3 runs, baselines uniform 0.1-0.9", 6, 3, "uniform:0.1:0.9", "shift", 0.0, EFFECTS_F),
    "F8x3c": ("8 tasks x 3 runs, baselines uniform 0.6-1.0 (ceiling)", 8, 3, "uniform:0.6:1.0", "shift", 0.0, EFFECTS_F),
    "F8x5": ("8 tasks x 5 runs, baselines uniform 0.1-0.9", 8, 5, "uniform:0.1:0.9", "shift", 0.0, EFFECTS_F),
    "A": ("base: uniform 0.1-0.9, the same gain on every task", 8, 3, "uniform:0.1:0.9", "shift", 0.0, ("0", "0.2", "0.3")),
    "B": ("baselines near 0 or 1: beta(0.5, 0.5)", 8, 3, "beta:0.5:0.5", "shift", 0.0, ("0", "0.2", "0.3")),
    "C": ("weak models: uniform 0-0.3", 8, 3, "uniform:0:0.3", "shift", 0.0, ("0", "0.2", "0.3")),
    "D": ("only half the tasks helped (twice the gain)", 8, 3, "uniform:0.1:0.9", "half", 0.0, ("0", "0.1", "0.15")),
    "E": ("help as a share of the remaining failures", 8, 3, "uniform:0.1:0.9", "share", 0.0, ("0", "0.4", "0.6")),
    "F": ("a task's runs repeat one draw with chance 0.7", 8, 3, "uniform:0.1:0.9", "shift", 0.7, ("0", "0.2", "0.3")),
    "G": ("B, D and F together", 8, 3, "beta:0.5:0.5", "half", 0.7, ("0", "0.1", "0.15")),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(checkout: Path, *args) -> str:
    return subprocess.run(["git", "-C", str(checkout), *args], capture_output=True, text=True, check=True).stdout.strip()


def check(checkout: Path) -> dict:
    head = git(checkout, "rev-parse", "HEAD")
    folder = HERE.relative_to(Path(git(HERE, "rev-parse", "--show-toplevel"))).as_posix()
    changes = git(checkout, "status", "--porcelain", "--untracked-files=all", "--", ".", f":(exclude){folder}")
    if head != COMMIT or changes:
        raise SystemExit(f"not a clean checkout of {COMMIT}: HEAD {head}; changes: {changes[:300]!r}")
    return {"commit": head, "files_sha256": {path: sha256((checkout / path).read_bytes()) for path in CODE}}


def main():
    python, checkout = sys.argv[1], Path(sys.argv[2]).resolve()
    code = check(checkout)
    (HERE / "results").mkdir(exist_ok=True)
    settings = {}
    for key, (description, tasks, runs, baseline, model, correlation, effects) in SETTINGS.items():
        relative = f"experiments/agent_baseline/{HERE.name}/results/{key}.json"
        args = ["--simulate", "--tasks", str(tasks), "--runs", str(runs), "--replicates", str(REPLICATES),
                "--resamples", str(RESAMPLES), "--seed", str(SEED), "--effects", *effects, "--baseline", baseline,
                "--effect-model", model, *(["--correlation", str(correlation)] if correlation else [])]
        subprocess.run([python, SCRIPT, *args, "--json", str(HERE / "results" / f"{key}.json")], cwd=checkout,
                       check=True, capture_output=True)
        settings[key] = {"description": description, "tasks": tasks, "runs_per_arm": runs, "baseline": baseline,
                         "effect_model": model, "correlation": correlation, "effects": [float(e) for e in effects],
                         "replicates": REPLICATES, "bootstrap_resamples": RESAMPLES, "seed": SEED,
                         "command": " ".join(["python", SCRIPT, *args, "--json", relative]), "output": relative,
                         "sha256": sha256((HERE / "results" / f"{key}.json").read_bytes())}
    manifest = {"what": "the eleven simulation settings of the B7 analysis, run with e9f5b90",
                "python": subprocess.run([python, "--version"], capture_output=True, text=True).stdout.strip(),
                "platform": platform.platform(terse=True), "code": code, "settings": settings}
    (HERE / "MANIFEST.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({key: value["sha256"][:12] for key, value in settings.items()}, indent=1))


if __name__ == "__main__":
    main()
