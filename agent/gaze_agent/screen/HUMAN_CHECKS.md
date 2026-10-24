# Lane A: human desktop checks

These commands are prepared for the human. No live desktop check has been run
by the coding agent. Run from this checkout's root, in the stage terminal.
Grant Accessibility and Screen Recording to that terminal, then relaunch it.
Use the fake Sam Rivera persona and team-controlled test accounts only.

## Configuration and remaining work in other lanes

The ignored `.env` now has `gpt-6.1-sol` for `OPENAI_MODEL_AGENT`,
`OPENAI_MODEL_FAST`, and `OPENAI_MODEL_VISION`.

The requested reasoning efforts are agent `xhigh`, fast `low`, vision `high`.
**They are not applied yet.** The current `llm.py` forwards only the model ID.
Its owner must add per-slot `reasoning={"effort": ...}` to the Responses request
and include effort in replay cache keys before recording the cache. Lane A has
not edited `llm.py`, prompts, the replay cache, or any frozen interface.

Official API reference: <https://developers.openai.com/api/docs/models/gpt-6.1-sol>.

The new `demo_*.json` runtime fixtures are synthetic, not recordings of the apps.
The human captures below are still needed. Lane C owns recording the replay
cache after the real workflows pass. Lane D owns the final rehearsal gate.

## B2: AX, OCR, and window-only capture

Put Messages in a demo conversation with its compose field focused. Paste a
command below into the stage terminal; the three-second delay lets you bring
Messages back to the foreground before inspection runs.

```sh
sleep 3
uv run --project agent python -m gaze_agent.screen --ax-only
```

Expected: `app Messages`, the correct window, at most 150 elements, a populated
`focused:` entry for the compose field, and a Send button or equivalent with its
description. Repeat with a Mail reply, the Deep Focus playlist in Music, and
Safari's demo ticket page. Safari should expose links, dates, quantity and Buy
through AXWebArea, or need the OCR fallback below.

With the target app frontmost again:

```sh
sleep 3
uv run --project agent python -m gaze_agent.screen
```

Expected: sparse AX is supplemented with `o... | text` OCR entries. Native
controls and the focused element remain available. A failed OCR attempt keeps
the usable AX list if the same window is still frontmost.

### Window changes during a read

AX and OCR now share one native window identity for each `get_screen()` call.
The check includes the process, AX window handle, title and bounds. Capture also
checks its window ID and bounds immediately before and after the capture call.
If a check detects a switch, move, resize or lost focused window, the read fails
with `window_changed, re-read`. It does not publish a mixed snapshot, and earlier
element IDs are invalidated. Start a new read once the intended window is stable.
An ordinary OCR failure still returns useful AX when the window has not changed.

Auto keeps its one-capture-attempt-per-minute limit. Its cached OCR boxes are
only reused for the same native window at the same bounds. A different window
with the same title, or a moved/resized window, gets AX only until the capture
budget allows a fresh image. Title-counter changes on the same window can still
reuse the cache.

These cases are tested with fake desktop APIs. The real Mac check is still
human-run: during a normal or forced-OCR read below, manually switch windows or
move the target. A detected change should produce the error above. A stable
follow-up read should describe just the newly selected window. Keep any real
output private until reviewed for demo-only content; no live pass is claimed.

To force the OCR path, including on an app with rich AX:

```sh
sleep 3
GAZE_FORCE_OCR=1 uv run --project agent python -m gaze_agent.screen --json
```

Expected: OCR boxes use screen coordinates, including the window offset. Check
that each `(x + width/2, y + height/2)` lands on its visible text. Repeat after
moving the window, on a Retina display, and on a secondary display if available.
OCR boxes must remain inside the target window.

In another terminal, start the overlay:

```sh
scripts/start.sh real
```

Use click mode (⌃⌥⌘D) if needed. Repeat forced OCR with the overlay visibly over
the target app. Expected: no overlay text in OCR; only the app's window is
captured. With multiple windows of the same app, repeat on each focused window.
An ambiguous match must not silently capture an arbitrary window. Panic stop:
⌃⌥⌘. (press again to show the overlay).

