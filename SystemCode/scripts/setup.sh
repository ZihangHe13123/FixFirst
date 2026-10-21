#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON_FOR_FIXFIRST="${1:-python3}"
"$PYTHON_FOR_FIXFIRST" -c 'import sys; assert sys.version_info >= (3,10), "FixFirst requires Python 3.10+"'
"$PYTHON_FOR_FIXFIRST" -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
echo 'Installed. Run .venv/bin/fixfirst serve (web) or .venv/bin/fixfirst interactive (terminal).'
