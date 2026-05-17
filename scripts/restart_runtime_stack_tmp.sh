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
READY_WAIT_SECONDS="${TRADING_RUNTIME_READY_WAIT_SECONDS:-600}"
RESTART_LOCK_DIR="${TRADING_RUNTIME_RESTART_LOCK_DIR:-$RUNTIME_BASE/locks/restart_runtime_stack_tmp.lock}"
RESTART_LOCK_WAIT_SECONDS="${TRADING_RUNTIME_RESTART_LOCK_WAIT_SECONDS:-300}"
DB_PATH="$DATA_DIR/trading.db"
DATABASE_URL="sqlite:///$DB_PATH"

PYTHON_BIN="$TMP_VENV/bin/python"
POST_RESTART_REFRESH_REPORTS="${TRADING_POST_RESTART_REFRESH_REPORTS:-1}"
POST_RESTART_NO_ORDER_DAYS="${TRADING_POST_RESTART_NO_ORDER_DAYS:-1}"
POST_RESTART_NO_ORDER_LIMIT="${TRADING_POST_RESTART_NO_ORDER_LIMIT:-80}"
WS_INTERVALS="${TRADING_WS_INTERVALS:-1m,5m,15m}"
WS_LIMIT_SYMBOLS="${TRADING_WS_LIMIT_SYMBOLS:-30}"
LOOP_LIMIT_SYMBOLS="${TRADING_LOOP_LIMIT_SYMBOLS:-0}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  cat >&2 <<EOF
missing tmp python runtime: $PYTHON_BIN

Create it first, then install the runtime dependencies there. Existing /tmp
runtime restarts intentionally avoid the workspace .venv because that can stall
when macOS file indexing is busy.
EOF
  exit 1
fi

truthy_value() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

acquire_restart_lock() {
  local waited=0
  local owner_pid=""
  local lock_parent
  lock_parent="$(dirname "$RESTART_LOCK_DIR")"
  mkdir -p "$lock_parent"
  while ! mkdir "$RESTART_LOCK_DIR" 2>/dev/null; do
    owner_pid="$(cat "$RESTART_LOCK_DIR/pid" 2>/dev/null || true)"
    if [[ "$owner_pid" =~ ^[0-9]+$ ]] && ! kill -0 "$owner_pid" 2>/dev/null; then
      rm -rf "$RESTART_LOCK_DIR"
      continue
    fi
    if [[ "$waited" -ge "$RESTART_LOCK_WAIT_SECONDS" ]]; then
      echo "restart lock is still held after ${RESTART_LOCK_WAIT_SECONDS}s: $RESTART_LOCK_DIR pid=${owner_pid:-unknown}" >&2
      exit 1
    fi
    sleep 1
    waited=$((waited + 1))
  done
  printf '%s\n' "$$" > "$RESTART_LOCK_DIR/pid"
  date -u +%Y-%m-%dT%H:%M:%SZ > "$RESTART_LOCK_DIR/started_at"
  trap 'rm -rf "$RESTART_LOCK_DIR"' EXIT
}

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

