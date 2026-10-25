#!/bin/sh
# One command from a fresh clone: checks the tools, installs what is missing, starts the overlay.
#
#   scripts/start.sh live       LIVE: Electron overlay + the real Python agent. It calls OpenAI and
#                               really clicks and types in your apps (risky actions still ask you to
#                               confirm). Needs OPENAI_API_KEY (shell or .env; not with REPLAY=replay)
#                               and OPENAI_MODEL_AGENT/FAST/VISION. Grant this terminal Accessibility
#                               and Screen Recording. DEMO_MODE=1 and GAZE_SOURCE=mouse unless you set
#                               them in the shell (the launcher's defaults win over .env). Alias: real
#   scripts/start.sh preview    PREVIEW: Electron overlay + the fake agent. Scripted suggestions and
#                               results; no OpenAI, no desktop actions. Alias: fake. Also the default.
#   scripts/start.sh browser    PREVIEW in your browser + the fake agent.
#   scripts/start.sh stop       Stop leftover overlay, agent and dev servers started from this checkout.
#
# Also: pnpm start [live|preview|browser|stop]. Ctrl+C in this terminal quits.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

usage() {
  echo "Usage: scripts/start.sh [live|preview|browser|stop]" >&2
  echo "  live     real agent: calls OpenAI and acts on this Mac (alias: real)" >&2
  echo "  preview  fake agent: no OpenAI, no desktop actions (alias: fake; the default)" >&2
  echo "  browser  fake agent, overlay UI in your browser" >&2
  echo "  stop     stop leftovers started from this checkout" >&2
}

case "${1:-preview}" in
  live|real) MODE=live ;;
  preview|fake) MODE=preview ;;
  browser) MODE=browser ;;
  stop) exec scripts/dev-browser.sh stop ;;
  -h|--help|help) usage; exit 0 ;;
  *) usage; exit 2 ;;
esac

# A setting as Electron main will see it: a variable set in the shell wins over .env (dotenv does not
# override). Only presence is ever tested or printed for the key; values stay in this process.
env_file_value() {
  [ -f .env ] || return 0
  # Last assignment wins, like dotenv; optional "export"; quotes or an unquoted " # comment" removed.
  sed -n "s/^[[:space:]]*\(export[[:space:]][[:space:]]*\)\{0,1\}$1[[:space:]]*=[[:space:]]*//p" .env | tail -n 1 |
    sed -e 's/[[:space:]]*$//' -e "s/^\"\(.*\)\"$/\1/" -e "s/^'\(.*\)'$/\1/" -e 's/^\([^"'"'"'][^#]*\)[[:space:]]#.*$/\1/' -e 's/^#.*$//' -e 's/[[:space:]]*$//'
}
setting() {
  if eval "[ \"\${$1+set}\" = set ]"; then eval "printf '%s' \"\${$1}\""; else env_file_value "$1"; fi
}
# Prints $1 only if it is one of the allowed values; Electron main reports anything else.
shown() {
  value=$1; shift
  for allowed in "$@"; do [ "$value" = "$allowed" ] && { printf '%s' "$value"; return; }; done
  printf 'invalid'
}

if [ "$MODE" = live ]; then
  # Fail before installing or starting anything; Electron main repeats the full check (models, efforts).
  if [ "$(setting REPLAY)" != replay ] && [ -z "$(setting OPENAI_API_KEY | tr -d '[:space:]')" ]; then
    echo "LIVE needs OPENAI_API_KEY, in the shell or in $ROOT/.env (copy .env.example and fill it in)." >&2
    echo "Nothing was started. For the fake agent: scripts/start.sh preview" >&2
    exit 1
  fi
fi

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
echo "Hotkeys: ⌃⌥⌘. STOP + hide/show   ⌃⌥⌘D click mode (dwell off)   ⌃⌥⌘M mouse <-> eye tracking   ⌃⌥⌘Q quit"
echo

case "$MODE" in
  preview)
    [ -z "${GAZE_AGENT_CMD:-}" ] || echo "Ignoring GAZE_AGENT_CMD: the preview always runs the fake agent."
    GAZE_AGENT_CMD= exec scripts/dev.sh
    ;;
  live)
    uv sync --project agent --quiet
    export GAZE_SOURCE="${GAZE_SOURCE:-mouse}" DEMO_MODE="${DEMO_MODE:-1}"
    echo "LIVE: the real agent calls OpenAI and clicks and types on this Mac."
    replay=$(setting REPLAY)
    echo "  DEMO_MODE=$(shown "$DEMO_MODE" 0 1)  GAZE_SOURCE=$(shown "$GAZE_SOURCE" mouse webgazer)  REPLAY=$(shown "${replay:-off}" off record replay)"
    echo "  Stop a task: dwell STOP or press ⌃⌥⌘.   Quit: ⌃⌥⌘Q or Ctrl+C here."
    echo
    # Electron main starts the real agent only for GAZE_AGENT_MODE=live with no GAZE_AGENT_CMD.
    GAZE_AGENT_MODE=live GAZE_AGENT_CMD= exec pnpm dev
    ;;
  browser)
    exec scripts/dev-browser.sh
    ;;
esac
