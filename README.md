# Gaze Copilot

Gaze Copilot is a macOS overlay for controlling apps with gaze dwell. Electron talks to a Python agent over an authenticated localhost WebSocket. The protocol is defined in [`protocol/messages.schema.json`](protocol/messages.schema.json).

## Start here: Stage 1 only

Follow [Human backend testing: Stage 1](.plans/backend-human-testing.md), then return the sanitized results and wait for review. Stage 1 checks tools, configuration presence and permissions; it starts no overlay, agent server or desktop task. Do not create, configure or switch to a `GazeDemo` account now.

The launch modes and later probes below are reference material, not permission to advance the human testing stages. Native launch, typing, clipboard, STOP, recipient delivery and complete desktop replay still require human verification. Fake tests and the five synthetic prompt recordings do not establish those results.

## Launch modes (later human-run reference; gated)

Run from the chosen checkout's root only after the relevant stage is explicitly given. The launcher needs Node satisfying `^22.22.2 || ^24.15.0 || >=26.0.0`, pnpm (CI uses 9.x), and uv. It installs JS packages; uv manages Python and agent dependencies. Use Python 3.12 for backend checks.

| Shell command | Behavior |
|---|---|
| `scripts/start.sh` or `scripts/start.sh preview` (alias `fake`) | Electron overlay + fake agent; scripted output, no OpenAI or desktop actions |
| `scripts/start.sh browser` | Browser UI + fake agent; scripted output, no OpenAI or desktop actions |
| `scripts/start.sh live` (alias `real`) | Real Python agent; OpenAI calls except in strict replay, and real desktop actions |
| `scripts/start.sh stop` | Stops leftover overlay, agents and dev servers from this checkout |
| `scripts/dev.sh` | Fake preview unless `GAZE_AGENT_CMD` selects a custom command, which may act on the desktop |
| Bare `pnpm dev` | With no launching-shell mode and no custom command in shell or `.env`, reports `No agent selected` and exits 1 |

The `start.sh` preview ignores `GAZE_AGENT_CMD`; its live mode also clears it. Electron reads `GAZE_AGENT_MODE` from the launching environment before loading `.env`, so a file setting cannot select live mode. Preview output is not a real API result.

For a later authorized overlay session, Ctrl+C in its launching terminal or ⌃⌥⌘Q quits. ⌃⌥⌘. sends STOP and hides/shows the overlay. ⌃⌥⌘D toggles click mode; ⌃⌥⌘M toggles mouse/eye tracking. Mouse-as-gaze is the launcher's default. After a crash, the cleanup command is `scripts/start.sh stop` in a shell at this checkout's root.

## Configuration and live-start checks

The coding assistant's model is independent of the app's configuration. Model IDs and reasoning effort are separate: the tracked `.env.example` requests `gpt-6.1-sol` in `OPENAI_MODEL_AGENT`, `_FAST` and `_VISION`, with `OPENAI_REASONING_EFFORT_AGENT=xhigh`, `_FAST=low`, `_VISION=xhigh`. These template values do not populate a missing private `.env` or shell setting. The key and prices in the template are empty.

The wrapper forwards effort separately to the Responses API and includes it in replay keys. Unset/empty effort uses the API default. Accepted effort strings are `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`; local acceptance does not prove a particular model/account supports them.

| Entry point | Configuration source and precedence |
|---|---|
| Electron launcher | Shell wins over `.env`, even when empty, for key/model/effort/`REPLAY`. `live` sets `DEMO_MODE=1` and `GAZE_SOURCE=mouse` when their shell values are unset **or empty**, ignoring their file values. |
| Direct `python -m gaze_agent.server` | Reads its process environment; does not load `.env`. A later shell recipe must supply settings explicitly, for example with uv's `--env-file`. |
| Synthetic live API checker | Loads `.env` without overriding the shell, forces `REPLAY=off` and ignores the private demo selector. Human-run and billed; gated in the [reference](agent/gaze_agent/screen/HUMAN_CHECKS.md). |
| Real rehearsal | Defaults to `REPLAY=replay`, forces demo mode and disables ambient Auto. Private selection must be exported in the shell; an unset/empty selector is pinned so `.env` alone cannot select a private persona. |

