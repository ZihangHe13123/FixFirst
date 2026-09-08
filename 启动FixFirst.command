#!/bin/bash
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
  echo "请先按 README.md 安装 Python 3.10+ 并运行 scripts/setup.sh"
  read -r -p "按回车关闭" _answer
  exit 1
fi
.venv/bin/python -m fixfirst interactive
