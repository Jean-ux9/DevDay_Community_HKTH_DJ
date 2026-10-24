#!/bin/sh
# One command from a fresh clone: checks the tools, installs what is missing, starts the overlay.
#
#   scripts/start.sh            Electron overlay + fake agent (no OpenAI, no desktop actions)
#   scripts/start.sh real       Electron overlay + the real Python agent (.env with OPENAI_API_KEY;
#                               it really clicks and types: grant the terminal Accessibility and
#                               Screen Recording; DEMO_MODE=1 unless you set it)
#   scripts/start.sh browser    overlay UI in your browser + fake agent
#
# Also: pnpm start [real|browser]. Ctrl+C in this terminal quits.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
MODE=${1:-fake}

need() {
  command -v "$1" >/dev/null 2>&1 && return 0
  echo "Missing '$1'. Install it with: $2" >&2
  exit 1
}
need node "brew install node   (Node 24, or 22.22+)"
need pnpm "brew install pnpm   (or: npm install -g pnpm)"
need uv "brew install uv     (or: curl -LsSf https://astral.sh/uv/install.sh | sh)"
node -e '
  const [maj, min] = process.versions.node.split(".").map(Number)
  const ok = (maj === 22 && min >= 22) || (maj === 24 && min >= 15) || maj >= 26
  if (!ok) { console.error(`Node ${process.versions.node} is too old for the overlay; use Node 24 (or 22.22+).`); process.exit(1) }'

# JS packages for the overlay (fast when already up to date). Python deps: uv resolves them itself.
pnpm install --frozen-lockfile --reporter=silent

echo
echo "Hotkeys: ⌃⌥⌘. STOP + hide/show   ⌃⌥⌘D click mode (dwell off)   ⌃⌥⌘M mouse <-> eye tracking"
echo

case "$MODE" in
  fake)
    exec scripts/dev.sh
    ;;
  real)
    if [ ! -f .env ] || ! grep -Eq '^OPENAI_API_KEY=.+' .env; then
      echo "No OPENAI_API_KEY in $ROOT/.env (copy .env.example and fill it in)." >&2
      exit 1
    fi
    uv sync --project agent --quiet
    # An empty GAZE_AGENT_CMD makes Electron spawn the real agent (uv run --project agent …).
    GAZE_AGENT_CMD= GAZE_SOURCE="${GAZE_SOURCE:-mouse}" DEMO_MODE="${DEMO_MODE:-1}" exec pnpm dev
    ;;
  browser)
    exec scripts/dev-browser.sh
    ;;
  *)
    echo "Usage: scripts/start.sh [fake|real|browser]" >&2
    exit 2
    ;;
esac