Live preflight checks make no OpenAI request. The shell requires a nonblank key unless `REPLAY=replay`; otherwise it prints `Nothing was started` and exits 1 before installation. Electron then checks key presence, all three model slots, effort strings, `REPLAY=off|record|replay` and `DEMO_MODE=0|1` before creating a window or agent. Errors name settings without printing values. These are local checks: an invalid key or unsupported model can still fail on the first API request. If the agent exits, the overlay shows `The agent stopped`; quit and restart after diagnosis.

The P04 private provider and P05/P08 server/rehearsal consumers are present in combined checkpoint `be0731d`. That is code availability, not approval of any private persona, recipients, folders or cache. Keep `GAZE_DEMO_CONFIG` unset during Stage 1. `DEMO_MODE=1` does not replace an existing profile.

## Shell versus interactive commands

`uv run scripts/fake_overlay.py repl --spawn` is a **shell** command that connects to its own fake agent on a free port. Inside its `>` prompt, use the following **REPL** commands. This is developer reference; Stage 1 does not need a REPL.

| REPL command | When to use it |
|---|---|
| `select N` | Select a displayed plan, suggestion or recovery card (positive, 1-based number). Cancel/Other cards stay local. |
| `choose N` or `choose cancel` | Answer a pending `CHOICE` request only. |
| `confirm no` / `confirm yes` | Cancel / approve the pending confirmation. On a real agent, approval may execute the action. |
| `stop` | Stop the active task, including a pending choice/confirm. |
| `help` / `quit` | Show commands / leave the REPL. |

Do not type the literal `N` or the displayed `>`; use the displayed number. A bare number is not a command. `select` and `choose` are not interchangeable.

## Rehearsal and replay distinctions (gated)

`scripts/rehearse.py` defaults to **real**, including without `--target`; `--target real` does too. Both automatically confirm Send in D1/D2. `fake_overlay.py demo` also automatically confirms Send when connected to a real agent. The REPL requires manual confirmation. Use `--target fake` or `demo --spawn` for fake-only checks; the word `fake` in the client filename does not make its connected agent fake.

`DEMO_MODE=1` still acts on apps and permits approved Sends; confirmed BUY is a no-op, and real rehearsal stops at BUY without confirming it. Strict `REPLAY=replay` makes zero OpenAI calls and fails on missing/invalid entries, but still performs real desktop actions. Messages, Mail, websites and streaming may require network services. A completely offline demo is a separate, unverified requirement. The five shipped synthetic prompt responses are not a complete desktop recording.

Recommend English for initial recommendations, plans and controlled tests. Preserve exact message meaning, names, approved message text and observed native labels; do not translate an outgoing message to make a test pass.

## Developer fake checks

These shell commands use fakes and temporary test storage; they do not unlock human stages. Run from this checkout's root, with desktop/API entry points guarded in tests:

```sh
env -u GAZE_DEMO_CONFIG UV_NO_ENV_FILE=1 PYTHON_DOTENV_DISABLED=1 uv run --project agent --python 3.12 pytest agent/tests scripts/tests --tb=short
env -u GAZE_DEMO_CONFIG UV_NO_ENV_FILE=1 PYTHON_DOTENV_DISABLED=1 uv run scripts/fake_overlay.py demo --spawn
env -u GAZE_DEMO_CONFIG UV_NO_ENV_FILE=1 PYTHON_DOTENV_DISABLED=1 uv run scripts/rehearse.py --target fake
sh scripts/check_secrets.sh
git diff --check
```

Expect pytest exit 0, 11 protocol-flow PASS lines, nine fake-rehearsal PASS lines, `Secret scan passed.` and a clean diff check. Ctrl+C interrupts; spawned fake servers are cleaned up by the harness. Return only counts, exit codes and sanitized failures. If uv cannot reach the network, retry with `uv run --offline` and report a remaining dependency failure. The secret scan covers tracked and non-ignored new files; no private environment, raw AX, clipboard data or real contact handles belong in reports.
