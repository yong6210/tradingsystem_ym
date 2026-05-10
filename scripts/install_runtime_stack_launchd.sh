#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE:-$0}"
ROOT_DIR="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd)"
RUNTIME_BASE="${TRADING_RUNTIME_BASE:-$HOME/Library/Application Support/trading}"
TMP_ROOT="${TRADING_TMP_RUNTIME_ROOT:-$RUNTIME_BASE/runtime_src}"
LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
DISABLED_DIR="${HOME}/Library/LaunchAgents.disabled/$(date -u +%Y%m%dT%H%M%SZ)_runtime_stack_cutover"
DOMAIN="gui/$(id -u)"
RUNTIME_STACK_LABEL="com.yumin.trading.runtime-stack"
RUNTIME_STACK_PLIST="$LAUNCH_AGENTS_DIR/$RUNTIME_STACK_LABEL.plist"

mkdir -p "$LAUNCH_AGENTS_DIR" "$DISABLED_DIR"

for label in \
  com.yumin.trading.api \
  com.yumin.trading.stage-monitor \
  com.yumin.trading.paper-lineage-watch
do
  launchctl bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
  if [[ -f "$LAUNCH_AGENTS_DIR/$label.plist" ]]; then
    mv "$LAUNCH_AGENTS_DIR/$label.plist" "$DISABLED_DIR/$label.plist"
  fi
done

if [[ ! -d "$TMP_ROOT/scripts" ]]; then
  echo "missing durable runtime source: $TMP_ROOT" >&2
  echo "Run scripts/restart_runtime_stack_tmp.sh once from the workspace to create the durable runtime copy." >&2
  exit 1
fi

cp "$ROOT_DIR/scripts/watch_runtime_stack_tmp.sh" "$TMP_ROOT/scripts/watch_runtime_stack_tmp.sh"
cp "$ROOT_DIR/scripts/restart_runtime_stack_tmp.sh" "$TMP_ROOT/scripts/restart_runtime_stack_tmp.sh"
chmod +x "$TMP_ROOT/scripts/watch_runtime_stack_tmp.sh" "$TMP_ROOT/scripts/restart_runtime_stack_tmp.sh"

plutil -lint "$ROOT_DIR/launchd/$RUNTIME_STACK_LABEL.plist" >/dev/null
launchctl bootout "$DOMAIN/$RUNTIME_STACK_LABEL" >/dev/null 2>&1 || true
cp "$ROOT_DIR/launchd/$RUNTIME_STACK_LABEL.plist" "$RUNTIME_STACK_PLIST"
launchctl bootstrap "$DOMAIN" "$RUNTIME_STACK_PLIST"

launchctl print "$DOMAIN/$RUNTIME_STACK_LABEL" | sed -n '1,80p'
echo "disabled_legacy_plists=$DISABLED_DIR"
