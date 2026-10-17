#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${1:-python3}"

if [[ "$(uname -s)" != "Darwin" ]]; then
    printf '%s\n' 'This setup is for the Excel for Mac runner.' >&2
    exit 1
fi

# A venv still depends on its base Python; do not inherit the Codex runtime.
CHECK_BASE='import sys
from pathlib import Path
paths = [sys.executable, sys.base_prefix, *sys.path]
if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11 or newer is required.")
if any("codex" in str(Path(p).resolve()).lower() for p in paths if p):
    raise SystemExit("Choose an independent Python installation, not the Codex runtime.")
print("Python:", sys.executable)
print("Base installation:", sys.base_prefix)'

"$PYTHON" -I -c "$CHECK_BASE"
if [[ -e "$ROOT/.venv" ]]; then
    if [[ ! -x "$ROOT/.venv/bin/python3" ]]; then
        printf '%s\n' 'Existing .venv is incomplete. Preserve or rename it before retrying.' >&2
        exit 1
    fi
    "$ROOT/.venv/bin/python3" -I -c "$CHECK_BASE"
else
    "$PYTHON" -I -m venv "$ROOT/.venv"
fi

"$ROOT/.venv/bin/python3" -I -m pip install -r "$ROOT/excel_runner/requirements-runtime.txt"
"$ROOT/.venv/bin/python3" -I -m pip check
"$ROOT/.venv/bin/python3" -I -c 'import openpyxl, sys; print("Runner Python:", sys.executable); print("openpyxl:", openpyxl.__version__)'
printf '%s\n' 'Python setup complete. This does not modify workbook parameters or run a backtest.'
