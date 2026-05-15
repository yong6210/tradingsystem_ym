#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE:-$0}"
SCRIPT_ROOT="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd)"

WORKSPACE_ROOT="${TRADING_WORKSPACE_ROOT:-/Users/yumin/Documents/trading}"
if [[ ! -d "$WORKSPACE_ROOT/app" && -d "$SCRIPT_ROOT/app" ]]; then
  WORKSPACE_ROOT="$SCRIPT_ROOT"
fi

RUNTIME_BASE="${TRADING_RUNTIME_BASE:-$HOME/Library/Application Support/trading}"
TMP_ROOT="${TRADING_TMP_RUNTIME_ROOT:-$RUNTIME_BASE/runtime_src}"
TMP_VENV="${TRADING_TMP_RUNTIME_VENV:-$RUNTIME_BASE/runtime_venv}"
DATA_DIR="${TRADING_RUNTIME_DATA_DIR:-$RUNTIME_BASE/data}"
REPORTS_DIR="${TRADING_RUNTIME_REPORTS_DIR:-$RUNTIME_BASE/reports}"
ARCHIVES_DIR="${TRADING_RUNTIME_ARCHIVES_DIR:-$RUNTIME_BASE/archives}"
LOG_DIR="${TRADING_LOG_DIR:-$RUNTIME_BASE/logs}"
HEARTBEAT_DIR="${TRADING_HEARTBEAT_DIR:-$RUNTIME_BASE/heartbeats}"
LOG_ROTATE_MAX_BYTES="${TRADING_LOG_ROTATE_MAX_BYTES:-104857600}"
LOG_ROTATE_KEEP="${TRADING_LOG_ROTATE_KEEP:-5}"
API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"
LAUNCHD_API_LABEL="${LAUNCHD_API_LABEL:-com.yumin.trading.api}"
READY_URL="http://$API_HOST:$API_PORT/health/ready"
REFRESH_SRC="${TRADING_REFRESH_TMP_RUNTIME_SRC:-auto}"
DB_PATH="$DATA_DIR/trading.db"
DATABASE_URL="sqlite:///$DB_PATH"

PYTHON_BIN="$TMP_VENV/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  cat >&2 <<EOF
missing tmp python runtime: $PYTHON_BIN

Create it first, then install the runtime dependencies there. Existing /tmp
runtime restarts intentionally avoid the workspace .venv because that can stall
when macOS file indexing is busy.
EOF
  exit 1
fi

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

refresh_tmp_source() {
  if [[ "$TMP_ROOT" == "$WORKSPACE_ROOT" ]]; then
    echo "refusing to refresh runtime source in-place over workspace: $TMP_ROOT" >&2
    exit 1
  fi
  mkdir -p "$TMP_ROOT"
  copy_tree "$WORKSPACE_ROOT/app" "$TMP_ROOT/app"
  copy_tree "$WORKSPACE_ROOT/scripts" "$TMP_ROOT/scripts"

  for file in .env pyproject.toml uv.lock; do
    if [[ -f "$WORKSPACE_ROOT/$file" ]]; then
      cp "$WORKSPACE_ROOT/$file" "$TMP_ROOT/$file"
    fi
  done
  if [[ ! -f "$TMP_ROOT/.env" ]]; then
    touch "$TMP_ROOT/.env"
  fi
  awk -F= '$1 != "DATABASE_URL" && $1 != "RUNTIME_WORKER_HEARTBEAT_DIR" { print }' "$TMP_ROOT/.env" > "$TMP_ROOT/.env.runtime"
  printf 'DATABASE_URL=%s\n' "$DATABASE_URL" >> "$TMP_ROOT/.env.runtime"
  printf 'RUNTIME_WORKER_HEARTBEAT_DIR=%s\n' "$HEARTBEAT_DIR" >> "$TMP_ROOT/.env.runtime"
  mv "$TMP_ROOT/.env.runtime" "$TMP_ROOT/.env"

  mkdir -p "$REPORTS_DIR" "$ARCHIVES_DIR"
  rm -rf "$TMP_ROOT/reports" "$TMP_ROOT/archives"
  ln -s "$REPORTS_DIR" "$TMP_ROOT/reports"
  ln -s "$ARCHIVES_DIR" "$TMP_ROOT/archives"

  if [[ -e "$TMP_ROOT/trading.db" && ! -L "$TMP_ROOT/trading.db" ]]; then
    mv "$TMP_ROOT/trading.db" "$TMP_ROOT/trading.db.backup.$(date -u +%Y%m%dT%H%M%SZ)"
  fi
  mkdir -p "$DATA_DIR"
  ln -sfn "$DB_PATH" "$TMP_ROOT/trading.db"

  find "$TMP_ROOT/app" "$TMP_ROOT/scripts" -name __pycache__ -type d -prune -exec rm -rf {} +
}

