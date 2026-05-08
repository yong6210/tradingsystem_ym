#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE:-$0}"
ROOT_DIR="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd)"
cd "$ROOT_DIR"

export PYDANTIC_DISABLE_PLUGINS="${PYDANTIC_DISABLE_PLUGINS:-1}"
export PYTHONDONTWRITEBYTECODE="${PYTHONDONTWRITEBYTECODE:-1}"

LOG_DIR="/tmp"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
SPAWN_SCRIPT="$ROOT_DIR/scripts/spawn_detached_process.py"
WORKER_SCRIPT="$ROOT_DIR/scripts/run_worker.py"
HEARTBEAT_DIR="/tmp/trading_worker_heartbeats"
API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"
READY_URL="http://$API_HOST:$API_PORT/health/ready"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "missing python runtime: $PYTHON_BIN" >&2
  exit 1
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
