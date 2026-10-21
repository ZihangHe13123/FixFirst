"""Simulate the registered confirmatory family (three models, Holm at 0.05) with commit c464214 and record
what was run: each setting's parameters and seed, the exact command (relative to the repository root), the
code's commit and its files' SHA-256, and every output's SHA-256.

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
COMMIT = "c464214e860fd536a1286ebbf57e20516dd93d79"
SCRIPT = "experiments/agent_baseline/task_analysis.py"
CODE = ("experiments/agent_baseline/task_analysis.py", "experiments/agent_baseline/compare_arms.py")
SEED, REPLICATES = 20261001, 2000
ALPHA = 0.05  # the registered level of the family; task_analysis.py has no option to change it
RUNS = ("5", "5", "3")  # runs per arm of the three models, as decided on 2 Oct: two fast models, one slow one
WIDE, NONE = "uniform:0.1:0.9", ("0", "0", "0")

# id: (description, effects per model, tasks, baseline, effect model, correlation, every model meets the same tasks)
SETTINGS = {
    "null": ("no effect in any model; baselines uniform 0.1-0.9", NONE, 8, WIDE, "shift", 0.0, True),
    "null-ceiling": ("no effect; baselines uniform 0.6-1.0", NONE, 8, "uniform:0.6:1.0", "shift", 0.0, True),
    "null-ends": ("no effect; baselines near 0 or 1, beta(0.5, 0.5)", NONE, 8, "beta:0.5:0.5", "shift", 0.0, True),
    "null-repeats": ("no effect; a task's runs repeat one draw with chance 0.7", NONE, 8, WIDE, "shift", 0.7, True),
    "null-own-tasks": ("no effect; each model draws its own tasks", NONE, 8, WIDE, "shift", 0.0, False),
    "null-6-tasks": ("no effect; six tasks", NONE, 6, WIDE, "shift", 0.0, True),
    "all-0.2": ("every model gains 0.2 on every task", ("0.2", "0.2", "0.2"), 8, WIDE, "shift", 0.0, True),
    "all-0.3": ("every model gains 0.3 on every task", ("0.3", "0.3", "0.3"), 8, WIDE, "shift", 0.0, True),
    "all-0.3-repeats": ("every model gains 0.3; runs repeat with chance 0.7", ("0.3", "0.3", "0.3"), 8, WIDE, "shift", 0.7, True),
    "all-half": ("every model gains 0.3 on half its tasks, nothing on the rest", ("0.15", "0.15", "0.15"), 8, WIDE, "half", 0.0, True),
    "first-0.3": ("only the first model (5 runs) gains 0.3", ("0.3", "0", "0"), 8, WIDE, "shift", 0.0, True),
    "two-0.3": ("the two 5-run models gain 0.3, the 3-run model nothing", ("0.3", "0.3", "0"), 8, WIDE, "shift", 0.0, True),
    "last-0.3": ("only the 3-run model gains 0.3", ("0", "0", "0.3"), 8, WIDE, "shift", 0.0, True),
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
    for key, (description, effects, tasks, baseline, model, correlation, shared) in SETTINGS.items():
        relative = f"experiments/agent_baseline/{HERE.name}/results/{key}.json"
        args = ["--simulate", "--family-runs", *RUNS, "--tasks", str(tasks), "--replicates", str(REPLICATES),
                "--seed", str(SEED), "--effects", *effects, "--baseline", baseline, "--effect-model", model,
                *(["--correlation", str(correlation)] if correlation else []), *([] if shared else ["--independent-tasks"])]
        subprocess.run([python, SCRIPT, *args, "--json", str(HERE / "results" / f"{key}.json")], cwd=checkout,
                       check=True, capture_output=True)
        settings[key] = {"description": description, "runs_per_model": [int(n) for n in RUNS],
                         "effects": [float(e) for e in effects], "tasks": tasks, "baseline": baseline,
                         "effect_model": model, "correlation": correlation, "shared_tasks": shared,
                         "replicates": REPLICATES, "seed": SEED, "alpha": ALPHA,
                         "command": " ".join(["python", SCRIPT, *args, "--json", relative]), "output": relative,
                         "sha256": sha256((HERE / "results" / f"{key}.json").read_bytes())}
    manifest = {"what": "the registered confirmatory family (three models, Holm at 0.05), simulated with c464214",
                "python": subprocess.run([python, "--version"], capture_output=True, text=True).stdout.strip(),
                "platform": platform.platform(terse=True), "code": code, "settings": settings}
    (HERE / "MANIFEST.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({key: value["sha256"][:12] for key, value in settings.items()}, indent=1))


if __name__ == "__main__":
    main()
