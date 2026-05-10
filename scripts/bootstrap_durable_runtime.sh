#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE:-$0}"
WORKSPACE_ROOT="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd)"
RUNTIME_BASE="${TRADING_RUNTIME_BASE:-$HOME/Library/Application Support/trading}"
RUNTIME_SRC="${TRADING_TMP_RUNTIME_ROOT:-$RUNTIME_BASE/runtime_src}"
RUNTIME_VENV="${TRADING_TMP_RUNTIME_VENV:-$RUNTIME_BASE/runtime_venv}"
DATA_DIR="${TRADING_RUNTIME_DATA_DIR:-$RUNTIME_BASE/data}"
REPORTS_DIR="${TRADING_RUNTIME_REPORTS_DIR:-$RUNTIME_BASE/reports}"
ARCHIVES_DIR="${TRADING_RUNTIME_ARCHIVES_DIR:-$RUNTIME_BASE/archives}"
LOG_DIR="${TRADING_LOG_DIR:-$RUNTIME_BASE/logs}"
HEARTBEAT_DIR="${TRADING_HEARTBEAT_DIR:-$RUNTIME_BASE/heartbeats}"
PYTHON_CREATE_BIN="${TRADING_RUNTIME_CREATE_PYTHON:-/opt/homebrew/bin/python3}"
DB_PATH="$DATA_DIR/trading.db"
DATABASE_URL="sqlite:///$DB_PATH"

copy_tree() {
  local src="$1"
  local dst="$2"
  rm -rf "$dst"
  mkdir -p "$(dirname "$dst")"
  if cp -cR "$src" "$dst" 2>/dev/null; then
    return 0
  fi
  cp -R "$src" "$dst"
}

if [[ ! -x "$PYTHON_CREATE_BIN" ]]; then
  echo "missing Python runtime creator: $PYTHON_CREATE_BIN" >&2
  exit 1
fi

mkdir -p "$RUNTIME_BASE" "$DATA_DIR" "$REPORTS_DIR" "$ARCHIVES_DIR" "$LOG_DIR" "$HEARTBEAT_DIR"

if [[ ! -x "$RUNTIME_VENV/bin/python" ]]; then
  "$PYTHON_CREATE_BIN" -m venv "$RUNTIME_VENV"
fi

"$RUNTIME_VENV/bin/python" -m pip install --upgrade pip
WORKSPACE_ROOT="$WORKSPACE_ROOT" "$RUNTIME_VENV/bin/python" - <<'PY'
from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

workspace = Path(os.environ["WORKSPACE_ROOT"])
with (workspace / "pyproject.toml").open("rb") as handle:
    deps = tomllib.load(handle)["project"]["dependencies"]
subprocess.check_call([sys.executable, "-m", "pip", "install", *deps])
PY

copy_tree "$WORKSPACE_ROOT/app" "$RUNTIME_SRC/app"
copy_tree "$WORKSPACE_ROOT/scripts" "$RUNTIME_SRC/scripts"

for file in .env pyproject.toml uv.lock; do
  if [[ -f "$WORKSPACE_ROOT/$file" ]]; then
    cp "$WORKSPACE_ROOT/$file" "$RUNTIME_SRC/$file"
  fi
done
if [[ ! -f "$RUNTIME_SRC/.env" ]]; then
  touch "$RUNTIME_SRC/.env"
fi
awk -F= '$1 != "DATABASE_URL" && $1 != "RUNTIME_WORKER_HEARTBEAT_DIR" { print }' "$RUNTIME_SRC/.env" > "$RUNTIME_SRC/.env.runtime"
printf 'DATABASE_URL=%s\n' "$DATABASE_URL" >> "$RUNTIME_SRC/.env.runtime"
printf 'RUNTIME_WORKER_HEARTBEAT_DIR=%s\n' "$HEARTBEAT_DIR" >> "$RUNTIME_SRC/.env.runtime"
mv "$RUNTIME_SRC/.env.runtime" "$RUNTIME_SRC/.env"

rm -rf "$RUNTIME_SRC/reports" "$RUNTIME_SRC/archives"
ln -s "$REPORTS_DIR" "$RUNTIME_SRC/reports"
ln -s "$ARCHIVES_DIR" "$RUNTIME_SRC/archives"
ln -sfn "$DB_PATH" "$RUNTIME_SRC/trading.db"

if [[ -d "$WORKSPACE_ROOT/reports/validation/contracts" ]]; then
  mkdir -p "$REPORTS_DIR/validation"
  rm -rf "$REPORTS_DIR/validation/contracts"
  copy_tree "$WORKSPACE_ROOT/reports/validation/contracts" "$REPORTS_DIR/validation/contracts"
fi

if [[ ! -f "$DB_PATH" ]]; then
  if [[ ! -f "$WORKSPACE_ROOT/trading.db" ]]; then
    echo "missing source database: $WORKSPACE_ROOT/trading.db" >&2
    exit 1
  fi
  if command -v lsof >/dev/null 2>&1 && lsof "$WORKSPACE_ROOT/trading.db" >/dev/null 2>&1; then
    echo "source database has open holders; stop runtime before first durable DB migration" >&2
    exit 1
  fi
  SRC_DB="$WORKSPACE_ROOT/trading.db" DST_DB="$DB_PATH" "$RUNTIME_VENV/bin/python" - <<'PY'
import os
import sqlite3
from pathlib import Path

src = Path(os.environ["SRC_DB"])
dst = Path(os.environ["DST_DB"])
dst.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(src) as source, sqlite3.connect(dst) as target:
    source.backup(target)
PY
fi

find "$RUNTIME_SRC/app" "$RUNTIME_SRC/scripts" -name __pycache__ -type d -prune -exec rm -rf {} +

echo "runtime_src=$RUNTIME_SRC"
echo "runtime_venv=$RUNTIME_VENV"
echo "runtime_db=$DB_PATH"
echo "runtime_reports=$REPORTS_DIR"
echo "runtime_heartbeats=$HEARTBEAT_DIR"
