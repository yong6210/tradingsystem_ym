#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BRIEF_DIR="$ROOT_DIR/reports/operations/operator_session_briefs"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  else
    echo "python3 is required to run notify_operator_session_brief.py" >&2
    exit 1
  fi
fi

mkdir -p "$BRIEF_DIR"
cd "$ROOT_DIR"

BRIEF_MODE="${OPERATOR_BRIEF_MODE:-shift-start}"
if [[ "$BRIEF_MODE" != "shift-start" && "$BRIEF_MODE" != "shift-end" ]]; then
  echo "OPERATOR_BRIEF_MODE must be shift-start or shift-end" >&2
  exit 1
fi

MODE_SLUG="${BRIEF_MODE//-/_}"
CHANNEL_SLUG="${OPERATOR_BRIEF_CHANNEL:-system}"
CHANNEL_SLUG="${CHANNEL_SLUG//-/_}"
LATEST_RUN_PATH="${OPERATOR_BRIEF_LATEST_RUN_FILE:-$BRIEF_DIR/latest_operator_session_brief_${MODE_SLUG}.json}"
STATE_PATH="${OPERATOR_BRIEF_STATE_FILE:-$BRIEF_DIR/last_alert_state_${MODE_SLUG}_${CHANNEL_SLUG}.json}"

NOTIFY_ARGS=(
  --symbol "${OPERATOR_BRIEF_SYMBOL:-BTCUSDC}"
  --universe "${OPERATOR_BRIEF_UNIVERSE:-usdc_perp_top30}"
  --days "${OPERATOR_BRIEF_DAYS:-7}"
  --portfolio-limit "${OPERATOR_BRIEF_PORTFOLIO_LIMIT:-5}"
  --intent-limit "${OPERATOR_BRIEF_INTENT_LIMIT:-5}"
  --reconcile-limit "${OPERATOR_BRIEF_RECONCILE_LIMIT:-5}"
  --channel "${OPERATOR_BRIEF_CHANNEL:-system}"
  --brief-mode "$BRIEF_MODE"
  --state-file "$STATE_PATH"
)

if [[ -n "${OPERATOR_BRIEF_DISCORD_WEBHOOK_URL:-}" ]]; then
  NOTIFY_ARGS+=(--webhook-url "$OPERATOR_BRIEF_DISCORD_WEBHOOK_URL")
fi
if [[ "${OPERATOR_BRIEF_FORCE_SEND:-0}" == "1" ]]; then
  NOTIFY_ARGS+=(--force-send)
fi
if [[ "${OPERATOR_BRIEF_DRY_RUN:-0}" == "1" ]]; then
  NOTIFY_ARGS+=(--dry-run)
fi

"$PYTHON_BIN" "$ROOT_DIR/scripts/notify_operator_session_brief.py" "${NOTIFY_ARGS[@]}" \
  > "$LATEST_RUN_PATH"
