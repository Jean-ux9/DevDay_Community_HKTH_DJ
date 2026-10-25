# Hackathon demo runbook: reusable action providers

Source-checked against combined revision `a2110f1` (H1 runtime, H2 launcher,
H3 Mail/Messages, H4 overlay). The fake scenario matrix below passes on that
revision; that is engineering evidence only, never native Mail, launcher or
gaze success. Writing this runbook does not unlock anything: no recording, no
real/default rehearsal (it auto-confirms Send), no `fake_overlay.py demo`
against a real agent (also auto-confirms Send) and no further billed API probes.

The coordinator gives the human **one block at a time** and waits for its
sanitized result before sending the next one.

## Facts from the combined code that shape the demo

- Structured providers dispatch only when the agent runs with
  `GAZE_AGENT_MODE=live` and `REPLAY=off`. Preview, replay and record never
  launch or send. `scripts/start.sh live` sets `GAZE_AGENT_MODE=live`.
- **Mail Send needs a selected private demo config.** The sender is the selected
  persona's `address.email`; recipients come only from its approved list. With
  `GAZE_DEMO_CONFIG` unset, `mail.send` reports `trusted_sender_required` and
  cannot send. The config requires `DEMO_MODE=1` (start.sh's default).
- **Messages Send uses Apple's Messages scripting**, pinned to the single enabled
  iMessage account (the script refuses before sending if there are none or several).
  Add e.g. `"TeamMessage": ["+15551234567"]` (E.164, no spaces, or an iMessage
  email) to both `persona.contacts` and `approved_recipients`. No SMS fallback.
- Apps: only Safari, Mail, Messages, TextEdit, Notes, Calendar. Links: `http(s)`
  only. "Completed" means the launcher/Mail accepted it, not that it was observed
  or delivered.
- A denied macOS Automation prompt for Mail returns a sanitized failure before
  any draft is sent. Any other unexpected script exit is reported as **unknown**:
  check Sent manually, never retry.

## Scenario matrix (fake integration, `agent/tests/runtime/test_connector_demo.py`)

Real server, Session composition, default registry, TaskLoop, safety gate and the
published H2/H3 providers. Fake edges only: model, planner, desktop, the
launcher's process spawn and Mail's send transport. Temporary selected config
with invented persona/handles. 24 cases, all PASS on `a2110f1`.

| # | Scenario | Expected and asserted |
|---|---|---|
| S1/S2 | Approved app (`textedit`) / `https` link | one exact `/usr/bin/open` argv; no confirm; result says "not observed" |
| S3 | `file:`, `javascript:`, credentials, `-a …`, control char, unapproved app, path | zero spawns, failed result |
| S4/S6 | Mail confirm: Cancel / Yes | confirm shows exact recipient, account, subject, body; nothing dispatched while waiting; Cancel → zero sends; Yes → exactly one osascript argv with that frozen payload; "delivery is not verified" |
| S5 | Unknown alias, phone-only alias for Mail, model-supplied `recipient`, `cc` | no confirm, zero sends |
| S7 | Stored destination changes while the confirm is shown | approval revoked, zero sends |
| S8/S9 | STOP / disconnect during confirm | zero sends; late Yes refused |
| S10 | Model repeats the identical send | one confirm, one send |
| S11 | Transport outcome uncertain; model retries same/altered send and opens Mail | result "unknown", no recovery plans, one send, nothing else dispatched |
| S11b | STOP after hand-off to transport | "unknown", transport cancelled, one send |
| S12 | `messages.send` | failed, no confirm, no spawn |
| S13 | `REPLAY=replay` or non-live mode | zero spawns |
| leak | S4/S6/S11 | recipient, sender and body absent from `task_result` and task log |

Not covered by fakes (human only): real launcher, Mail Automation permission,
actual delivery, overlay/gaze, camera.

## Per-laptop setup

**Laptop 2 (fakes only):** repo fetched at the combined revision, `uv`, Node/pnpm
for overlay tests. No `.env`, private config, recipients or caches; never copy
them from Laptop 1.

**Laptop 1 (demo machine):** the same plus, kept local and untracked: `.env` with
the OpenAI key; a private demo config manifest whose persona `address.email` is
the Mail account the human chose to send from and whose approved recipients
include the human's own test destination under the alias used on stage (e.g.
TeamMail). Its path is supplied only in the shell, never in tracked files.

## Human blocks (Laptop 1)

Use **Terminal A** at the repository root of the workspace named in the
handoff (the coordinator supplies the exact `cd`). Each block says **shell** or
**REPL `>` prompt**; never paste one into the other.

### Block 1. Checkout, tools and fake checks (shell, Terminal A)