needs_refresh=0
case "$REFRESH_SRC" in
  1|true|yes)
    needs_refresh=1
    ;;
  0|false|no)
    needs_refresh=0
    ;;
  auto)
    if [[ ! -d "$TMP_ROOT/app" || ! -f "$TMP_ROOT/scripts/run_worker.py" || ! -f "$TMP_ROOT/scripts/spawn_detached_process.py" ]]; then
      needs_refresh=1
    fi
    ;;
  *)
    echo "invalid TRADING_REFRESH_TMP_RUNTIME_SRC: $REFRESH_SRC" >&2
    exit 1
    ;;
esac

if [[ "$needs_refresh" -eq 1 ]]; then
  refresh_tmp_source
fi

if [[ ! -f "$TMP_ROOT/scripts/run_worker.py" || ! -f "$TMP_ROOT/scripts/spawn_detached_process.py" ]]; then
  echo "runtime source is incomplete: $TMP_ROOT" >&2
  exit 1
fi
if [[ ! -f "$DB_PATH" ]]; then
  echo "runtime database is missing: $DB_PATH" >&2
  echo "Create or migrate the runtime DB before starting the durable runtime stack." >&2
  exit 1
fi

mkdir -p "$HEARTBEAT_DIR"

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

mkdir -p "$LOG_DIR"
for log_name in trading_api.log trading_worker_loop.log trading_worker_ws.log; do
  rotate_log_if_large "$LOG_DIR/$log_name"
done

rm -f "$HEARTBEAT_DIR/loop.json" "$HEARTBEAT_DIR/ws.json"

{
  echo
  echo "===== durable-runtime restart $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
} >>"$LOG_DIR/trading_api.log"
{
  echo
  echo "===== durable-runtime restart $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
} >>"$LOG_DIR/trading_worker_loop.log"
{
  echo
  echo "===== durable-runtime restart $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
} >>"$LOG_DIR/trading_worker_ws.log"

cd "$TMP_ROOT"
SPAWN_SCRIPT="$TMP_ROOT/scripts/spawn_detached_process.py"
WORKER_SCRIPT="$TMP_ROOT/scripts/run_worker.py"
BASE_ENV=(env PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYDANTIC_DISABLE_PLUGINS=1)

"$PYTHON_BIN" "$SPAWN_SCRIPT" \
  --log "$LOG_DIR/trading_api.log" \
  -- "${BASE_ENV[@]}" "$PYTHON_BIN" -m uvicorn app.main:app --host "$API_HOST" --port "$API_PORT" >/dev/null
"$PYTHON_BIN" "$SPAWN_SCRIPT" \
  --log "$LOG_DIR/trading_worker_loop.log" \
  -- "${BASE_ENV[@]}" "$PYTHON_BIN" "$WORKER_SCRIPT" --mode loop --sync-universe --limit-symbols 30 --symbol-concurrency 1 --limit-1m 120 --limit-5m 500 --limit-15m 500 --interval-seconds 60 >/dev/null
"$PYTHON_BIN" "$SPAWN_SCRIPT" \
  --log "$LOG_DIR/trading_worker_ws.log" \
  -- "${BASE_ENV[@]}" "$PYTHON_BIN" "$WORKER_SCRIPT" --ws-stream --sync-universe --limit-symbols 30 --ws-intervals 1m,5m,15m >/dev/null

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
