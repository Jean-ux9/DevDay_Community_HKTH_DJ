# Lane B models and replay checks

**Scope: five synthetic prompt recordings, not a complete D1-D4 desktop
recording.** No Messages/Mail delivery, music playback, ticket-site task or
real-app offline rehearsal has been verified by this cache.

All three slots use `gpt-6.1-sol`. Effort is a separate Responses API parameter,
not a suffix in the model ID. The requested configuration is:

```dotenv
OPENAI_MODEL_AGENT=gpt-6.1-sol
OPENAI_MODEL_FAST=gpt-6.1-sol
OPENAI_MODEL_VISION=gpt-6.1-sol
OPENAI_REASONING_EFFORT_AGENT=xhigh
OPENAI_REASONING_EFFORT_FAST=low
OPENAI_REASONING_EFFORT_VISION=xhigh
```

Source: [official GPT-6.1 Sol model documentation](https://developers.openai.com/api/docs/models/gpt-6.1-sol).
The model supports text/image input, Responses function tools, and both requested
efforts. Live image understanding has not been checked in this lane.

These values describe the source lane's ignored `.env`; integration does not
copy private environment files or configure the active shell. The prompt-check
commands below load `.env` themselves. A direct server launch must receive them from the
launcher or use `uv run --project agent --env-file .env python -m gaze_agent.server`
with its separate token/port setup; `server.py` does not load `.env` itself.
The new optional effort variables map to `reasoning: {effort: ...}`. If omitted,
the wrapper preserves the API default. Effort is part of the replay key, so a
different effort cannot silently reuse an earlier recording. The public
`complete()` signature, protocol and shared contracts are unchanged. The shared
`.env.example` belongs to A2 and was not edited; A2 can add these optional effort
variables there.

## What the cache proves

The checked-in cache contains five live Responses API recordings, all using
`fixtures/demo_profile.json` and synthetic data. They are individual prompt
responses, not recorded steps through four real desktop tasks:

1. Ticket planning: Taylor Swift + Ticketmaster + tickets, imperative labels
   within 40 characters, followed by Something else.
2. Sentence decoding: committed `tell mom` plus `GHI,ABC` gives `Tell Mom "ha."`.
   The groups permit `ha`, not `hi`; the prompt was tightened after a live
   response violated that constraint. This is a constraint check, not a natural
   message-writing example. Production `planner.decode` now validates all raw
   words, not just this example: unknown/empty groups fail before the model;
   returned words must match one letter per group and retain committed words in
   order. Case, apostrophes and surrounding punctuation are allowed. Invalid
   candidates are removed; if none remain, it raises `LLMError`. There is no
   second model call or invented fallback sentence.
3. Auto suggestions on a synthetic Mail message from Alex: includes
   `Reply to Alex: noon sounds good`.
4. A proposed Send on a synthetic Messages draft: current element/snapshot IDs,
   model confirmation flag, and deterministic gate `action:send, source:both`.
5. A synthetic user-cancelled tool result: the next call is `finish` with
   `ok:false`; the model does not retry Send.

The task calls only propose tools. Neither check imports a desktop adapter,
executes a tool, captures a screen, or reads/writes the active user profile.
The fixture profile is supplied in memory to both the calls and the recording
guard. This is necessary because the active Mac profile differs from the demo.

From the repository root:

```sh
uv run --project agent python agent/replay/check_planner.py replay
uv run --project agent python agent/replay/check_prompts.py replay
```

Both commands remove the API key in their own process before calling the wrapper;
any cache miss fails before HTTP. They compare output with the recorded expected
JSON. Wi-Fi was not switched off. The backend suite additionally prohibits the
OpenAI client and active-profile loader while replaying these same five entries.

`REPLAY=replay` is now strict even when a valid API key is present: a miss raises
`LLMError` naming the prompt, model and effort, with instructions to record the
matching demo input first. Invalid/incompatible entries also fail; neither case
constructs an OpenAI client or counts a live call. This intentionally replaces
the live fallback described in the older spec §8.6. Use `REPLAY=off` for live
calls, or `REPLAY=record` to record authorized demo inputs. Models, effort,
templates and meaningful input must match the recordings.

The raw API recordings are unchanged by the decoder/risk-hint fixes. The
planner's expected parsed output now marks the two ticket searches `risky:false`:
a standalone "No purchase" disclaimer in plan details is no longer counted as
an instruction to buy. Buy labels, positive purchase instructions and model risk
flags still mark a plan as risky. The action confirmation gate is unchanged and
still requires confirmation on an observed Buy button even for a search plan.

## Private demo configuration (issue #5)

`agent/gaze_agent/demo_config.py` adds an **explicit opt-in** private persona,
recipient allowlist and storage. With `GAZE_DEMO_CONFIG` unset or empty, nothing
changes: the public fixture, the default profile store and this tracked cache
are used exactly as described above. Setting it to the absolute path of a private
manifest requires `DEMO_MODE=1`. Example with **fake** values only:

```json
{
  "format": "gaze-private-demo/1",
  "config_id": "rehearsal-a",
  "persona": {"name": "Riley Example", "favorites": {"artist": "The Placeholder Band",
              "playlist": "Quiet Hours", "sites": ["tickets.example"]},
              "contacts": {"Mom": ["+1 555 0142"]},
              "style": {"tone": "casual", "signature": "– Riley", "phrases": ["on my way"]},
              "address": {"full_name": "Riley Example", "city": "Testville", "email": "riley@example.invalid"}},
  "approved_recipients": {"Mom": ["+1 555 0142"]},
  "data_dir": "/Users/example/GazePrivateDemo/data",
  "cache_dir": "/Users/example/GazePrivateDemo/replay-cache"
}
```

- `persona` must be a valid protocol profile. `approved_recipients` must list
  exactly its contacts: no padded, duplicate or shared handles.
- The manifest, `data_dir` and `cache_dir` must be outside every Git work tree.
  They must not overlap the default `~/Library/Application Support/GazeCopilot`
  store or each other. The manifest must belong to the user and must not be
  group- or world-writable. Errors name the field, never the path or handle.
- The private store seeds `profile.json` from the persona inside `data_dir`.
  Profile edits or files with contacts outside `approved_recipients` are
  rejected, so the allowlist can never grow from the active profile.
- `REPLAY=record` and `REPLAY=replay` use only
  `cache_dir/<config_id>-<fingerprint>`. The fingerprint covers the persona and
  allowlist, so a changed persona never reuses old recordings. Replay stays
  strict: a miss or bad entry fails with zero API calls, even with a key.
  Recording requires the active private profile to equal the persona.
- `check_planner.py` and `check_prompts.py` are public-fixture checks only. The
  CLI drops the selector with a notice, and `check()` refuses it.

The server and rehearsal consumers are still separate follow-up edits. Until they
use this provider, **do not set `GAZE_DEMO_CONFIG` for real runs**: the server
would keep using the default store and the public allowlist. The actual private
persona, recipients and directories remain human decisions.

**Prompt changes:** a changed prompt body changes every affected cache key. The
shipped synthetic entries then miss, and private recordings in every namespace
become stale. Refresh them by recording again only when a human authorizes live
calls (`check_*.py record` for the public synthetic set; real recording for
private namespaces). Never rename, rekey or edit an old response so that it
matches a new prompt.

## Phase 0 stub fixture correction

The user authorized correcting the shared Phase 0 fixture in
`agent/tests/test_stubs.py::test_stub_planner_shapes`. Its fake response remains
"Tell Mom I'll be late."; its input now commits the first four words and encodes
the final word "late" correctly:

```python
planner.decode(["tell", "mom", "i'll", "be"], [["JKL", "ABC", "TUV", "DEF"]], None, {})
```

The test also checks that the old mismatched input (only `tell` plus `GHI`)
still raises `LLMError`. Production validation was not weakened, and no test was
skipped. No schema, shared interface or prompt placeholder changed. Current
verification results are recorded in `.plans/tasks.md`.

To refresh these synthetic recordings using a configured key:

```sh
uv run --project agent python agent/replay/check_planner.py record
uv run --project agent python agent/replay/check_prompts.py record
```

`OPENAI_PRICE_*` is still unset, so live usage logs report `est_usd:null`; no
prices were added to code. Replay uses zero live tokens.

## Safety label provenance

The user reported these exact **synthetic fixture** labels; no human AX dumps or
live checks are available:

| App | Label | Gate |
| --- | --- | --- |
| Messages | Send | send |
| Mail | Send | send |
| Mail | Reply All | send |
| Safari / Ticketmaster | Buy tickets | buy |

`test_synthetic_demo_app_labels` checks each as AX and OCR, with the model flag
off. Existing rules cover all four without a policy change. No real Delete or
Submit labels have been reported. Existing generic Delete/Submit tests are not
live evidence.

## Human checks still required

**These synthetic recordings are not the D1-D4 desktop replay cache.** Real app
layouts, permissions, OCR positions, target identification, recipient delivery,
clipboard restoration, timing and real-app offline rehearsal remain unverified.
Do not describe the demo as ready on the basis of these checks.

Before recording real tasks, the human must back up the active profile and
switch it to the exact demo fixture. Both recording and rehearsal reject a
different persona; the synthetic helpers do not change the profile for them.
The fixture contacts are placeholders; safe, reachable demo recipients still
need to be agreed before a real Send/delivery test. Cancelling at Send can check
the confirmation gate but does not prove delivery or record the full send path.
For example, the following is **human-run only**, because it changes the active
app profile:

```sh
gaze_profile="$HOME/Library/Application Support/GazeCopilot/profile.json"
mkdir -p "$(dirname "$gaze_profile")"
if [ -f "$gaze_profile" ]; then
  cp "$gaze_profile" "$gaze_profile.before-demo-$(date +%Y%m%d-%H%M%S)"
fi
cp fixtures/demo_profile.json "$gaze_profile"
```

From the terminal with Accessibility and Screen Recording grants, human-run:

```sh
DEMO_MODE=1 uv run --project agent python -m gaze_agent.screen
DEMO_MODE=1 REPLAY=record scripts/start.sh real
```

- Screen check: Messages exposes compose/Send; sparse AX falls back to OCR;
  OCR coordinates land on the text and contain no overlay text.
- Overlay: use ⌃⌥⌘D for click mode; ⌃⌥⌘. stops/hides. D1 sends to demo Mom
  only after Send confirmation; D2 drafts/replies to demo Alex and confirms
  Send; D3 plays Deep Focus or performs the selected browser task; D4 resolves
  Taylor Swift and Ticketmaster, asks for the date, fills quantity, and stops
  at BUY. A confirmed demo BUY must be a no-op.
- TextEdit/clipboard: submit `open TextEdit and type hello world`; expect the
  text, a successful task result and an unchanged clipboard.
- Race: stop at a pending confirm; a later confirm must not send. Revoke Screen
  Recording and request a permission check; expect `screen_recording:false`
  without a crash.

Once those real paths have been recorded, human-run the rehearsal with Wi-Fi
off. Clearing the key also ensures a miss cannot fall back to a live call:

```sh
OPENAI_API_KEY= REPLAY=replay DEMO_MODE=1 uv run scripts/rehearse.py
```

Expect D1-D4 PASS using real apps. Reaching this point still requires human
reports; it has not been run by the agent. A changed app layout may need a new
recording; this cache normalizes IDs/coordinates, not arbitrary screen content.

For Ticket E, run each command below for 10 minutes, switching among Mail,
Messages and Safari, then quit and retain the usage rows/summary:

```sh
DEMO_MODE=1 GAZE_AUTO_AMBIENT=0 scripts/start.sh real
DEMO_MODE=1 GAZE_AUTO_AMBIENT=1 scripts/start.sh real
```

Expect no unsolicited Auto model calls with `0`, and at most three ambient
attempts/minute with the default 20-second cooldown with `1` (manual refreshes
have their own 3-second gap). Task/planner calls are counted separately.
