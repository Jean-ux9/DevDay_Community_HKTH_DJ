# Human backend testing: Stage 1

**Only sections 1–3 of Stage 1 are unlocked.** Return their sanitized results
and wait for review before any later probe, including the optional billed API
check. Do not launch an overlay/server, inspect a screen, type into apps, send,
record or rehearse during this stage. Do not create, configure or switch to a
`GazeDemo` Mac account. No profile, recipient or private cache is approved here.

This guide was source-checked against combined checkpoint `be0731d` (P05/P08
included). A checkpoint is not evidence that native or live tests passed.

## Prerequisites and terminal

Use the Mac Terminal app intended for later backend tests. Call its window
**Terminal A**. Stop a known old REPL with `quit` at its `>` prompt and its
server with Control+C in the shell that launched it. Do not start either now.

Open Terminal A at the current workspace's repository root with the exact `cd`
command supplied in the handoff. Do not reuse an older workspace path. Personal
checkout paths are deliberately absent from tracked docs. Every code block
below is a **shell command in Terminal A**, never input for a REPL `>` prompt.
Use the delivered checkout named in the handoff; do not switch branches or pull
over local work as part of this diagnostic.

## 1. Check the tools and checkout

```sh
git status --short --branch
git log -1 --format='%h %s'
node --version
pnpm --version
uv --version
```

PASS: the branch/commit matches the handoff, existing changes are understood,
and all three tools print versions. Node must satisfy the repository's engines:
22.22.2+ within 22, 24.15+ within 24, or 26+. CI uses pnpm 9.x. Missing tools,
unexpected changes or mismatched code are stop/report conditions. A new terminal
or account can have a different PATH. These commands print metadata, not keys.

## 2. Check Python and sanitized configuration

```sh
uv sync --project agent --python 3.12 --frozen
git check-ignore .env
```

PASS: sync finishes successfully and the second command prints `.env`.
Sync may download Python/dependencies. The ignore check does **not** establish
that the file exists. If network access fails, retry sync with
`uv sync --offline --project agent --python 3.12 --frozen`; report any remaining
dependency failure without installing Python manually.

Paste this entire block into Terminal A. It reads local configuration only in
your human-run process. It never prints the key, custom commands, paths or
private selector contents, and it does not open any profile or manifest:

```sh
uv run --project agent --python 3.12 python - <<'PY'
import os
from pathlib import Path
from dotenv import dotenv_values

# Literal .env values, matching Electron's lack of variable expansion.
# If your file uses ${...} references, report that fact privately for review:
# Python dotenv helpers can expand them differently from Electron.
file_settings = dotenv_values(".env", interpolate=False)
settings = {**file_settings, **os.environ}

def present(value):
    return bool(value and value.strip())

print(".env:", "FOUND" if Path(".env").is_file() else "MISSING")
print("API key in .env:", "SET" if present(file_settings.get("OPENAI_API_KEY")) else "MISSING")
print("API key in shell:", "SET" if present(os.getenv("OPENAI_API_KEY")) else "UNSET/EMPTY")
print("Effective API key:", "SET" if present(settings.get("OPENAI_API_KEY")) else "MISSING")
print("View: shell over literal .env; not a server launch or API access check.")

allowed_efforts = {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
for slot in ("AGENT", "FAST", "VISION"):
    name = f"OPENAI_MODEL_{slot}"
    value = settings.get(name)
    status = "MISSING" if not present(value) else (
        "MATCHES TEMPLATE" if value == "gpt-6.1-sol" else "SET; DIFFERS FROM TEMPLATE")
    print(f"{name}: {status}")
    name = f"OPENAI_REASONING_EFFORT_{slot}"
    value = (settings.get(name) or "").strip()
    status = value if value in allowed_efforts else (
        "UNSET/EMPTY; API default" if not value else "INVALID; value hidden")
    print(f"{name}: {status}")

for name, default, allowed in (
    ("REPLAY", "off", {"off", "record", "replay"}),
    ("DEMO_MODE", "0", {"0", "1"}),
    ("DEBUG", "0", {"0", "1"}),
    ("GAZE_AUTO_AMBIENT", "0", {"0", "1"}),
    ("GAZE_SOURCE", "webgazer", {"webgazer", "mouse"}),
):
    value = settings.get(name, default)
    print(f"{name}: {value if value in allowed else 'INVALID; value hidden'}")
for name in ("GAZE_AGENT_CMD", "GAZE_AGENT_MODE", "GAZE_DEMO_CONFIG"):
    print(f"{name}: {'SET; contents hidden' if settings.get(name) else 'UNSET/EMPTY'}")
names = ["OPENAI_API_KEY", "REPLAY", "DEMO_MODE", "GAZE_SOURCE", "GAZE_DEMO_CONFIG"]
names += [f"OPENAI_{kind}_{slot}" for kind in ("MODEL", "REASONING_EFFORT")
          for slot in ("AGENT", "FAST", "VISION")]
print("Shell overrides file for:", ", ".join(n for n in names if n in os.environ) or "none")
for name, default in (("DEMO_MODE", "1"), ("GAZE_SOURCE", "mouse")):
    value = os.getenv(name) or default
    allowed = {"0", "1"} if name == "DEMO_MODE" else {"mouse", "webgazer"}
    print(f"Later start.sh live {name}: {value if value in allowed else 'INVALID; value hidden'}")
PY
```

