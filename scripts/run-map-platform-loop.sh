#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/abhisheksrivastava/intact-agent-runner"
LOCK_DIR="/tmp/intact-map-platform-host-runner.lock"
LOG_DIR="$ROOT/logs"
ENV_FILE="${INTACT_AGENT_RUNNER_ENV:-$HOME/.config/intact-agent-runner/map-platform.env}"

mkdir -p "$LOG_DIR"

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) another map-platform host loop is already running"
  exit 0
fi

cleanup() {
  rmdir "$LOCK_DIR" 2>/dev/null || true
}
trap cleanup EXIT

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

export AGENT_RUNNER_ROOT="$ROOT"
export MCP_SERVER_ROOT="${MCP_SERVER_ROOT:-/Users/abhisheksrivastava/intact-mcp-server}"
export MAP_PLATFORM_ROOT="${MAP_PLATFORM_ROOT:-/Users/abhisheksrivastava/map_platform}"
export LLM_PROVIDER="${LLM_PROVIDER:-openai}"
export AUTOMATION_ID="${AUTOMATION_ID:-intact-agent-runner-launchd-map-platform}"
export COMMIT_AND_PUSH="${COMMIT_AND_PUSH:-1}"

cd "$ROOT"
exec node src/cli.js host-run --product map-platform
