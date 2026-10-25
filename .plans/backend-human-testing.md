# Human backend testing: Stage 1

Only Stage 1 is unlocked here. The next agent must wait for the human's results
before giving Stage 2. The goal now is backend diagnosis and fixes, not a demo.
The `GazeDemo` Mac account is a future user-managed plan, not a prerequisite to
create now and not something the agent may configure automatically.

## Prerequisites and terminal

Use the same Mac Terminal app that will run the later backend checks. Call one
window **Terminal A**; another window of the same app will later be **Terminal B**.
Do not paste sensitive AX output or keys into either test window. Stop any old
client with `quit` and its server with Control+C in its launching terminal.

Open Terminal A at the current workspace's repository root using the exact
`cd` command supplied in the agent's reply; do not reuse an older workspace path.
The personal checkout path is deliberately kept out of this tracked guide.
Every command in this stage is a **shell command in Terminal A**, not a command
for the interactive overlay's `>` prompt. The checkout starts at `3938bbc`;
backend stabilization edits may be present without a new commit.

## 1. Check the tools and checkout

```sh
git branch --show-current
git log -1 --format='%h %s'
node --version
pnpm --version
uv --version
```

PASS: the expected delivered checkpoint is present, all three tools print
versions, Node satisfies the repository's engines (22.22.2+ within 22, 24.15+
within 24, or 26+), and pnpm is 9.x as used in CI. Missing tools or mismatched
code are a stop/report condition, not a reason to run the app anyway. A new
terminal/account may have a different PATH even if an earlier terminal worked.

These commands print repository/tool metadata, not environment values or keys.

## 2. Check Python and sanitized configuration

```sh
uv sync --project agent --python 3.12 --frozen
git check-ignore .env
```

The sync may download dependencies. It should finish successfully; the second
command should print `.env`. That confirms the ignore rule, not file existence.

Paste this whole block in Terminal A. It reads configuration locally and prints
only presence, approved setting values or comparison status, never the key:

```sh
uv run --project agent --python 3.12 python - <<'PY'
import getpass
import os
from pathlib import Path
from dotenv import dotenv_values

file_settings = dotenv_values(".env")
settings = {**file_settings, **os.environ}
print("Account short name matches GazeDemo:", getpass.getuser().casefold() == "gazedemo")
print(".env:", "FOUND" if Path(".env").is_file() else "MISSING")
print("API key in .env:", "SET" if file_settings.get("OPENAI_API_KEY") else "MISSING")
print("API key in shell:", "SET" if os.getenv("OPENAI_API_KEY") else "UNSET")
print("Shell settings take precedence over .env.")

for slot in ("AGENT", "FAST", "VISION"):
    name = f"OPENAI_MODEL_{slot}"
    value = settings.get(name)
    status = "MISSING" if not value else (
        "MATCHES SHIPPED RECORDINGS" if value == "gpt-6.1-sol"
        else "SET; DIFFERS FROM SHIPPED RECORDINGS")
    print(f"{name}: {status}")
    name = f"OPENAI_REASONING_EFFORT_{slot}"
    value = (settings.get(name) or "").strip()
    allowed = {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
    print(f"{name}: {value if value in allowed else 'UNSET; API default' if not value else 'INVALID; value hidden'}")

for name, default, allowed in (
    ("REPLAY", "off", {"off", "record", "replay"}),
    ("DEMO_MODE", "0", {"0", "1"}),
    ("DEBUG", "0", {"0", "1"}),
    ("GAZE_AUTO_AMBIENT", "0", {"0", "1"}),
    ("GAZE_SOURCE", "webgazer", {"webgazer", "mouse"}),
):
    value = settings.get(name, default)
    print(f"{name}: {value if value in allowed else 'INVALID; value hidden'}")
print("GAZE_AGENT_CMD:", "SET; contents hidden" if settings.get("GAZE_AGENT_CMD") else "UNSET")
PY
```

PASS for configuration presence: `.env` exists and is ignored, its key is set,
all three model slots are set, and no setting is invalid. A different model or
effort is a review item, not proof that the model is unsupported. Shipped synthetic
recordings use Agent xhigh, Fast low, Vision xhigh with the displayed model ID;
they do not prove full desktop replay. Presence does not verify live API access.
`Account short name matches GazeDemo: False` is expected in the current account;
do not create, configure or switch Mac users for this stage.

If `.env` is missing, report that without copying it from another worktree or
posting a key. Leave the active profile and demo settings unchanged while the
configuration is reviewed. No OpenAI call occurs in these checks regardless of
the printed REPLAY/DEMO_MODE settings.

## 3. Check Mac permissions without capturing anything

Run in Terminal A yourself:

```sh
uv run --project agent --python 3.12 python -c 'import json; from gaze_agent.permissions import check; print(json.dumps(check(), indent=2))'
```

PASS: `accessibility` and `screen_recording` are true. Backend `camera: unknown`
is expected; it is not a camera permission test. Initial backend mouse/CLI tests
do not require eye tracking. Record actual camera setup as pending until tested
through Electron later.

If Accessibility is false, this human-run command opens its settings pane:

```sh
uv run --project agent --python 3.12 python -c 'from gaze_agent.permissions import open_settings_pane; open_settings_pane("accessibility")'
```

Enable the actual Terminal app used for this test. If Screen Recording is false:

```sh
uv run --project agent --python 3.12 python -c 'from gaze_agent.permissions import open_settings_pane; open_settings_pane("screen_recording")'
```

This requests Screen Recording permission and opens its pane; it does not take
a screenshot. Enable the same Terminal app. If macOS requests a restart, finish
any work, quit/reopen that app, return to this workspace and repeat the check.
Do not assume a different terminal app or the future GazeDemo account has the
same grants. The coding agent must not run these native checks itself.

## What will happen, stop and cleanup

This stage starts no agent server, overlay, desktop task or rehearsal, and changes
no profile. Leave `GAZE_DEMO_CONFIG` (the new private demo manifest selector for
issue #5) unset: it is not part of Stage 1. Do not set it until the server and
rehearsal use it and the private persona/recipients are agreed in a later stage. Only dependency installation and human-chosen permission changes may
persist. Control+C interrupts a command; no app automation process needs stopping.
Close System Settings when finished. Keep permissions for later tests, or turn
them off manually in the same panes if abandoning the test.

There are **zero OpenAI calls**. Downloads may still use the internet. A future
strict-replay run can also make zero OpenAI calls while sending real messages or
using online sites/services, so it is not automatically a completely offline demo.

Do not run the rehearsal or scripted desktop flows during this stage.
`scripts/rehearse.py` defaults to **real**, and both that default and
`--target real` automatically confirm Send in D1/D2. `fake_overlay.py demo` also
automatically confirms Send when connected to a real agent. The REPL requires
manual confirmation. Only `--target fake` and `demo --spawn` use fakes.
`DEMO_MODE=1` still allows desktop actions. Strict `REPLAY=replay` makes zero
OpenAI calls and fails on a miss, but still performs real app actions; Messages,
Mail, websites and streaming may need network access. A completely offline demo
is a separate, still unverified requirement.

## Results to send back

- Branch/commit and the three tool versions.
- Python sync success or its sanitized error, and whether `.env` was printed.
- The diagnostic output above, reviewed for secrets before sending.
- The final permission JSON and camera status marked untested/pending as needed.

Never send `.env` contents, a full environment dump, raw AX output, a screenshot
of private windows, clipboard contents, personal contact handles or the full
terminal history. The agent must wait here and resolve Stage 1 failures before
giving the next stage. Later stages remain the ordered sequence in the handoff.