```sh
git status --short --branch
git log -1 --format='%h %s'
uv --version
uv sync --project agent --python 3.12 --frozen
env -u GAZE_DEMO_CONFIG UV_NO_ENV_FILE=1 PYTHON_DOTENV_DISABLED=1 uv run scripts/fake_overlay.py demo --spawn
```

Expected: commit matches the handoff; sync succeeds (retry once with
`--offline` on network failure); all flows PASS, exit 0 (fake agent only).
Nothing stays running. Return: commit, sync ok/failed, PASS count.

### Block 2. Permissions and provider capability (shell, Terminal A)

```sh
uv run --project agent --python 3.12 python -c 'import json; from gaze_agent.permissions import check; print(json.dumps(check(), indent=2))'
```

Then select the private config **in this shell only** (path not shared) and
print which structured operations the agent would offer. This composes the same
registry as the server; it sends nothing, spawns nothing and prints no address:

```sh
export DEMO_MODE=1 GAZE_DEMO_CONFIG='<your private manifest path>'
uv run --project agent --python 3.12 python -c 'from gaze_agent import demo_config; from gaze_agent.tools.registry import default_registry; c = demo_config.selected(); r = default_registry(trusted_sender=c.persona().get("address", {}).get("email") if c else None); print("config selected:", c is not None); print("available:", r.capabilities()); print("unavailable:", r.unavailable)'
```

Expected: `accessibility`/`screen_recording` true (camera `unknown` is normal);
`config selected: True`; available includes `app.open`, `web.open`, `mail.send`;
unavailable is empty. A config error prints a sanitized
`Private demo config: …` message: stop and report it. Return: permission JSON
and the three printed lines. No paths, names or addresses.

### Block 3. Start the real agent (shell, Terminal B)

Open **Terminal B** at the same checkout. This agent can act on this Mac.

```sh
export DEMO_MODE=1 GAZE_AGENT_MODE=live REPLAY=off GAZE_DEMO_CONFIG='<your private manifest path>'
GAZE_TOKEN=demo-local uv run --project agent --python 3.12 --env-file .env python -m gaze_agent.server
```

Expected: `Gaze agent listening on 127.0.0.1:<port>`; note the port. A
`Gaze agent: Private demo config: …` line means it refused to start: report it.
Stop/cleanup: Control+C in Terminal B.

### Block 4. App, then link (REPL, Terminal A)

```sh
GAZE_TOKEN=demo-local GAZE_PORT=<port> uv run scripts/fake_overlay.py repl
```

At `>`: `intent open TextEdit`, then `select 1`. Expected: TextEdit opens; the
result says the launcher accepted it (not observed). Then
`intent open https://example.com`, `select 1`. Expected: the page opens in the
default browser. Stop: `stop` for a running task. Close the app/tab yourself.
Return per step: opened yes/no and result ok/summary text (no screenshots).

### Block 5. Mail Send Cancel (REPL, Terminal A)

At `>`: `intent email TeamMail saying the demo is starting`, then `select 1`.
Expected: a confirmation with Recipient, Provider `apple_mail`, Account, Subject
and Exact content. Check they are what you expect, then `confirm no`. Expected:
cancelled result. Check Mail's Sent mailbox: **zero new items**. Return: confirm
shown yes/no, fields correct yes/no, zero sends yes/no.

**Stop and wait for review.** Block 6 needs a separate explicit human approval
for one controlled send to the human's own test destination.

### Block 6. One controlled Mail send (REPL, Terminal A, separately approved)

Same intent and `select 1`; read the confirmation; `confirm yes` exactly once.
macOS may ask whether the terminal may control Mail: the human decides; denying
gives a failed result with nothing sent. Expected: result "Provider acknowledged
submission; recipient delivery is not verified", and exactly one item in Sent.
If the result is **unknown**, do not retry or repeat the intent: check Sent and
report. Return: result ok/summary and the Sent count; no content or address.
Then `quit` the REPL and Control+C Terminal B.

### Block 7. Gaze integration (shell, Terminal A)

Both previous processes stopped. Then:

```sh
export GAZE_DEMO_CONFIG='<your private manifest path>'
scripts/start.sh live
```

Repeat block 4 (app/link), then block 5 (Cancel only) by gaze/T9. The overlay
shows "Handed to the app" for an approved accepted send and "Not confirmed" for
an uncertain one (H4). A live send by gaze needs its own approval. Report
camera/eye tracking separately. Stop: Control+C; `scripts/start.sh stop` clears
leftovers.

## What to return (every block)

Only the requested statuses. Never send `.env`, environment dumps, the manifest
path, account names, addresses, phone numbers, message bodies, screenshots, AX
output, clipboard contents or full terminal transcripts.
