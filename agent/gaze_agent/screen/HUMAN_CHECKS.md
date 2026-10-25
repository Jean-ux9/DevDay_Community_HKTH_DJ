# Lane A: human desktop checks

These commands are prepared for the human. No live desktop check has been run
by the coding agent. Run from this checkout's root, in the stage terminal.
Grant Accessibility and Screen Recording to that terminal, then relaunch it.
Use the fake Sam Rivera persona and team-controlled test accounts only.

## Configuration and remaining work in other lanes

Private `.env` files are not copied between workspaces. Check the local key's
presence without printing it; do not assume this checkout has any model settings.
The integrated `llm.py` supports optional `OPENAI_REASONING_EFFORT_AGENT`,
`OPENAI_REASONING_EFFORT_FAST`, and `OPENAI_REASONING_EFFORT_VISION`, and includes
effort in replay keys. The shipped synthetic recordings use `gpt-6.1-sol` for
all three model slots, with Agent `xhigh`, Fast `low`, and Vision `xhigh`.
See `agent/replay/README.md` for their exact scope and configuration. This is a
recording configuration, not a claim of live model access in the current shell.

The new `demo_*.json` runtime fixtures are synthetic, not recordings of the apps.
The human captures below are still needed. Backend lane B owns LLM recording
and replay; backend lane C owns the runtime and `scripts/rehearse.py`. Original
Task D owns the mock overlay/client. Raw screen contents, private contact handles,
and captured images must not be pasted into public issues or tracked fixtures.

## Launch/focus regression check (human-run; zero OpenAI calls)

The integration follow-up changes foreground detection to use the current AX
focused application, avoiding `NSWorkspace` foreground state that can remain
cached without a Cocoa main run loop. The launcher now resolves the app, calls
the system `open` command, and waits at most 10 seconds for its AX-focused window.
STOP interrupts its polling and terminates a stalled launcher. Keyboard chords
release keys in reverse order with the remaining modifier flags.

These changes are covered with fake native APIs; real Mac activation and event
delivery still require a human retest. A file-opening dialog counts as an app
window: launching TextEdit does not itself create a new document. Click New
Document or choose File > New when that is needed.

Stop an old client with `quit` and its server with Control+C so the next process
loads the edited code. From a fresh window of the permission-granted Terminal
app, in this checkout's root, run this yourself:

```sh
uv run --project agent --python 3.12 python - <<'PY'
from gaze_agent.actions import DesktopActions
from gaze_agent.screen.ax import front_window

DesktopActions({}).open_app("TextEdit")
app, _, _ = front_window()
assert app.bundleIdentifier() == "com.apple.TextEdit", "Focus changed after launch"
print("PASS: TextEdit is active. A document chooser is also valid.")
PY
```

This really opens/activates TextEdit. It reads app identity and whether a focused
window exists, but does not capture a screenshot, dump AX text, load the active
profile, or call OpenAI. Keep private windows out of the test. Report only PASS
or the error code; no document contents are needed. Control+C interrupts the
check; close a blank test document without saving for cleanup.

After this passes, restart the isolated blank-profile server before the live
TextEdit typing/clipboard test. Live task execution sends readable screen text
to OpenAI, and the explicit vision tool can send a window image. A zero-OpenAI
launch check is not evidence that a later complete app demo is offline.

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
