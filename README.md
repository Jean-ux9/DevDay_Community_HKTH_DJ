# Gaze Copilot

Gaze Copilot is a macOS overlay for controlling apps with gaze dwell. The Electron overlay talks to a Python agent over a localhost WebSocket. The protocol is defined in [`protocol/messages.schema.json`](protocol/messages.schema.json).

## Local setup

- Python 3.12 and `uv` manage the agent and the fake harness.
- Node 20+ and `pnpm` are used by the Electron overlay.
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

# Run the overlay against the fake agent once the Node workspace is installed.
scripts/dev.sh
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
