#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

export GAZE_AGENT_CMD="${GAZE_AGENT_CMD:-uv run scripts/fake_agent.py}"
export GAZE_SOURCE="${GAZE_SOURCE:-mouse}"

exec pnpm dev "$@"
