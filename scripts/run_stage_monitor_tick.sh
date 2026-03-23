#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STAGE_DIR="$ROOT_DIR/reports/operations/stage_monitor"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"

mkdir -p "$STAGE_DIR"
cd "$ROOT_DIR"

"$PYTHON_BIN" "$ROOT_DIR/scripts/ops_stage_board.py" --json \
  > "$STAGE_DIR/latest_stage_board.json"

NOTIFY_ARGS=()
if [[ -n "${STAGE_MONITOR_DISCORD_WEBHOOK_URL:-}" ]]; then
  NOTIFY_ARGS+=(--webhook-url "$STAGE_MONITOR_DISCORD_WEBHOOK_URL")
fi
if [[ "${STAGE_MONITOR_DRY_RUN:-0}" == "1" ]]; then
  NOTIFY_ARGS+=(--dry-run)
fi

"$PYTHON_BIN" "$ROOT_DIR/scripts/notify_stage_change.py" "${NOTIFY_ARGS[@]}"
