# Gaze Copilot

Gaze Copilot is a macOS overlay for controlling apps with gaze dwell. The Electron overlay talks to a Python agent over a localhost WebSocket. The protocol is defined in [`protocol/messages.schema.json`](protocol/messages.schema.json).

## Quick start

Needs Node 24 (or 22.22+), `pnpm` and `uv`; the script tells you how to install whichever is missing.
It installs the JS packages itself, and `uv` fetches Python and its packages on first use.

```sh
git pull
scripts/start.sh            # PREVIEW: Electron overlay + fake agent (no OpenAI key, no desktop actions)
scripts/start.sh live       # LIVE: Electron overlay + the real agent (calls OpenAI; really clicks and types)
scripts/start.sh browser    # PREVIEW: overlay UI in your browser + fake agent
scripts/start.sh stop       # stop leftovers started from this checkout (overlay, agents, dev servers)
```

`scripts/start.sh` alone is the preview (also `preview` or `fake`); `real` is an alias of `live`. Bare `pnpm dev` starts no
agent and tells you to pick a mode. Ctrl+C in that terminal or ⌃⌥⌘Q quits. Hotkeys: ⌃⌥⌘. STOP and
hide/show the overlay, ⌃⌥⌘D click mode (selection by real clicks instead of dwell; STOP still dwells),
⌃⌥⌘M mouse ↔ eye tracking. The mouse is the gaze by default: hovering a card selects it.

Live-start checks (they print variable names, never values, and make no OpenAI call):

1. Before installing or starting anything, `live` needs `OPENAI_API_KEY` in the shell or `.env`
   (not with `REPLAY=replay`, which answers from the cache only). Otherwise: "Nothing was started", exit 1.
2. Before any window or agent, Electron checks again: the key (same rule), `OPENAI_MODEL_AGENT`, `_FAST` and
   `_VISION`, valid `OPENAI_REASONING_EFFORT_*` (none, minimal, low, medium, high, xhigh, max),
   `REPLAY` (off, record, replay) and `DEMO_MODE` (0, 1). Any problem is listed and it exits 1.

A variable set in the shell, even empty, wins over `.env`. `live` uses `DEMO_MODE=1` and
`GAZE_SOURCE=mouse` unless the shell sets them; their `.env` values are ignored. A wrong key or model
name still passes these checks and shows up as a model error on the first request. If the agent
exits, the overlay shows "The agent stopped": quit and start again.

## Local setup

- Python 3.12 and `uv` manage the agent and the fake harness.
- Node 24 (or 22.22+) and `pnpm` are used by the Electron overlay; the overlay tests need it (jsdom 30).
- Put `OPENAI_API_KEY` and the model settings in a local `.env`. Keep `.env` private; `.env.example` is the tracked template.
- In development, macOS Accessibility, Screen Recording, and Camera permissions belong to the terminal app that launches the app. Grant them to that terminal, then quit and relaunch the terminal before checking permissions again.

## Work against the fakes

The fake agent does not use OpenAI or access macOS apps. It uses the fictional demo persona in [`fixtures/demo_profile.json`](fixtures/demo_profile.json), validates WebSocket messages against the protocol schema, and never performs real purchases.

```sh
# Run D1–D4 and the lifecycle/recovery protocol flows using an ephemeral port.
uv run scripts/fake_overlay.py demo --spawn

# Start an interactive overlay-side client against a fake agent.
uv run scripts/fake_overlay.py repl --spawn

# Run the Task D rehearsal gate against a fake agent. D4 stops at BUY confirm.
uv run scripts/rehearse.py --target fake

# Run the overlay against the fake agent once the Node workspace is installed
# (GAZE_AGENT_CMD=<command> runs that command as the agent instead).
scripts/dev.sh

# Or only the overlay UI in your browser (mouse = gaze, free ports, opens when ready).
# Ctrl+C stops both servers; `scripts/dev-browser.sh stop` clears leftovers from this checkout.
scripts/dev-browser.sh
```

The interactive client accepts `intent`, `select`, `choose`, `confirm`, `stop`, `mode`, `refresh`, `profile`, and `perms`. Enter `help` for the full command list.

## Stage rehearsal

The real rehearsal starts the Python agent with `REPLAY=replay` and `DEMO_MODE=1`, then drives it with the CLI harness. It verifies that the agent reports demo mode and the fixture profile before sending any tasks. It runs D1–D3 through their demo actions and stops D4 at the BUY confirm without answering it. Run this only from the stage terminal after Tasks A, B, and C are integrated and the replay cache is recorded with the demo persona:

```sh
REPLAY=replay DEMO_MODE=1 uv run scripts/rehearse.py
```

When developing or rehearsing manually, use only the demo persona and test flows. Never put real contact details or other personal profile data in fixtures or replay files.

## Checks

```sh
uv run --project agent pytest agent/tests scripts/tests
uv run scripts/fake_overlay.py demo --spawn
scripts/check_secrets.sh
```

`scripts/check_secrets.sh` scans tracked and non-ignored files for secret-like API key markers. Replay files under `agent/replay/cache/` are intentionally tracked and must contain demo-persona data only.
