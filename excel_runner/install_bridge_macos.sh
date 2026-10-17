#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ "$(uname -s)" != "Darwin" ]]; then
    printf '%s\n' 'This bridge is for Microsoft Excel for Mac.' >&2
    exit 1
fi
DEST="$HOME/Library/Application Scripts/com.microsoft.Excel"
mkdir -p "$DEST"
TARGET="$DEST/BacktestRunner.scpt"
TEMP="$(mktemp -d)"
trap 'rm -rf "$TEMP"' EXIT
osacompile -o "$TEMP/BacktestRunner.scpt" "$ROOT/excel_runner/BacktestRunner.applescript"
if [[ -f "$TARGET" ]] && cmp -s <(osadecompile "$TARGET") <(osadecompile "$TEMP/BacktestRunner.scpt"); then
    printf '%s\n' 'The Excel bridge is already installed.'
    exit 0
fi
if [[ -f "$TARGET" ]]; then
    BACKUP="$TARGET.backup-$(date +%Y%m%d_%H%M%S)-$$"
    cp -p "$TARGET" "$BACKUP"
    printf 'Previous bridge preserved: %s\n' "$BACKUP"
fi
cp "$TEMP/BacktestRunner.scpt" "$TARGET"
printf 'Excel bridge installed: %s\n' "$TARGET"