### Record AX trees for regression fixtures

Only record demo-persona content. Dumps contain window titles, URLs, labels and
descriptions; native handles are excluded. Keep raw dumps outside the repo until
reviewed. This command creates a fresh temporary directory:

```sh
export GAZE_AX_DUMPS="$(mktemp -d /tmp/gaze-lane-a.XXXXXX)"
```

For each command, use its delay to foreground the named app in the intended demo
state. The dump command reads AX only and does not take a screenshot.

```sh
sleep 3
uv run --project agent python -m gaze_agent.screen --dump-ax "$GAZE_AX_DUMPS/messages.json"
```

```sh
sleep 3
uv run --project agent python -m gaze_agent.screen --dump-ax "$GAZE_AX_DUMPS/mail.json"
```

```sh
sleep 3
uv run --project agent python -m gaze_agent.screen --dump-ax "$GAZE_AX_DUMPS/music.json"
```

```sh
sleep 3
uv run --project agent python -m gaze_agent.screen --dump-ax "$GAZE_AX_DUMPS/safari-tickets.json"
```

The destination must be new; an existing capture is never overwritten. Review
for demo-only content before handing dumps to lane A. Compaction can then be
reproduced without desktop access:

```sh
uv run --project agent python -m gaze_agent.screen --fixture "$GAZE_AX_DUMPS/messages.json" --json
```

Expected: the same compact elements and focus as the recorded AX inspection,
with a fresh snapshot ID. Lane A will turn reviewed human captures into fixtures
and regression tests; this has not happened yet.

## B3: TextEdit and clipboard preservation

Stop any previous real agent or overlay for this check. Start the agent in shell
1 with a free port and the ignored configuration loaded explicitly (the direct
server entry point does not load `.env` itself):

```sh
export GAZE_TOKEN=dev-token
export GAZE_PORT="$(uv run --project agent python -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
printenv GAZE_PORT
DEMO_MODE=1 GAZE_AUTO_AMBIENT=0 uv run --env-file .env --project agent python -m gaze_agent.server
```

In shell 2, set `GAZE_PORT` to the numeric value printed by shell 1, then run:

```sh
GAZE_TOKEN=dev-token uv run scripts/fake_overlay.py repl
```

Copy a known piece of demo text to the clipboard before selecting the task. In
the REPL:

```text
mode type
intent open TextEdit and type hello world
select 1
```

Expected: TextEdit opens, `hello world` appears, then exactly one terminal
`task_status` and `task_result{ok:true}`. Pasting manually elsewhere afterwards
must still yield the original clipboard content. Repeat with image or rich-text
clipboard content to check every pasteboard type. No implicit Return/Send is
performed by `type_text` without `submit:true`.

## B5: Screen Recording revocation

Keep the real agent and REPL running from B3. Type:

```text
perms
```

Expected initially: `screen_recording:true`. Manually revoke Screen Recording
for this terminal in System Settings, then type `perms` again. Expected on that
check: `screen_recording:false`, with no crash. Accessibility is reported
independently. If macOS requires a terminal restart, report that limitation
instead of marking this check passed. Restore the grant and relaunch the stage
terminal before further demo tests.

## D1–D4 integration and replay (human only)

```sh
REPLAY=record DEMO_MODE=1 scripts/start.sh real
```

From the overlay, exercise D1 (Messages send), D2 (Mail reply), D3 (Music or
Safari), and D4 (tickets). Confirm only demo recipients. D1/D2 must wait at Send;
STOP followed by a late confirm must never execute. D4 must ask about ambiguous
dates, fill quantity, and stop at Buy. In demo mode a Buy confirmation must be
a no-op.

After lane C has recorded the demo-persona replay cache and lane D is ready,
stop the previous processes and run:

```sh
REPLAY=replay DEMO_MODE=1 uv run --env-file .env scripts/rehearse.py
```

Expected: D1–D4 each PASS; D4 reaches Buy without purchasing. Repeat with Wi-Fi
off to establish offline replay. No replay cache or live pass is claimed by
lane A. Return the command output, app states, permission results and reviewed
AX dumps for any failed screen read.
