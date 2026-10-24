# Agent instructions: Gaze Copilot

An eye-controlled AI copilot for macOS: an Electron overlay (`overlay/`) talks to a Python agent (`agent/`) over a localhost WebSocket.

## Read first
- `.plans/gaze-copilot-spec.md`: the build spec. Section numbers (§4.4 etc.) are cited everywhere.
- `.plans/tasks.md`: Phase 0 plus four parallel tasks (A overlay, B agent server, C planner/prompts/safety, D harness). Each task lists the **files it owns**. Edit only files your task owns; if you need a change elsewhere, say so in your PR instead of making it.

## Rules
- **Never commit or push.** A human does that.
- **The WebSocket protocol is frozen.** The single source of truth is `protocol/messages.schema.json` (validate type `T` against `#/$defs/payload_T`). Follow the correlation and lifecycle rules in spec §4.1 and §4.4. Change the schema only when explicitly asked to; any schema change must update both mocks as well.
- **No secrets in tracked files.** The OpenAI key lives only in `.env` (git-ignored); `.env.example` stays empty. Fixtures and replay caches use the fake demo persona only.
- **No LLM prompt text in code.** Prompts live in `prompts/*.md`.

## Running the mocks
Python is managed by `uv`. Each script declares its Python version (3.12) and dependencies at the top, so `uv run` installs them by itself. Don't install Python manually, and don't use the system `python3`.

```sh
# Check the protocol end to end: starts a mock agent and runs every scripted flow
# (D1–D4, recovery, races, settings, bad input). Expect all PASS, exit code 0.
uv run scripts/fake_overlay.py demo --spawn

# Run selected flows against an agent that is already running (e.g. the real one)
GAZE_TOKEN=<token> GAZE_PORT=<port> uv run scripts/fake_overlay.py demo d1 stop_during_confirm

# Mock agent on its own (port 8765, token dev-token): for building the overlay
GAZE_TOKEN=dev-token uv run scripts/fake_agent.py [--delay 0.6] [--quiet]

# Interactive mock overlay (type `help` for commands)
uv run scripts/fake_overlay.py repl --spawn
```

| File | Role |
|---|---|
| `scripts/fake_agent.py` | Mock agent server: fake suggestions, plans, choices and confirms; enforces every §4.4 rule |
| `scripts/fake_overlay.py` | Mock overlay client: scripted `demo` flows (PASS/FAIL) and interactive `repl` |
| `scripts/gaze_client.py` | Overlay-side client library used by `fake_overlay.py` (§4.4 filtering) |
| `scripts/wsproto.py` | Envelope building, schema validation, merge-patch |

## Working in parallel (Superset workspaces)
Several agents (Codex and Claude Code) work at the same time, each in its own Superset workspace: a separate git worktree on its own branch, one per task in `.plans/tasks.md`.
- **Stay inside your workspace.** Don't read or edit other worktrees, and don't switch branches.
- **Don't hardcode port 8765.** Other workspaces may be using it. Prefer `demo --spawn` (it picks a free port). If you start `fake_agent.py` on its own, pick your own port: `GAZE_PORT=<free port>`.
- **`.env` may be missing in your workspace.** The mocks don't need it. If your task needs the OpenAI key and `.env` is absent, stop and say so; don't create or guess one.
- **No network in your sandbox?** Retry with `uv run --offline …`; the dependencies are usually already in the shared uv cache. If that also fails, report it instead of working around it.

## Before you finish
- Run `uv run scripts/fake_overlay.py demo --spawn` if you touched the protocol, the mocks or anything that speaks WebSocket. Report the output.
- Run your task's own tests (see its "Done when" in `.plans/tasks.md`).
- Report what was verified and what wasn't. Don't claim a check passed if you didn't run it.
