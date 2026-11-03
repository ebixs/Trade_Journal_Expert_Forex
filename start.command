#!/bin/bash
# Starts the journal on macOS. Pass --demo to use sample data.
cd "$(dirname "$0")" || exit 1
PY=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    PY="$candidate"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10 or newer is required. Install it from python.org, then run this again."
  read -r -p "Press Enter to close" _
  exit 1
fi
[ -d .venv ] || "$PY" -m venv .venv || exit 1
.venv/bin/python -m pip install -q -r requirements.txt || echo "Package install failed; trying to start anyway."
.venv/bin/python run.py "$@"
