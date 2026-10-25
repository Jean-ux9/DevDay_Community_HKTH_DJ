#!/bin/sh
# PREVIEW: Electron overlay + the fake agent, mouse = gaze. No OpenAI, no desktop actions.
# GAZE_AGENT_CMD=<command> runs that command as the agent instead (custom: not checked to be fake).
# The real agent starts only with scripts/start.sh live.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

if [ -n "${GAZE_AGENT_CMD:-}" ]; then
  export GAZE_AGENT_MODE=custom
  echo "CUSTOM agent from GAZE_AGENT_CMD (not the fake preview; it may act on this Mac)."
else
  export GAZE_AGENT_MODE=preview
  echo "PREVIEW: fake agent. Scripted suggestions and results; no OpenAI, no desktop actions."
  echo "For the real agent: scripts/start.sh live"
fi
export GAZE_SOURCE="${GAZE_SOURCE:-mouse}"

exec pnpm dev "$@"
