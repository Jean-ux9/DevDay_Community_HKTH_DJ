#!/bin/sh
# Browser PREVIEW: the overlay UI in a plain browser against the fake agent, with mouse = gaze (hover,
# no clicks). Always the fake agent: no OpenAI, no desktop actions.
#
#   scripts/dev-browser.sh          stop leftovers, start both servers on free ports, open the page
#   scripts/dev-browser.sh stop     stop leftovers from this checkout only: dev servers, fake or real
#                                   agents and the Electron overlay (also: scripts/start.sh stop)
#   NO_OPEN=1 scripts/dev-browser.sh   start without opening a browser
#
# Ctrl+C stops everything this script started. Processes started from other worktrees are never touched.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

# Dev servers (vite, fake agent). `stop` also takes the Electron overlay, its electron-vite runner and
# a real agent (gaze_agent.server). Only processes whose working directory is inside this checkout.
DEV_SERVERS='vite/bin/vite.js|scripts/fake_agent.py'
EVERYTHING="$DEV_SERVERS|electron-vite|Electron\.app/Contents/MacOS/Electron( |\$)|gaze_agent\.server"
ours() {
  for pid in $(pgrep -f "$1" 2>/dev/null || true); do
    cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')
    case "$cwd" in "$ROOT"|"$ROOT"/*) echo "$pid" ;; esac
  done
}

# stop_leftovers PATTERN SIGNAL...: each signal in turn, ~3 s apart, then SIGKILL for what is left.
stop_leftovers() {
  pattern=$1; shift
  pids=$(ours "$pattern")
  [ -z "$pids" ] && return 0
  echo "Stopping old processes from this checkout: $(echo $pids)"
  for signal in "$@"; do
    kill -"$signal" $pids 2>/dev/null || true
    kill -CONT $pids 2>/dev/null || true # a suspended process only acts on a signal once resumed
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      pids=$(ours "$pattern")
      [ -z "$pids" ] && return 0
      sleep 0.3
    done
  done
  kill -9 $pids 2>/dev/null || true
}

if [ "${1:-}" = "stop" ]; then
  # INT first, so the overlay and an agent can shut down cleanly (stop the task, close sessions).
  stop_leftovers "$EVERYTHING" INT TERM
  exit 0
fi

stop_leftovers "$DEV_SERVERS" TERM

free_port() { node -e "const s=require('net').createServer();s.listen(0,'127.0.0.1',()=>{console.log(s.address().port);s.close()})"; }
AGENT_PORT=$(free_port)
VITE_PORT=$(free_port)
TOKEN=dev-token
URL="http://127.0.0.1:$VITE_PORT/?port=$AGENT_PORT&token=$TOKEN"

AGENT_PID=
VITE_PID=
kill_tree() {
  [ -n "$1" ] || return 0
  pkill -TERM -P "$1" 2>/dev/null || true
  kill -TERM "$1" 2>/dev/null || true
  pkill -CONT -P "$1" 2>/dev/null || true
}
cleanup() {
  trap - EXIT INT TERM HUP
  echo
  echo "Stopping the fake agent and vite…"
  kill_tree "$VITE_PID"
  kill_tree "$AGENT_PID"
  wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP # HUP: the terminal window was closed

# stdin from /dev/null: a background job that reads the terminal (vite's "press h" shortcuts)
# gets suspended by the shell and then hangs every request while still holding its port.
GAZE_TOKEN=$TOKEN GAZE_PORT=$AGENT_PORT uv run scripts/fake_agent.py --delay 0.6 --quiet </dev/null &
AGENT_PID=$!
(cd overlay && exec ./node_modules/.bin/vite src/renderer --port "$VITE_PORT" --strictPort --host 127.0.0.1 --clearScreen false) </dev/null &
VITE_PID=$!

# Open the page only once vite answers, so the browser never races the server.
i=0
until curl -fs -o /dev/null "http://127.0.0.1:$VITE_PORT/"; do
  i=$((i + 1))
  if [ "$i" -gt 100 ] || ! kill -0 "$VITE_PID" 2>/dev/null; then
    echo "vite did not start" >&2
    exit 1
  fi
  sleep 0.2
done

echo
echo "Browser PREVIEW: fake agent. Scripted suggestions and results; no OpenAI, no desktop actions."
echo "Overlay:  $URL"
echo "Options:  &bg=busy|light|dark|none   &gaze=webgazer&camera=denied (permissions checklist)"
echo "Press Ctrl+C to stop both servers."
[ -n "${NO_OPEN:-}" ] || open "$URL"
wait
