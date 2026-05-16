#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE:-$0}"
ROOT_DIR="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd)"

echo "restart_runtime_stack.sh is a compatibility wrapper; delegating to restart_runtime_stack_tmp.sh" >&2
exec "$ROOT_DIR/scripts/restart_runtime_stack_tmp.sh" "$@"
