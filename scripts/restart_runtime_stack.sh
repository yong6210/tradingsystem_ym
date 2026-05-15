#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE:-$0}"
ROOT_DIR="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd)"
cd "$ROOT_DIR"

export PYDANTIC_DISABLE_PLUGINS="${PYDANTIC_DISABLE_PLUGINS:-1}"
export PYTHONDONTWRITEBYTECODE="${PYTHONDONTWRITEBYTECODE:-1}"

LOG_DIR="/tmp"
LOG_ROTATE_MAX_BYTES="${TRADING_LOG_ROTATE_MAX_BYTES:-104857600}"
LOG_ROTATE_KEEP="${TRADING_LOG_ROTATE_KEEP:-5}"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
SPAWN_SCRIPT="$ROOT_DIR/scripts/spawn_detached_process.py"
WORKER_SCRIPT="$ROOT_DIR/scripts/run_worker.py"
HEARTBEAT_DIR="/tmp/trading_worker_heartbeats"
API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"
LAUNCHD_API_LABEL="${LAUNCHD_API_LABEL:-com.yumin.trading.api}"
READY_URL="http://$API_HOST:$API_PORT/health/ready"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "missing python runtime: $PYTHON_BIN" >&2
  exit 1
fi

file_size_bytes() {
  local path="$1"
  if stat -f%z "$path" >/dev/null 2>&1; then
    stat -f%z "$path"
    return 0
  fi
  if stat -c%s "$path" >/dev/null 2>&1; then
    stat -c%s "$path"
    return 0
  fi
  wc -c <"$path" | tr -d ' '
}

rotate_log_if_large() {
  local path="$1"
  local max_bytes="${LOG_ROTATE_MAX_BYTES:-0}"
  local keep="${LOG_ROTATE_KEEP:-5}"
  local size idx
  [[ -f "$path" ]] || return 0
  [[ "$max_bytes" =~ ^[0-9]+$ ]] || max_bytes=0
  [[ "$keep" =~ ^[0-9]+$ ]] || keep=5
  [[ "$max_bytes" -gt 0 ]] || return 0
  size="$(file_size_bytes "$path" 2>/dev/null || echo 0)"
  [[ "$size" =~ ^[0-9]+$ ]] || size=0
  [[ "$size" -ge "$max_bytes" ]] || return 0
  if [[ "$keep" -le 0 ]]; then
    : >"$path"
    return 0
  fi
  rm -f "$path.$keep"
  for ((idx=keep - 1; idx>=1; idx--)); do
    if [[ -e "$path.$idx" ]]; then
      mv "$path.$idx" "$path.$((idx + 1))"
    fi
  done
  mv "$path" "$path.1"
}

if [[ "$(uname -s)" == "Darwin" ]] && command -v launchctl >/dev/null 2>&1; then
  LAUNCHD_DOMAIN="gui/$(id -u)"
  if launchctl print "$LAUNCHD_DOMAIN/$LAUNCHD_API_LABEL" >/dev/null 2>&1; then
    launchctl bootout "$LAUNCHD_DOMAIN/$LAUNCHD_API_LABEL" >/dev/null 2>&1 || true
  fi
fi

if command -v lsof >/dev/null 2>&1; then
  while read -r pid; do
    [[ -n "$pid" ]] && kill "$pid" || true
  done < <(lsof -ti "tcp:$API_PORT" || true)
fi
pkill -TERM -f "uvicorn app.main:app" || true
pkill -TERM -f "run_worker.py --mode loop" || true
pkill -TERM -f "run_worker.py --ws-stream" || true
sleep 1
pkill -KILL -f "uvicorn app.main:app" || true
pkill -KILL -f "run_worker.py --mode loop" || true
pkill -KILL -f "run_worker.py --ws-stream" || true
sleep 1
if command -v lsof >/dev/null 2>&1; then
  for _ in $(seq 1 30); do
    if ! lsof -ti "tcp:$API_PORT" >/dev/null 2>&1; then
      break
    fi
    while read -r pid; do
      [[ -n "$pid" ]] && kill -KILL "$pid" || true
    done < <(lsof -ti "tcp:$API_PORT" || true)
    sleep 1
  done
  if lsof -ti "tcp:$API_PORT" >/dev/null 2>&1; then
    echo "port $API_PORT is still in use after cleanup" >&2
    exit 1
  fi
fi
rm -f "$HEARTBEAT_DIR/loop.json" "$HEARTBEAT_DIR/ws.json"

mkdir -p "$LOG_DIR"
for log_name in trading_api.log trading_worker_loop.log trading_worker_ws.log; do
  rotate_log_if_large "$LOG_DIR/$log_name"
done

{
  echo
  echo "===== restart $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
} >>"$LOG_DIR/trading_api.log"
{
  echo
  echo "===== restart $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
} >>"$LOG_DIR/trading_worker_loop.log"
{
  echo
  echo "===== restart $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
} >>"$LOG_DIR/trading_worker_ws.log"

"$PYTHON_BIN" "$SPAWN_SCRIPT" \
  --log "$LOG_DIR/trading_api.log" \
  -- env PYTHONUNBUFFERED=1 "$PYTHON_BIN" -m uvicorn app.main:app --host "$API_HOST" --port "$API_PORT" >/dev/null
"$PYTHON_BIN" "$SPAWN_SCRIPT" \
  --log "$LOG_DIR/trading_worker_loop.log" \
  -- env PYTHONUNBUFFERED=1 "$PYTHON_BIN" "$WORKER_SCRIPT" --mode loop --sync-universe --limit-symbols 30 --symbol-concurrency 1 --limit-1m 120 --limit-5m 500 --limit-15m 500 --interval-seconds 60 >/dev/null
"$PYTHON_BIN" "$SPAWN_SCRIPT" \
  --log "$LOG_DIR/trading_worker_ws.log" \
  -- env PYTHONUNBUFFERED=1 "$PYTHON_BIN" "$WORKER_SCRIPT" --ws-stream --sync-universe --limit-symbols 30 --ws-intervals 1m,5m,15m >/dev/null

last_ready_response=""
for _ in $(seq 1 180); do
  last_ready_response="$(curl -sS --max-time 5 "$READY_URL" 2>/dev/null || true)"
  if [[ "$last_ready_response" == *'"status":"ready"'* ]]; then
    printf '%s\n' "$last_ready_response"
    exit 0
  fi
  sleep 1
done

printf '%s\n' "${last_ready_response:-runtime_not_ready}"
exit 1