dotenv_value() {
  local key="$1"
  local file="$TMP_ROOT/.env"
  local value=""
  [[ -f "$file" ]] || return 0
  value="$(grep -E "^[[:space:]]*$key[[:space:]]*=" "$file" | tail -n 1 | sed -E "s/^[^=]*=//; s/[[:space:]]+#.*$//; s/^[[:space:]]+//; s/[[:space:]]+$//; s/^['\\\"]//; s/['\\\"]$//" || true)"
  printf '%s\n' "$value"
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

sync_micro_main_backtest_reports() {
  local report_dir path dst src_dir dst_dir pattern

  for report_dir in micro_main_usdt_proxy_backtests micro_main_usdc_backtests micro_main_usdt_backtests micro_main_risk_sweeps; do
    src_dir="$WORKSPACE_ROOT/reports/validation/$report_dir"
    dst_dir="$REPORTS_DIR/validation/$report_dir"
    [[ -d "$src_dir" ]] || continue
    mkdir -p "$dst_dir"
    pattern='*.json'
    while IFS= read -r path; do
      dst="$dst_dir/$(basename "$path")"
      if [[ ! -f "$dst" ]] || ! cmp -s "$path" "$dst"; then
        cp -p "$path" "$dst"
      fi
    done < <(find "$src_dir" -maxdepth 1 -type f -name "$pattern" | sort)
  done
}

post_restart_refresh_reports() {
  truthy_value "$POST_RESTART_REFRESH_REPORTS" || return 0

  local refresh_log="$LOG_DIR/post_restart_report_refresh.log"
  local entry_surface_dir="$TMP_ROOT/reports/operations/entry_surface"
  mkdir -p "$LOG_DIR" "$entry_surface_dir"

  run_report_refresh() {
    local name="$1"
    shift
    echo "-- $name begin $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    if "$@"; then
      echo "-- $name ok $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    else
      echo "-- $name failed rc=$? $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    fi
  }

  {
    echo
    echo "===== post-restart report refresh $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
    echo "runtime_src=$TMP_ROOT"
    echo "heartbeat_dir=$HEARTBEAT_DIR"
    cd "$TMP_ROOT"
    export RUNTIME_WORKER_HEARTBEAT_DIR="$HEARTBEAT_DIR"
    export TRADING_HEARTBEAT_DIR="$HEARTBEAT_DIR"
    run_report_refresh runtime_guard \
      "$PYTHON_BIN" "$TMP_ROOT/scripts/run_micro_live_runtime_guard.py" \
      --days 30 --limit 200 --no-fail-exit --quiet
    run_report_refresh no_order_watchdog \
      "$PYTHON_BIN" "$TMP_ROOT/scripts/run_micro_live_no_order_watchdog.py" \
      --days "$POST_RESTART_NO_ORDER_DAYS" --limit "$POST_RESTART_NO_ORDER_LIMIT" --no-fail-exit --quiet
    run_report_refresh live_candidate_promotion_readiness \
      "$PYTHON_BIN" "$TMP_ROOT/scripts/run_live_candidate_promotion_readiness.py" \
      --hours 24 --limit 12 --since-ws-start --heartbeat-dir "$HEARTBEAT_DIR" --quiet
    run_report_refresh live_replay_parity \
      "$PYTHON_BIN" "$TMP_ROOT/scripts/run_live_replay_parity_audit.py" \
      --all-live-symbols --days 3 --since-ws-start --heartbeat-dir "$HEARTBEAT_DIR" --no-fail-exit --quiet
    run_report_refresh session_impulse_retest_runtime_audit \
      "$PYTHON_BIN" "$TMP_ROOT/scripts/run_session_impulse_retest_runtime_audit_report.py" \
      --hours 3 --limit 200 --since-ws-start --heartbeat-dir "$HEARTBEAT_DIR" --no-fail-exit --quiet
    run_report_refresh entry_surface \
      "$PYTHON_BIN" "$TMP_ROOT/scripts/notify_entry_surface.py" \
      --quiet \
      --lock-file "$entry_surface_dir/entry_surface.lock" \
      --output-file "$entry_surface_dir/latest_entry_alert_run.json"
    run_report_refresh boot_check \
      "$PYTHON_BIN" "$TMP_ROOT/scripts/run_micro_live_boot_check.py" \
      --days 3 --limit 200 --no-fail-exit --quiet
    run_report_refresh ops_heartbeat \
      "$PYTHON_BIN" "$TMP_ROOT/scripts/run_micro_live_ops_heartbeat.py" \
      --no-fail-exit --quiet
  } >>"$refresh_log" 2>&1
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

acquire_restart_lock

if [[ "$needs_refresh" -eq 1 ]]; then
  refresh_tmp_source
fi
sync_micro_main_backtest_reports

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
WS_SYMBOLS="${TRADING_WS_SYMBOLS:-$(dotenv_value AUTO_TRADING_MICRO_LIVE_ALLOWED_SYMBOLS)}"
WS_ARGS=(--ws-stream --ws-intervals "$WS_INTERVALS")
if [[ -n "$WS_SYMBOLS" ]]; then
  WS_ARGS+=(--ws-symbols "$WS_SYMBOLS")
else
  WS_ARGS+=(--sync-universe --limit-symbols "$WS_LIMIT_SYMBOLS")
fi

"$PYTHON_BIN" "$SPAWN_SCRIPT" \
  --log "$LOG_DIR/trading_api.log" \
  -- "${BASE_ENV[@]}" "$PYTHON_BIN" -m uvicorn app.main:app --host "$API_HOST" --port "$API_PORT" >/dev/null
"$PYTHON_BIN" "$SPAWN_SCRIPT" \
  --log "$LOG_DIR/trading_worker_loop.log" \
  -- "${BASE_ENV[@]}" "$PYTHON_BIN" "$WORKER_SCRIPT" --mode loop --sync-universe --limit-symbols "$LOOP_LIMIT_SYMBOLS" --symbol-concurrency 1 --limit-1m 120 --limit-5m 500 --limit-15m 500 --interval-seconds 60 >/dev/null
"$PYTHON_BIN" "$SPAWN_SCRIPT" \
  --log "$LOG_DIR/trading_worker_ws.log" \
  -- "${BASE_ENV[@]}" "$PYTHON_BIN" "$WORKER_SCRIPT" "${WS_ARGS[@]}" >/dev/null

last_ready_response=""
for _ in $(seq 1 "$READY_WAIT_SECONDS"); do
  last_ready_response="$(curl -sS --max-time 5 "$READY_URL" 2>/dev/null || true)"
  if [[ "$last_ready_response" == *'"status":"ready"'* ]]; then
    post_restart_refresh_reports || true
    printf '%s\n' "$last_ready_response"
    exit 0
  fi
  sleep 1
done

printf '%s\n' "${last_ready_response:-runtime_not_ready}"
exit 1
