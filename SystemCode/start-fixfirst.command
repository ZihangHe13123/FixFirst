#!/bin/bash
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "Install Python 3.10+ and run scripts/setup.sh first (see README.md)."
  read -r -p "Press Enter to close" _answer
  exit 1
fi
.venv/bin/python -m fixfirst serve
