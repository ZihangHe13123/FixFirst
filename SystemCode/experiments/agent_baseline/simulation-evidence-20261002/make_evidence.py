"""Re-run the eleven simulation settings of the B7 analysis, before and after the 2026-10-02 fixes, and
record what was run: each setting's parameters and seed, the exact command (relative to the repository
root), the code commit and its files' SHA-256, and every output's SHA-256.

    python make_evidence.py PYTHON BEFORE_F_CHECKOUT BEFORE_AG_CHECKOUT AFTER_CHECKOUT

Each checkout is a clean git checkout of the commit named below; the script refuses one that is at
another commit or has uncommitted changes. Outputs go next to this file: before/ and after/. It reads
no results of any experiment; everything is synthetic.
"""
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = "experiments/agent_baseline/task_analysis.py"
CODE = ("experiments/agent_baseline/task_analysis.py", "experiments/agent_baseline/compare_arms.py")
SEED, REPLICATES, RESAMPLES = 20261001, 2000, 1000
EFFECTS_F = ("0", "0.1", "0.2", "0.3", "0.4")

# id: (description, tasks, runs per arm, baseline, effect model, correlation, effects)
SETTINGS = {
    "F8x3": ("8 tasks x 3 runs, baselines uniform 0.1-0.9", 8, 3, (0.1, 0.9), "shift", 0.0, EFFECTS_F),
    "F6x3": ("6 tasks x 3 runs, baselines uniform 0.1-0.9", 6, 3, (0.1, 0.9), "shift", 0.0, EFFECTS_F),
    "F8x3c": ("8 tasks x 3 runs, baselines uniform 0.6-1.0 (ceiling)", 8, 3, (0.6, 1.0), "shift", 0.0, EFFECTS_F),
    "F8x5": ("8 tasks x 5 runs, baselines uniform 0.1-0.9", 8, 5, (0.1, 0.9), "shift", 0.0, EFFECTS_F),
    "A": ("base: uniform 0.1-0.9, the same gain on every task", 8, 3, "uniform:0.1:0.9", "shift", 0.0, ("0", "0.2", "0.3")),
    "B": ("baselines near 0 or 1: beta(0.5, 0.5)", 8, 3, "beta:0.5:0.5", "shift", 0.0, ("0", "0.2", "0.3")),
    "C": ("weak models: uniform 0-0.3", 8, 3, "uniform:0:0.3", "shift", 0.0, ("0", "0.2", "0.3")),
    "D": ("only half the tasks helped (twice the gain)", 8, 3, "uniform:0.1:0.9", "half", 0.0, ("0", "0.1", "0.15")),
    "E": ("help as a share of the remaining failures", 8, 3, "uniform:0.1:0.9", "share", 0.0, ("0", "0.4", "0.6")),
    "F": ("a task's runs repeat one draw with chance 0.7", 8, 3, "uniform:0.1:0.9", "shift", 0.7, ("0", "0.2", "0.3")),
    "G": ("B, D and F together", 8, 3, "beta:0.5:0.5", "half", 0.7, ("0", "0.1", "0.15")),
}
BEFORE_F, BEFORE_AG, AFTER = "bedb38b", "304f9dc", "7914699"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(checkout: Path, *args) -> str:
    return subprocess.run(["git", "-C", str(checkout), *args], capture_output=True, text=True, check=True).stdout.strip()


def check(checkout: Path, commit: str) -> dict:
    head = git(checkout, "rev-parse", "HEAD")
    evidence = f":(exclude)experiments/agent_baseline/{HERE.name}"  # this folder, written by this script
    if not head.startswith(commit) or git(checkout, "status", "--porcelain", "--", "experiments", "src", evidence):
        raise SystemExit(f"{checkout.name}: not a clean checkout of {commit}")
    return {"commit": head, "files_sha256": {path: sha256((checkout / path).read_bytes()) for path in CODE}}


def arguments(key: str, era: str) -> list[str]:
    description, tasks, runs, baseline, model, correlation, effects = SETTINGS[key]
    args = ["--simulate", "--tasks", str(tasks), "--runs", str(runs), "--replicates", str(REPLICATES),
            "--resamples", str(RESAMPLES), "--seed", str(SEED), "--effects", *effects]
    if era == BEFORE_F:  # bedb38b knew only uniform baselines, as --baseline-range LOW HIGH
        return args + ["--baseline-range", str(baseline[0]), str(baseline[1])]
    spec = baseline if isinstance(baseline, str) else f"uniform:{baseline[0]}:{baseline[1]}"
    args += ["--baseline", spec, "--effect-model", model]
    return args + (["--correlation", str(correlation)] if correlation else [])


def run(python: str, checkout: Path, key: str, era: str, folder: str) -> dict:
    target = HERE / folder / f"{key}.json"
    target.parent.mkdir(exist_ok=True)
    args = arguments(key, era)
    subprocess.run([python, SCRIPT, *args, "--json", str(target)], cwd=checkout, check=True, capture_output=True)
    relative = f"experiments/agent_baseline/{HERE.name}/{folder}/{key}.json"
    return {"output": relative, "sha256": sha256(target.read_bytes()),
            "command": " ".join(["python", SCRIPT, *args, "--json", relative])}


def main():
    python, before_f, before_ag, after = sys.argv[1], *(Path(p).resolve() for p in sys.argv[2:5])
    code = {BEFORE_F: check(before_f, BEFORE_F), BEFORE_AG: check(before_ag, BEFORE_AG), AFTER: check(after, AFTER)}
    version = subprocess.run([python, "--version"], capture_output=True, text=True).stdout.strip()
    settings = {}
    for key, (description, tasks, runs, baseline, model, correlation, effects) in SETTINGS.items():
        era = BEFORE_F if key.startswith("F") and len(key) > 1 else BEFORE_AG
        settings[key] = {
            "description": description, "tasks": tasks, "runs_per_arm": runs,
            "baseline": baseline if isinstance(baseline, str) else f"uniform:{baseline[0]}:{baseline[1]}",
            "effect_model": model, "correlation": correlation, "effects": [float(e) for e in effects],
            "replicates": REPLICATES, "bootstrap_resamples": RESAMPLES, "seed": SEED,
            "before": {"code": era, **run(python, before_f if era == BEFORE_F else before_ag, key, era, "before")},
            "after": {"code": AFTER, **run(python, after, key, AFTER, "after")},
        }
    manifest = {
        "what": "the eleven simulation settings of the B7 task-level analysis, before and after the 2026-10-02 fixes",
        "python": version, "platform": platform.platform(terse=True),
        "random_streams": {"tasks_and_runs": "random.Random(seed)", "task_population_for_the_truth": "random.Random(seed + 1), "
                           "200000 draws", "half_model_coins_for_the_truth": "random.Random(seed + 2)",
                           "bootstrap": "random.Random(f'{seed}|{effect}|{replicate}|sim|server|{protocol id}|real|baseline|mcp'), "
                                        "the same string in all three commits"},
        "code": code, "settings": settings,
    }
    (HERE / "MANIFEST.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: (v["before"]["sha256"][:12], v["after"]["sha256"][:12]) for k, v in settings.items()}, indent=1))


if __name__ == "__main__":
    main()
