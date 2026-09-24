#!/bin/bash
# Prepare the real open-source projects used in docs/REAL_PROJECTS.md.
# Usage: bash scripts/setup_real_projects.sh [target-dir] [python]
set -euo pipefail
TARGET="${1:-../test-projects}"
PY="${2:-python3}"
mkdir -p "$TARGET"
cd "$TARGET"

# humanize at a fixed commit: healthy, and a copy without its declared test dependencies.
git clone -q https://github.com/python-humanize/humanize humanize
git -C humanize checkout -q 392aef7
cp -R humanize humanize-missing-deps
export SETUPTOOLS_SCM_PRETEND_VERSION=4.99.0
"$PY" -m venv humanize/.venv
humanize/.venv/bin/python -m pip install -q -e "humanize[tests]"
"$PY" -m venv humanize-missing-deps/.venv
humanize-missing-deps/.venv/bin/python -m pip install -q pytest ruff
humanize-missing-deps/.venv/bin/python -m pip install -q -e humanize-missing-deps --no-deps

# Flask 1.1.4 with today's libraries, installed without its old version caps
# (what an unpinned requirements file produces).
git clone -q --depth 1 --branch 1.1.4 https://github.com/pallets/flask flask-1.1.4
"$PY" -m venv flask-1.1.4/.venv
flask-1.1.4/.venv/bin/python -m pip install -q pytest ruff jinja2 werkzeug itsdangerous click
flask-1.1.4/.venv/bin/python -m pip install -q -e flask-1.1.4 --no-deps
echo "Ready in $TARGET. In FixFirst's start page, choose a folder and its .venv interpreter."
