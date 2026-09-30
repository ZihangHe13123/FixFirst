"""Draw the field-trial notebooks and scripts with a fixed seed (see README.md).

Every candidate is listed with the reason it was excluded, if it was. Exclusions a static scan
cannot see (for example a large download) are checked by hand afterwards and recorded; the next
candidate in the same seeded order then takes its place.

  python experiments/field_trial/sample.py REPOS OUT.json
"""

import ast
import json
from pathlib import Path
import random
import re
import sys

SEED = 20260930
GUI = {"tkinter", "Tkinter", "pygame", "PyQt5", "PyQt6", "PySide2", "PySide6", "turtle", "kivy", "wx", "pyautogui",
       "keyboard", "mouse", "pynput", "easygui", "customtkinter", "pystray", "plyer"}
NETWORK = {"requests", "urllib", "urllib2", "urllib3", "httpx", "aiohttp", "selenium", "tweepy", "smtplib", "socket",
           "pytube", "instaloader", "praw", "telegram", "discord", "googletrans", "wikipedia", "speech_recognition",
           "pyttsx3", "gtts", "yfinance", "pywhatkit", "webbrowser", "ftplib", "imaplib", "poplib", "paramiko",
           "http", "mechanize", "newspaper", "feedparser", "youtube_dl", "yt_dlp", "twilio", "openai", "boto3",
           "pymongo", "psycopg2", "mysql", "redis", "firebase_admin", "gspread", "spotipy", "sounddevice",
           "pyaudio", "cv2"}  # cv2 scripts in these collections mostly open a camera
CREDENTIAL = re.compile(r"api[_-]?key|API_KEY|access[_-]?token|secret|password", re.I)
STDLIB = set(sys.stdlib_module_names)


def imports_of(source: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set(re.findall(r"^\s*(?:from|import)\s+([A-Za-z_]\w*)", source, re.M))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module.split(".")[0])
    return names


def notebook_code(path: Path) -> str:
    cells = json.loads(path.read_text(encoding="utf-8")).get("cells", [])
    lines = []
    for cell in cells:
        if cell.get("cell_type") == "code":
            source = "".join(cell.get("source", []))
            # IPython magics and shell escapes are not Python; keep the rest parseable.
            lines += [line for line in source.splitlines() if not line.lstrip().startswith(("%", "!"))]
    return "\n".join(lines)


def classify(source: str, local: set[str]) -> tuple[set[str], str | None]:
    names = imports_of(source)
    third = {n for n in names if n not in STDLIB and n not in local}
    if not third:
        return third, "no third-party import"
    if names & GUI:
        return third, "GUI or input device: " + ",".join(sorted(names & GUI))
    if names & NETWORK:
        return third, "network, service or camera: " + ",".join(sorted(names & NETWORK))
    if re.search(r"\binput\s*\(", source):
        return third, "interactive input()"
    if CREDENTIAL.search(source):
        return third, "credentials"
    return third, None


def draw(candidates: list[dict], count: int, distinct=None) -> tuple[list[str], list[str]]:
    eligible = sorted(c["path"] for c in candidates if c["excluded"] is None)
    random.Random(f"{SEED}:{len(eligible)}").shuffle(eligible)
    chosen, groups = [], set()
    for path in eligible:
        group = distinct(path) if distinct else path
        if group in groups:
            continue
        chosen.append(path)
        groups.add(group)
        if len(chosen) == count:
            break
    return chosen, eligible


def main() -> None:
    repos, out = Path(sys.argv[1]), Path(sys.argv[2])
    record = {"seed": SEED, "sources": {}}

    def add(name, candidates, count, distinct=None):
        chosen, order = draw(candidates, count, distinct)
        record["sources"][name] = {"candidates": candidates, "seeded_order": order, "chosen": chosen}

    pdsh = repos / "jakevdp_PythonDataScienceHandbook"
    local = {"fig_code", "helpers_05_08"}
    rows = []
    for path in sorted((pdsh / "notebooks").glob("*.ipynb")):
        third, excluded = classify(notebook_code(path), local)
        rows.append({"path": path.relative_to(pdsh).as_posix(), "third_party": sorted(third), "excluded": excluded})
    add("jakevdp/PythonDataScienceHandbook", rows, 2, distinct=lambda p: Path(p).name.split(".")[0])

    imlp = repos / "amueller_introduction_to_ml_with_python"
    rows = []
    for path in sorted(imlp.glob("*.ipynb")):
        third, excluded = classify(notebook_code(path), {"mglearn", "preamble"})
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
        third, excluded = classify(source, {s.stem for s in scripts})
        if excluded is None and not (folder / "requirements.txt").exists():
            excluded = "no requirements.txt"
        rows.append({"path": main_script.relative_to(mini.parent).as_posix(), "third_party": sorted(third),
                     "excluded": excluded})
    add("Python-World/python-mini-projects", rows, 2)

    geek = repos / "geekcomputers_Python"
    rows = []
    for path in sorted(geek.glob("*.py")):
        third, excluded = classify(path.read_text(encoding="utf-8", errors="replace"), {p.stem for p in geek.glob("*.py")})
        rows.append({"path": path.name, "third_party": sorted(third), "excluded": excluded})
    add("geekcomputers/Python", rows, 1)

    out.write_text(json.dumps(record, indent=1) + "\n")
    for name, source in record["sources"].items():
        eligible = sum(1 for c in source["candidates"] if c["excluded"] is None)
        print(f"{name}: {len(source['candidates'])} candidates, {eligible} eligible, chosen {source['chosen']}")
        print(f"   next in seeded order: {source['seeded_order'][len(source['chosen']):len(source['chosen']) + 3]}")


if __name__ == "__main__":
    main()
