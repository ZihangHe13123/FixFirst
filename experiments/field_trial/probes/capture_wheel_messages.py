"""Capture real `uv pip install --only-binary=:all:` failures the way FixFirst's trial runs them.

  python probes/capture_wheel_messages.py OUT.json CASES.json PYTHON3.12

Same argv shape as dependency_resolution.collect (uv venv --no-config, uv pip install --no-config
--only-binary=:all: -r requirements.txt -c constraints.txt), same child setup as runner.execute
(env copy + NO_COLOR, stdin DEVNULL, new session, piped output). Optional COLUMNS per run.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

out = Path(sys.argv[1])
cases = json.loads(Path(sys.argv[2]).read_text())
uv = shutil.which("uv")
py = sys.argv[3]
records = []
for case in cases:
    with tempfile.TemporaryDirectory(dir=out.parent) as tmp:
        env = os.environ.copy()
        env.update({"NO_COLOR": "1", "PYTHONUNBUFFERED": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                    "PYTHONIOENCODING": "utf-8", "PYTHONPATH": "", "PIP_CONFIG_FILE": os.devnull})
        env.pop("COLUMNS", None)
        if case.get("columns"):
            env["COLUMNS"] = str(case["columns"])
        venv = Path(tmp) / "env"
        subprocess.run([uv, "venv", "-q", "--no-config", "--no-python-downloads", "--python", py, str(venv)],
                       check=True, stdin=subprocess.DEVNULL, capture_output=True)
        (Path(tmp) / "requirements.txt").write_text("\n".join(case["requests"]) + "\n")
        (Path(tmp) / "constraints.txt").write_text("\n")
        argv = [uv, "pip", "install", "--no-config", "--python", str(venv / "bin" / "python"),
                "--only-binary=:all:", "-r", str(Path(tmp) / "requirements.txt"), "-c", str(Path(tmp) / "constraints.txt")]
        p = subprocess.run(argv, cwd=tmp, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, start_new_session=True, timeout=300)
        text = (p.stdout + p.stderr).replace(tmp, "<tmp>")
        records.append({**case, "exit_code": p.returncode, "output": text})
        print(f"--- {case['requests']} COLUMNS={case.get('columns')} exit={p.returncode}")
        print(text)
out.write_text(json.dumps(records, indent=1, ensure_ascii=False) + "\n")
