#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE:-$0}"
ROOT_DIR="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd)"

RESTART_SCRIPT="${TRADING_RUNTIME_RESTART_SCRIPT:-$ROOT_DIR/scripts/restart_runtime_stack_tmp.sh}"
RUNTIME_BASE="${TRADING_RUNTIME_BASE:-$HOME/Library/Application Support/trading}"
HEARTBEAT_DIR="${TRADING_HEARTBEAT_DIR:-$RUNTIME_BASE/heartbeats}"
API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"
READY_URL="${TRADING_READY_URL:-http://$API_HOST:$API_PORT/health/ready}"
CHECK_INTERVAL_SECONDS="${TRADING_RUNTIME_WATCHDOG_INTERVAL_SECONDS:-30}"
FAIL_THRESHOLD="${TRADING_RUNTIME_WATCHDOG_FAIL_THRESHOLD:-3}"
RESTART_RETRY_SECONDS="${TRADING_RUNTIME_WATCHDOG_RESTART_RETRY_SECONDS:-60}"
STARTING_GRACE_SECONDS="${TRADING_RUNTIME_WATCHDOG_STARTING_GRACE_SECONDS:-900}"
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

file_mtime_epoch() {
  local path="$1"
  if stat -f %m "$path" >/dev/null 2>&1; then
    stat -f %m "$path"
    return 0
  fi
  if stat -c %Y "$path" >/dev/null 2>&1; then
    stat -c %Y "$path"
    return 0
  fi
  return 1
}

loop_phase_within_grace() {
  local phase_pattern="$1"
  local heartbeat_path="$HEARTBEAT_DIR/loop.json"
  local mtime now age
  [[ -f "$heartbeat_path" ]] || return 1
  if ! grep -Eq "\"phase\"[[:space:]]*:[[:space:]]*\"(${phase_pattern})\"" "$heartbeat_path"; then
    return 1
  fi
  mtime="$(file_mtime_epoch "$heartbeat_path" 2>/dev/null || true)"
  [[ "$mtime" =~ ^[0-9]+$ ]] || return 1
  now="$(date +%s)"
  age=$((now - mtime))
  [[ "$age" -ge 0 && "$age" -le "$STARTING_GRACE_SECONDS" ]]
}

loop_starting_within_grace() {
  loop_phase_within_grace "starting"
}

loop_warming_within_grace() {
  loop_phase_within_grace "starting|syncing_universe"
}

market_data_warmup_within_grace() {
  local response="$1"
  [[ "$response" == *'"status":"degraded"'* ]] || return 1
  if [[ "$response" != *'"market_data_1m":false'* && "$response" != *'"market_data_5m":false'* ]]; then
    return 1
  fi
  for key in '"db":true' '"binance_rest":true' '"event_backend":true' '"disk_free":true' '"worker_ws":true'; do
    [[ "$response" == *"$key"* ]] || return 1
  done
  if [[ "$response" != *'"worker_loop":true'* ]] && ! loop_warming_within_grace; then
    return 1
  fi
  loop_warming_within_grace
}

ready_state() {
  local response
  response="$(curl -fsS --max-time 10 "$READY_URL" 2>/dev/null || true)"
  if [[ "$response" == *'"status":"ready"'* ]]; then
    printf 'ready\n'
    return 0
  fi
  if [[ "$response" == *'"worker_loop":"heartbeat_starting"'* ]] && loop_starting_within_grace; then
    printf 'starting_grace\n'
    return 0
  fi
  if market_data_warmup_within_grace "$response"; then
    printf 'market_data_warmup_grace\n'
    return 0
  fi
  printf 'not_ready\n'
  return 1
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
  local state
  if state="$(ready_state)"; then
    if [[ "$state" == "starting_grace" ]]; then
      log "runtime_starting_grace"
      return 0
    fi
    if [[ "$state" == "market_data_warmup_grace" ]]; then
      log "runtime_market_data_warmup_grace"
      return 0
    fi
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
  state="$(ready_state)" || state="not_ready"
  if [[ "$state" == "ready" ]]; then
    if [[ "$failures" -gt 0 ]]; then
      log "runtime_ready_after_failures count=$failures"
    fi
    failures=0
    continue
  fi
  if [[ "$state" == "starting_grace" ]]; then
    if [[ "$failures" -gt 0 ]]; then
      log "runtime_starting_grace_after_failures count=$failures"
    fi
    failures=0
    continue
  fi
  if [[ "$state" == "market_data_warmup_grace" ]]; then
    if [[ "$failures" -gt 0 ]]; then
      log "runtime_market_data_warmup_grace_after_failures count=$failures"
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