PASS for future live configuration presence: the **effective** key and all
three model slots are set, no setting is invalid, and any custom selection is
reviewed. A shell-only key is valid; `.env` need not exist when the shell supplies
everything. An empty shell variable overrides a populated file value. Missing
credentials do not block fake work; report them without copying private files
from another workspace, inventing values or posting a key. Leave settings as-is
for review. Keep `GAZE_DEMO_CONFIG` unset for Stage 1; if reported SET, stop for
review without opening the manifest or sharing its value.

Model IDs and reasoning effort are separate settings. `.env.example` requests
`gpt-6.1-sol` in all three slots, Agent/Vision `xhigh` and Fast `low`; it is a
template, not runtime defaults. Effort is forwarded separately and affects replay
keys. Unset/empty effort uses the API default. Another model/effort is a review
item, not proof of unsupported access. This coding assistant's selected model
does not change the application's model.

This diagnostic shows shell-over-file values for review. Electron loads `.env`
without overriding the shell; `start.sh live` additionally uses a nonempty shell
`DEMO_MODE`/`GAZE_SOURCE` or defaults to `1`/`mouse`, ignoring their file values.
The direct server does not load `.env` itself. The later API checker uses Python
dotenv; real rehearsal loads the child's file but pins its selector from the
shell. Do not treat these entry points as interchangeable. Literal `${...}` file
references need review because loaders differ. Presence proves neither API
authentication, credits, model access nor complete replay coverage. No API call
occurs here, whatever `REPLAY`/`DEMO_MODE` reports.

## 3. Check Mac permissions without capturing anything (human-run only)

In Terminal A yourself:

```sh
uv run --project agent --python 3.12 python -c 'import json; from gaze_agent.permissions import check; print(json.dumps(check(), indent=2))'
```

PASS: `accessibility` and `screen_recording` are true. Backend `camera: unknown`
is expected; it is not a camera test. Eye tracking and Electron camera setup
remain pending. The check does not prompt or capture anything.

If Accessibility is false, this human-run shell command opens its settings pane:

```sh
uv run --project agent --python 3.12 python -c 'from gaze_agent.permissions import open_settings_pane; open_settings_pane("accessibility")'
```

Enable the actual Terminal app used here. If Screen Recording is false:

```sh
uv run --project agent --python 3.12 python -c 'from gaze_agent.permissions import open_settings_pane; open_settings_pane("screen_recording")'
```

This requests permission and opens its pane; it takes no screenshot. Enable the
same terminal app. If macOS requests a restart, finish work, quit/reopen that
app, return to this checkout and repeat the permission check. Do not infer grants
for another terminal or a future Mac account. Coding agents must not run any
of these permission commands themselves.

## Stop, cleanup and results to return

Control+C interrupts a running command. Stage 1 starts no automation server or
overlay to clean up. Close System Settings afterward. Dependency installation
and human-chosen permission changes may persist. Keep the grants for later tests,
or remove them manually in the same panes if abandoning the tests. Stage 1 makes
**zero OpenAI calls**; dependency downloads may use the internet.

Return only:

- Branch/commit, understood dirty-file names, and Node/pnpm/uv versions.
- Python sync success or sanitized failure, and whether ignore checking printed `.env`.
- The diagnostic's sanitized output after reviewing it for secrets; no actual values beyond its approved statuses.
- Final permission JSON; camera marked pending, and any terminal restart needed.

Never send `.env`, environment dumps, raw AX, screenshots, clipboard contents,
personal paths/handles, response histories or full terminal transcripts.

**Stop here and wait for review.** The [later-probe reference](../agent/gaze_agent/screen/HUMAN_CHECKS.md)
does not unlock anything. The order remains profile backup/agreement, harmless
AX/OCR, separate TextEdit launch and document/typing/clipboard/STOP tests,
Cancel-first app flows, then approved sends and later recording/rehearsal. The
optional synthetic live API check is also gated on returned Stage 1 results and
explicit human authorization; it cannot establish desktop success.

Remember: real/default rehearsal and scripted `fake_overlay.py demo` against a
real agent auto-confirm Send. REPL confirmation is manual. `DEMO_MODE=1` still
acts. Strict replay makes zero OpenAI calls and fails on a miss, but acts on real
apps and may use network services. Completely offline behavior is unverified.
