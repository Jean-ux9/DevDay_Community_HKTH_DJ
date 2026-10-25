# Human desktop checks: gated reference

**Nothing in this reference is unlocked.** Start with [Stage 1](../../../.plans/backend-human-testing.md),
return results and wait for one subsequent stage at a time. Coding agents must
not run permission commands, launch apps/overlays, read native AX/clipboard data,
type, click, post key events, capture screens, call the live API or rehearse real
apps. The commands below are human-only reference probes for later authorization.

Source checkpoint: `be0731d`, including P03, P04, P05, P07 and P08 integration.
Their fake evidence does not verify native desktop delivery. Do not configure
or switch to `GazeDemo`, copy private settings, approve placeholder recipients,
or activate private cache/profile configuration from this guide.

## Configuration and ownership

The tracked template and synthetic prompt recordings use `gpt-6.1-sol` for all
three model slots, with Agent `xhigh`, Fast `low`, Vision `xhigh`. A model ID is
separate from reasoning effort; `llm.complete` forwards effort as a Responses
parameter and includes it in the replay key. Unset/empty effort uses the API
default. These facts do not establish the current shell's key, model access or
private settings. Use only Stage 1's sanitized presence diagnostic.

Electron loads `.env` without overriding shell variables, even empty ones.
The live launcher supplies demo mode `1` and gaze source `mouse` for unset/empty
shell values, ignoring their file values. A direct server needs settings in its
environment; it does not load `.env`. Real rehearsal pins `GAZE_DEMO_CONFIG`
from its shell, even when empty, so a file-only selector cannot activate a private
persona. See the [README configuration table](../../../README.md#configuration-and-live-start-checks).

Backend lane A owns native screen/actions/profile/permissions; B owns LLM,
prompts/planning/policy and replay recording; C owns server/task loop/integration
and `scripts/rehearse.py`; original D owns mock overlay/client. Overlay A1/A2 are
separate. P09 edits only the three assigned guides and its optional report.

P04's provider/storage and P05/P08's runtime/rehearsal consumers are present:
the server shares the selected store and its approved contacts; rehearsal checks
the approved persona before preparing apps or requesting tasks. The old missing
consumer patch is no longer a code prerequisite. Human persona/recipient/folder
agreement, backup and native checks are still prerequisites. Keep the selector
unset until that later agreement; do not paste private manifest contents here.
`DEMO_MODE=1` seeds a missing public-demo profile; it does not replace an existing
one. Public fixture contacts are placeholders, not approved real recipients.

## Optional synthetic live API probe (locked)

Prerequisites: returned/reviewed Stage 1 results and explicit authorization for
the billed probe. Shell command in Terminal A, from this checkout's root:

```sh
uv run --project agent --python 3.12 python agent/replay/check_live_api.py --live
```

The successful path makes four uncached Fast-slot requests: planning, T9 decode
and Auto suggestions for English/German synthetic Mail screens. It loads `.env`
without overriding the shell, forces `REPLAY=off`, ignores the private selector
and uses the public fake persona. It does not read the desktop/active profile,
touch a replay cache or execute tools. Failure may stop before all four requests;
credits may already have been spent. Do not retry in a loop.

PASS: `PASS live API check: 4 uncached requests` plus each call's `cached:false`,
response-id prefix and positive input/output usage. The human must also judge
concise natural English, preserved names (`Taylor Swift`, `Ticketmaster`, `Alex`,
`Mom`), exact message meaning/text and native labels such as `Antworten`.
Generated task questions/summaries are not proven English by this Fast-slot
probe. `FAIL:`/`SETUP FAILURE:` means stop/report. Without `--live` it prints
`NOT RUN`, exits 2 and makes no API call or `.env` read.

Control+C interrupts; no desktop/server cleanup is needed. Return the synthetic
output and wording judgement after reviewing it for secrets/custom settings;
redact any custom model/effort value if private. This validates only the exercised
Fast-slot requests, not Agent/Vision access or desktop success.

## Separate TextEdit launch probe for #6 (locked; zero OpenAI)

Prerequisites: the earlier human stages have been reviewed, the human explicitly
authorizes this probe, the actual terminal has Accessibility permission, and
private windows are out of the test. Stop known old clients/servers first. Use
Terminal A at this checkout's root; this is a shell block, not REPL input:

```sh
uv run --project agent --python 3.12 python - <<'PY'
from gaze_agent.actions import DesktopActions
from gaze_agent.screen.ax import front_window

DesktopActions({}).open_app("TextEdit")
app, _, window = front_window()
assert app.bundleIdentifier() == "com.apple.TextEdit" and window is not None, "Focus changed after launch"
print("PASS: TextEdit is active. A document chooser is also valid.")
PY
```

This really launches/activates TextEdit. `open_app` uses `/usr/bin/open` with a
10-second overall polling deadline; readiness requires launcher success and the
target's AX-focused window. Foreground observation uses AXFocusedApplication.
STOP cancellation and ordered key release are covered with fakes, not verified
here. This standalone probe has
no REPL or overlay STOP control; Control+C interrupts it. It reads app/window
identity only: no screenshot, AX text dump, profile load or API call.

PASS is the printed line and the target app/window active. An Open dialog is a
valid launch result. **Launch does not create a document.** A later authorized
test must separately choose New Document/File > New, verify `hello world` in a
blank unsaved document, test clipboard preservation and STOP. Do not infer these
from launch PASS, fake tests or recovery `Show me the screen` returning `ok:true`.
Return only PASS or a sanitized error; close a blank test document without saving
and quit the test app if it is no longer needed. Stage Manager as the earlier
failure's cause remains an unconfirmed hypothesis.

## Later native stages: acceptance reference, still locked

The next agent must supply a stage-specific shell recipe only after the prior
results and approved isolated storage/configuration are agreed. This reference
deliberately provides no ready-to-run server/send/recording recipe.

| Later stage | Prerequisites and evidence to establish |
|---|---|
| Profile backup/agreement | Human-controlled backup and explicit isolated persona, recipients and private folders; no private config in Git or copied from another worktree. |
| Harmless AX/local OCR | Approved synthetic app content; correct app/window/focused control, at most 150 compact elements; OCR boxes include window offsets, stay in bounds and exclude overlay text. Switch/move/resize detection must reject mixed reads with `window_changed, re-read`; a stable reread must describe only the intended window. |
| Blank document/typing/clipboard/STOP | Separate from launch; harmless text visible, original clipboard preserved for each tested format, one terminal status/result; STOP/disconnect and late-confirm checks assessed separately. Do not copy logs before checking clipboard preservation. |
| Cancel-first app flows | Native layouts supported and confirmation details correct; use Cancel first. Changed app/window/focus/draft/recipient and unreadable context must block dispatch. |
| Controlled Sends | Explicit human approval of reachable team-controlled recipients, supported native fields and successful earlier stages; verify actual delivery separately. |
| Recording/rehearsal | Complete authorized desktop paths honestly recorded in the approved private namespace; synthetic prompt cache alone is insufficient. Offline requirements assessed separately. |

Recipient evidence in `screen/recipients.py` supports only synthetic-tested,
English, field-backed native composers: one exact To handle; Mail also requires
readable empty Cc/Bcc fields. Titles/aliases/body mentions cannot authorize Send.
Missing, group/token/display-name, hidden/unreadable, web/sheet or unsupported
layouts fail closed. Actual Messages/Mail layouts are unverified; do not bypass
the guard or assume an English recommendation translates native control labels.

In a later manual client session, Terminal A runs only the agreed isolated server;
Terminal B runs the supplied REPL shell command with the matching private token
and free port. At the REPL `>` prompt use `select N` for plan/suggestion/recovery
cards, `choose N`/`choose cancel` for a pending CHOICE, and `confirm no` to cancel
a pending confirmation. `confirm yes` can execute the real action. `stop` stops
the task; `quit` leaves the REPL, then Control+C in Terminal A stops its server.
Bare numbers are invalid; no shell command belongs at `>`. Report sanitized
outcomes, not the handshake/profile, confirmation handles or full transcript.

## Launch, replay and cleanup distinctions

Later shell entry `scripts/start.sh live` (alias `real`) uses the real agent;
no argument/`preview`/`fake` uses the fake agent, and `browser` is fake-only.
`DEMO_MODE=1` still performs real app actions and approved Sends. Confirmed demo
BUY is a no-op; rehearsal stops at BUY without confirming a purchase.

`scripts/rehearse.py` defaults to **real**; both default and `--target real`
auto-confirm Send in D1/D2. Scripted `fake_overlay.py demo` against a real agent
also auto-confirms Send. REPL confirmation is manual. Only `--target fake` and
`demo --spawn` ensure those harness runs use fakes. Strict `REPLAY=replay` makes
zero OpenAI calls and fails on missing/invalid cache entries, but still acts;
Messages, Mail, streaming and sites may need network services. Completely offline
desktop behavior remains unverified. Never infer native success from fake PASS.

For a later overlay session, ⌃⌥⌘. sends STOP and hides/shows; ⌃⌥⌘Q or Control+C
in its launching terminal quits. After a crash, run `scripts/start.sh stop` in a
shell at this checkout's root to clean up its leftover processes. Return only
sanitized per-probe results and failures. Raw AX dumps/captures, clipboard data,
private config/paths/handles and full human transcripts stay out of tracked docs
and public issues. Any requested fixture transfer needs separate reviewed,
demo-only data; no native fixture collection is unlocked now.
