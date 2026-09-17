#!/usr/bin/env bash
# Convenience launcher for Linux/macOS.
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c "import PySide6" >/dev/null 2>&1; then
  .venv/bin/pip install -q -r requirements.txt
fi
exec .venv/bin/python main.py "$@"
