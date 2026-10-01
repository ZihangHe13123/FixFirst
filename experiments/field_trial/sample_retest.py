"""Draw the round-6 retest tasks (RETEST.md): seed from the final production commit, seen tasks excluded.

  python experiments/field_trial/sample_retest.py REPOS COMMIT OUT.json

REPOS holds fresh clones of the sources (default branches), named owner_repo as in the first batch;
COMMIT is the final production commit (its first 8 hex digits give the seed). The output keeps every
candidate, the automatic exclusion reasons and the full seeded order; manual exclusions are added
by hand afterwards with the next candidate in the same order taking the place.
"""

import json
from pathlib import Path
import random
import sys

import sample  # the first batch's candidate rules (sample.py beside this file)

SEEN = {
    "jakevdp/PythonDataScienceHandbook": {"notebooks/01.07-Timing-and-Profiling.ipynb",
                                          "notebooks/05.12-Gaussian-Mixtures.ipynb"},
    "amueller/introduction_to_ml_with_python": {"07-working-with-text-data.ipynb"},
    "Python-World/python-mini-projects": {"projects/Diff_Util/diff.py", "projects/Split_File/split_files.py",
                                          "projects/Web_page_summation/app.py"},
    "geekcomputers/Python": {"Polyline.py", "fastapi.py", "Guess_the_number_game.py", "blackJackGUI.py",
                             "serial_scanner.py", "ReadFromCSV.py", "NumPy Array Exponentiation.py"},
}
APPS = ["miguelgrinberg/flasky", "miguelgrinberg/microblog-2018", "mdn/django-locallibrary-tutorial",
        "mjhea0/flaskr-tdd", "wsvincent/djangox"]


def draw(rows: list[dict], count: int, seed: int, distinct=None):
    eligible = sorted(r["path"] for r in rows if r["excluded"] is None)
    order = eligible[:]
    random.Random(f"{seed}:{len(order)}").shuffle(order)
    chosen, groups = [], set()
    for path in order:
        group = distinct(path) if distinct else path
        if group not in groups:
            chosen.append(path)
            groups.add(group)
        if len(chosen) == count:
            break
    return chosen, order


def main() -> None:
    repos, commit, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    seed = int(commit[:8], 16)
    record = {"commit": commit, "seed": seed, "sources": {}}

    def add(name, rows, count, distinct=None):
        for row in rows:
            if row["excluded"] is None and row["path"] in SEEN.get(name, ()):
                row["excluded"] = "seen in the first batch"
        chosen, order = draw(rows, count, seed, distinct)
        record["sources"][name] = {"candidates": rows, "seeded_order": order, "chosen": chosen}

    pdsh = repos / "jakevdp_PythonDataScienceHandbook"
    rows = []
    for path in sorted((pdsh / "notebooks").glob("*.ipynb")):
        third, excluded = sample.classify(sample.notebook_code(path), {"fig_code", "helpers_05_08"})
        rows.append({"path": path.relative_to(pdsh).as_posix(), "third_party": sorted(third), "excluded": excluded})
    add("jakevdp/PythonDataScienceHandbook", rows, 2, distinct=lambda p: Path(p).name.split(".")[0])

    imlp = repos / "amueller_introduction_to_ml_with_python"
    rows = []
    for path in sorted(imlp.glob("*.ipynb")):
        third, excluded = sample.classify(sample.notebook_code(path), {"mglearn", "preamble"})
        rows.append({"path": path.name, "third_party": sorted(third), "excluded": excluded})
    add("amueller/introduction_to_ml_with_python", rows, 1)

    mini = repos / "Python-World_python-mini-projects" / "projects"
    rows = []
    for folder in sorted(p for p in mini.iterdir() if p.is_dir()):
        scripts = sorted(folder.glob("*.py"))
        if not scripts:
            continue
        main_script = next((s for s in scripts if s.stem.lower() in ("main", folder.name.lower())), scripts[0])
        source = "\n".join(s.read_text(encoding="utf-8", errors="replace") for s in scripts)
        third, excluded = sample.classify(source, {s.stem for s in scripts})
        if excluded is None and not (folder / "requirements.txt").exists():
            excluded = "no requirements.txt"
        rows.append({"path": main_script.relative_to(mini.parent).as_posix(), "third_party": sorted(third),
                     "excluded": excluded})
    add("Python-World/python-mini-projects", rows, 2)

    geek = repos / "geekcomputers_Python"
    rows = []
    for path in sorted(geek.glob("*.py")):
        third, excluded = sample.classify(path.read_text(encoding="utf-8", errors="replace"),
                                          {p.stem for p in geek.glob("*.py")})
        rows.append({"path": path.name, "third_party": sorted(third), "excluded": excluded})
    add("geekcomputers/Python", rows, 1)

    apps = [{"path": name, "third_party": [], "excluded": None} for name in APPS]
    add("tutorial apps", apps, 3)

    out.write_text(json.dumps(record, indent=1) + "\n")
    for name, source in record["sources"].items():
        print(f"{name}: chosen {source['chosen']}")


if __name__ == "__main__":
    main()
