#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE:-$0}"
ROOT_DIR="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd)"

RESTART_SCRIPT="${TRADING_RUNTIME_RESTART_SCRIPT:-$ROOT_DIR/scripts/restart_runtime_stack_tmp.sh}"
RUNTIME_BASE="${TRADING_RUNTIME_BASE:-$HOME/Library/Application Support/trading}"
API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"
READY_URL="${TRADING_READY_URL:-http://$API_HOST:$API_PORT/health/ready}"
CHECK_INTERVAL_SECONDS="${TRADING_RUNTIME_WATCHDOG_INTERVAL_SECONDS:-30}"
FAIL_THRESHOLD="${TRADING_RUNTIME_WATCHDOG_FAIL_THRESHOLD:-3}"
RESTART_RETRY_SECONDS="${TRADING_RUNTIME_WATCHDOG_RESTART_RETRY_SECONDS:-60}"
ONCE="${TRADING_RUNTIME_WATCHDOG_ONCE:-0}"

log() {
  mkdir -p "$RUNTIME_BASE/logs"
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

truthy() {
  case "${1:-}" in
    1|true|TRUE|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

check_ready() {
  local response
  response="$(curl -fsS --max-time 10 "$READY_URL" 2>/dev/null || true)"
  [[ "$response" == *'"status":"ready"'* ]]
}

restart_runtime() {
  if [[ ! -x "$RESTART_SCRIPT" ]]; then
    log "restart_script_missing path=$RESTART_SCRIPT"
    return 1
  fi
  log "restart_runtime_stack_tmp begin"
  if "$RESTART_SCRIPT"; then
    log "restart_runtime_stack_tmp ok"
    return 0
  fi
  log "restart_runtime_stack_tmp failed"
  return 1
}

ensure_ready() {
  if check_ready; then
    log "runtime_ready"
    return 0
  fi
  while ! restart_runtime; do
    sleep "$RESTART_RETRY_SECONDS"
  done
}

ensure_ready

if truthy "$ONCE"; then
  exit 0
fi

failures=0
while true; do
  sleep "$CHECK_INTERVAL_SECONDS"
  if check_ready; then
    if [[ "$failures" -gt 0 ]]; then
      log "runtime_ready_after_failures count=$failures"
    fi
    failures=0
    continue
  fi

  failures=$((failures + 1))
  log "runtime_not_ready failure_count=$failures threshold=$FAIL_THRESHOLD"
  if [[ "$failures" -ge "$FAIL_THRESHOLD" ]]; then
    restart_runtime || true
    failures=0
  fi
done
