# Hackathon demo runbook: reusable action providers

Status: **draft, written before H1/H2/H3 landed.** Source-checked against
`origin/main` `79c8dde`. Steps marked **(needs H1/H3 handoff)** name commands or
switches that do not exist on `main` yet; the coordinator fills them in from the
merged lane reports before handing that step to a human. Writing this runbook
does not unlock anything: no recording, no real/default rehearsal (it
auto-confirms Send), no `fake_overlay.py demo` against a real agent (also
auto-confirms Send) and no further billed API probes.

The coordinator gives the human **one block at a time** and waits for its
sanitized result before sending the next one. Fake results never count as
native Mail, Messages, launcher or gaze success.

## Scenario matrix (fake integration, `agent/tests/runtime/test_connector_demo.py`)

Real runtime (`loop.py`/`server.py`/`safety.py` after H1 wiring), fake model,
fake providers that record `prepare`/`execute` calls, temporary selected
configuration with two invented aliases. Native/HTTP/process guards stay active.

| # | Scenario | Drive | Expected (assert on runtime-visible behaviour) |
|---|---|---|---|
| S1 | Approved app open | model calls `app.open {name}` for an approved app | one `execute` with the app-map target; `task_result` honest (launcher accepted, not "observed") |
| S2 | Approved `https` link | `web.open {url}` | one `execute` with the exact URL; no confirmation needed unless policy flags risk |
| S3 | Rejected link | `web.open` with `file:`, `javascript:`, credentials, control chars or `-`-prefixed value | zero `execute`; sanitized failure |
| S4 | Send Cancel | `mail.send {recipient_alias, subject, body}` → `confirm_request` → `confirm_response {confirmed:false}` | zero `execute`; `task_result` cancelled/honest |
| S5 | Unapproved destination | alias not in selected config, or model passes a raw handle/extra recipient | zero `prepare` side effects and zero `execute`; no confirm shown for it |
| S6 | Confirmed exact payload | Send confirmed | exactly one `execute`; `PreparedAction.payload` equals what the confirm showed (resolved destination, subject, body); no Cc/Bcc/attachments |
| S7 | Post-confirm mutation | destination/body/account/provider changes between confirm and dispatch | old confirmation revoked; zero `execute` of the mutated payload |
| S8 | STOP while waiting for confirm | `stop` during `confirm_request` | zero `execute`; later late `confirm_response` ignored (§4.4) |
| S9 | Disconnect while waiting | socket closes during confirm | zero `execute`; task cancelled |
| S10 | Duplicate request | model repeats the same send tool call / same `request_id` | at most one `execute` |
| S11 | Unknown outcome, no retry | fake `execute` times out or is cancelled after dispatch | status `unknown`; no second `execute`; no automatic fallback provider |
| S12 | Messages path | S4/S6 for `messages.send {recipient_alias, body}` | same guarantees as Mail |
| S13 | No leaks | any of the above | no raw receipt/stdout/handle/body in logs or model-visible results |

Not covered by fakes (human only): real launcher behaviour, Mail/Messages
Automation permission, actual delivery, overlay/gaze.

## Per-laptop setup

Laptop 2 (fakes only) needs: this repo fetched at the combined revision, `uv`,
Node/pnpm for overlay tests. No `.env`, profile, recipients or caches; do not
copy them from Laptop 1. Laptop 1 (demo machine) is the only machine that
runs anything below from block 2 on.

## Human blocks (Laptop 1, demo machine)

Use one Terminal window, called **Terminal A**, opened at the repository root of
the workspace named in the handoff (the coordinator supplies the exact `cd`;
personal paths stay out of this file). Every block says whether it is a
**shell** command or input at a **REPL `>` prompt**. Never paste one into the
other.

### Block 1. Checkout, tools and fake checks (shell, Terminal A)

