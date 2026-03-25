#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STAGE_DIR="$ROOT_DIR/reports/operations/stage_monitor"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"

mkdir -p "$STAGE_DIR"
cd "$ROOT_DIR"

"$PYTHON_BIN" "$ROOT_DIR/scripts/stage_monitor_tick.py"
