#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENTRY_DIR="$ROOT_DIR/reports/operations/entry_surface"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
RUNTIME_BASE="${TRADING_RUNTIME_BASE:-$HOME/Library/Application Support/trading}"
RUNTIME_PYTHON_BIN="$RUNTIME_BASE/runtime_venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  if [[ -x "$RUNTIME_PYTHON_BIN" ]]; then
    PYTHON_BIN="$RUNTIME_PYTHON_BIN"
  elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  else
    echo "python3 is required to run notify_entry_surface.py" >&2
    exit 1
  fi
fi

mkdir -p "$ENTRY_DIR"
cd "$ROOT_DIR"

STATE_FILE="${ENTRY_SURFACE_STATE_FILE:-$ENTRY_DIR/last_alert_state.json}"
LOCK_FILE="${ENTRY_SURFACE_LOCK_FILE:-$STATE_FILE.lock}"
OUTPUT_FILE="${ENTRY_SURFACE_OUTPUT_FILE:-$ENTRY_DIR/latest_entry_alert_run.json}"

NOTIFY_ARGS=(
  --base-url "${ENTRY_SURFACE_BASE_URL:-http://127.0.0.1:8000}"
  --universe "${ENTRY_SURFACE_UNIVERSE:-usdc_perp_top30}"
  --limit "${ENTRY_SURFACE_LIMIT:-20}"
  --max-per-status "${ENTRY_SURFACE_MAX_PER_STATUS:-3}"
  --channel "${ENTRY_SURFACE_CHANNEL:-discord}"
  --state-file "$STATE_FILE"
  --lock-file "$LOCK_FILE"
  --output-file "$OUTPUT_FILE"
  --min-repeat-minutes "${ENTRY_SURFACE_MIN_REPEAT_MINUTES:-360}"
)

if [[ -n "${ENTRY_SURFACE_SYMBOL:-}" ]]; then
  NOTIFY_ARGS+=(--symbol "$ENTRY_SURFACE_SYMBOL")
fi
if [[ -n "${ENTRY_SURFACE_DISCORD_WEBHOOK_URL:-}" ]]; then
  NOTIFY_ARGS+=(--webhook-url "$ENTRY_SURFACE_DISCORD_WEBHOOK_URL")
fi
if [[ "${ENTRY_SURFACE_FORCE_SEND:-0}" == "1" ]]; then
  NOTIFY_ARGS+=(--force-send)
fi
if [[ "${ENTRY_SURFACE_DRY_RUN:-0}" == "1" ]]; then
  NOTIFY_ARGS+=(--dry-run)
fi

"$PYTHON_BIN" "$ROOT_DIR/scripts/notify_entry_surface.py" "${NOTIFY_ARGS[@]}"