```sh
git status --short --branch
git log -1 --format='%h %s'
uv --version
uv sync --project agent --python 3.12 --frozen
env -u GAZE_DEMO_CONFIG UV_NO_ENV_FILE=1 PYTHON_DOTENV_DISABLED=1 uv run scripts/fake_overlay.py demo --spawn
```

Expected: commit matches the handoff; sync succeeds (retry once with
`uv sync --offline ...` on network failure); every demo flow prints PASS and
exit 0. This uses the fake agent only. Stop: nothing stays running.
Return: commit, uv version, sync ok/failed, PASS count.

### Block 2. Permissions and provider capability (shell, Terminal A)

```sh
uv run --project agent --python 3.12 python -c 'import json; from gaze_agent.permissions import check; print(json.dumps(check(), indent=2))'
```

Expected: `accessibility` and `screen_recording` true (camera `unknown` is
normal here). Then the provider capability check **(needs H1/H3 handoff:
exact command that reports, without sending, whether the launcher, Mail
scripting and the optional `imsg` tool are available, and which account the
human selected)**. Missing tool or Automation permission must print a
sanitized setup failure, not a crash. Do not install tools or grant permissions
because of this step unless the human decides to. The first Mail/Messages
scripting call may show a macOS Automation prompt; the human chooses.
Return: the permission JSON and each provider as available / missing / denied.
No account names, addresses or handles.

### Block 3. Start the real agent (shell, Terminal B)

Open a second window, **Terminal B**, at the same checkout. **(needs H1
handoff: confirm this is still the launch path and which selected private
configuration it uses.)**

```sh
GAZE_TOKEN=demo-local uv run --project agent --python 3.12 --env-file .env python -m gaze_agent.server
```

Expected: `Gaze agent listening on 127.0.0.1:<port>`. Note the port. This agent
can act on this Mac. Stop/cleanup: Control+C in Terminal B.

### Block 4. App and link (REPL, Terminal A)

```sh
GAZE_TOKEN=demo-local GAZE_PORT=<port> uv run scripts/fake_overlay.py repl
```

At the `>` prompt type one intent, for example `intent open Calculator`, then
later `intent open https://example.com`. Expected: a plan or result, the app or
page opens, and the result text says it was launched (not that it was
verified). Stop: `stop` at the prompt for a running task; `quit` ends the REPL.
Close the opened app/tab yourself. Return: for each, opened yes/no and the
result state (completed/failed/unknown), no screenshots.

### Block 5. Send Cancel (REPL, Terminal A)

At the `>` prompt: `intent email TeamMail saying the demo is starting`.
Expected: a confirmation listing recipient alias resolution, subject and body.
Answer `confirm no`. Expected: cancelled result, **nothing sent**. The human
checks Mail's Sent mailbox and Messages for zero new items. Return: confirm
shown yes/no, fields shown matched the request yes/no, zero sends yes/no.

**Stop and wait for review.** The next block needs a separate explicit human
approval for one controlled send to the human's own test destination.

### Block 6. One controlled send (REPL, Terminal A, separately approved)

Same intent as block 5, read the confirmation, then `confirm yes` exactly once.
Expected: one sent item to the approved test destination; result `completed`
(provider acknowledged) or `unknown`. If `unknown`, **do not retry**; check Sent
manually and report. Never repeat the intent to "try again". Return: result
state and whether exactly one item appears in Sent; no content or address.
Repeat for TeamMessage only after a further approval.

### Block 7. Gaze integration (shell, Terminal A)

Quit the REPL (`quit`) and stop Terminal B (Control+C) first. Then
`scripts/start.sh live` per the H4 handoff. Repeat block 4, then block 5
(Cancel only) by gaze/T9. A live send by gaze needs its own approval.
Camera/eye tracking results are reported separately. Stop: Control+C;
`scripts/start.sh stop` clears leftovers.

## What to return (every block)

Only the requested statuses. Never send `.env`, environment dumps, account
names, addresses, phone numbers, message bodies, screenshots, AX output,
clipboard contents or full terminal transcripts.
