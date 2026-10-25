# Gaze Copilot: Build Spec (v1, hackathon)

> Working name: **Gaze Copilot** (placeholder; change the name in one place: `overlay/src/shared/app.ts` → `APP_NAME`).
> Deadline: **Sunday 2026-10-25 23:59**. Deliverable: 2-minute pitch video, then a live stage demo if we qualify.
> Team: 2 humans orchestrating AI coding agents (Codex / Claude Code). This spec must be precise enough that each track can be built by an agent **without asking questions**. If something is not specified, pick the simplest option and note it in the PR.

---

## 1. Product summary

An eye-controlled AI copilot for macOS. It is for people who struggle with a mouse or keyboard (spinal injury, early ALS, Parkinson's/tremor, severe RSI).

- **Input:** gaze (WebGazer) with **dwell** to select (800 ms default). A long **blink** can confirm an armed target (opt-in). Mouse-as-gaze is available as a dev and rescue mode.
- **Output:** a Python agent that operates real macOS apps through OpenAI function tools, using the **Accessibility (AX) tree first**, then Apple Vision OCR, and then a downscaled screenshot as a last resort.
- **Two modes:**
  - **Auto (default tab):** 3–4 suggestion cards based on what is on screen. **Ambient suggestions are off by default** (`GAZE_AUTO_AMBIENT=0`): the Auto dock shows a **"Suggest now"** card, and the agent calls the model only when the user dwells it (or switches to the Auto tab). Ambient mode can be turned on and is rate-limited (§7).
  - **Type (Task mode):** a free-request mode. The user types an intent on a T9 gaze keyboard, the agent returns 2–4 interpreted **plan cards**, the user picks one, and the agent runs it.
- **Safety:** a full-screen confirm appears before anything that sends, buys, deletes, submits or posts. A code-enforced gate plus a model flag decide when it appears (§9). A STOP target is always visible, and a panic hotkey is available.

### Demo tasks (all four must pass the rehearsal script)
| # | Request (typed or suggested) | Apps | Confirm? |
|---|---|---|---|
| D1 | "Tell Mom I'll be late" | Messages | Yes: **Send** |
| D2 | Auto suggests "Reply: sounds good" on the latest email | Mail | Yes: **Send** |
| D3 | "Play my focus playlist" / "Open YouTube and search X" | Music or Safari | No |
| D4 | "Tickets for my favorite artist" → resolves `profile.favorites.artist` → searches a ticket site → date picked via choice cards → quantity filled | Safari + ticket site (Ticketmaster or Eventbrite; pick whichever is least flaky on Saturday) | Yes: **Buy**. **Stop at the BUY confirm.** In demo mode, CONFIRM is a no-op (§9.4) |

The examples (message someone, email, play/open, buy tickets) are **not** menu items. They show what free requests can do.

---

## 2. Repository layout

```
/
├─ .gitignore                 # FIRST COMMIT (T0): .env, node_modules/, .venv/, __pycache__/, .DS_Store, dist/, out/, release/, *.sqlite
├─ .env.example               # OPENAI_API_KEY= (+ model vars below, empty)
├─ README.md                  # run instructions + permissions
├─ package.json / pnpm-workspace.yaml
├─ protocol/                  # SINGLE SOURCE OF TRUTH for WS messages
│  ├─ messages.schema.json    # ONE JSON Schema file: envelope + every message payload (draft 2020-12)
│  └─ README.md
├─ overlay/                   # Electron + TypeScript + Vite + React (pnpm)
│  └─ src/
│     ├─ main/                # window creation, spawn agent, global hotkey, token
│     ├─ preload/
│     ├─ renderer/
│     │  ├─ gaze/             # GazeProvider interface, webgazer.ts, mouse.ts, blink.ts (MediaPipe), filter.ts
│     │  ├─ dwell/            # <DwellTarget/> + DwellManager (the ONE selection component)
│     │  ├─ dock/             # Dock, ModeTabs, SuggestionCards, PlanCards, ChoiceCards, StatusPill
│     │  ├─ keyboard/         # T9Keyboard, PredictionBar, t9index.ts
│     │  ├─ screens/          # ConfirmScreen, Onboarding (permissions), Calibration, Settings
│     │  ├─ stop/             # StopTarget
│     │  └─ ws/               # client.ts (reconnect, validation), types generated from protocol/
│     └─ shared/app.ts
├─ agent/                     # Python 3.12, uv
│  ├─ pyproject.toml
│  └─ gaze_agent/
│     ├─ server.py            # websockets server, auth, routing, cancellation
│     ├─ protocol.py          # pydantic models generated from/validated against protocol/messages.schema.json
│     ├─ llm.py               # OpenAI Responses API wrapper + record/replay cache
│     ├─ loop.py              # task tool loop with limits
│     ├─ screen/ax.py         # AX tree snapshot → compact element list (pyobjc)
│     ├─ screen/ocr.py        # Apple Vision OCR fallback
│     ├─ screen/shot.py       # downscaled screenshot fallback
│     ├─ actions.py           # click, set text, keys, open app/url
│     ├─ safety.py            # confirmation gate rules
│     ├─ auto.py              # frontmost-window watcher + suggestion cache
│     ├─ profile.py           # profile/settings JSON store
│     ├─ tasklog.py           # JSONL log, 7-day retention
│     └─ permissions.py
├─ prompts/                   # all LLM prompts as .md with {{placeholders}}; NO prompts inline in code
│  ├─ task_system.md
│  ├─ plan_intent.md
│  ├─ auto_suggest.md
│  ├─ sentence_decode.md
│  └─ look_at_screen.md
├─ data/wordlist_en.txt       # ~20k English words with frequency, for local T9
├─ fixtures/demo_profile.json # FAKE demo persona (committed). Never commit real profile data.
└─ scripts/
   ├─ dev.sh                  # pnpm dev with the fake agent (preview); real agent: start.sh live
   ├─ fake_agent.py           # scripted WS server replaying demo flows (overlay dev without OpenAI)
   ├─ fake_overlay.py         # CLI client sending requests (agent dev without Electron)
   └─ rehearse.py             # runs D1–D4 with REPLAY=replay, prints pass/fail
```

**Secrets rule (we build in public):** only `.env.example` is committed. The key is read from `.env` by Electron main and passed to the agent via an env var. A pre-commit check (`scripts/check_secrets.sh`, run in CI) fails if `sk-` appears in tracked files. Replay cache files and fixtures contain **demo-persona data only**.

---

## 3. Tooling (pinned)

- Node 20+, **pnpm**, Electron (current stable), TypeScript strict, Vite, React.
- Python **3.12** with **uv**. Dependencies: `websockets`, `openai`, `pydantic>=2`, `pyobjc` (ApplicationServices, Quartz, Vision, AppKit), `pyautogui` (fallback only), `python-dotenv`.
- Types: generate TS types from `protocol/messages.schema.json` (`json-schema-to-typescript`); pydantic models must validate against the same schemas in tests.
- `.env` variables: `OPENAI_API_KEY`, `OPENAI_MODEL_AGENT` (strongest, for the tool loop), `OPENAI_MODEL_FAST` (mini, for suggestions/plans/decode), `OPENAI_MODEL_VISION` (for look_at_screen), `REPLAY=off|record|replay`, `DEMO_MODE=0|1`, `DEBUG=0|1`, `GAZE_SOURCE=webgazer|mouse`, `GAZE_AGENT_CMD` (optional; a custom command Electron main spawns as the agent, e.g. `uv run scripts/fake_agent.py --delay 2`. It receives the same `GAZE_TOKEN`/`GAZE_PORT`), `GAZE_AGENT_MODE=live|preview|custom` (set by `scripts/start.sh`/`dev.sh` in the launching shell; never read from `.env`; §4), `GAZE_AUTO_AMBIENT=0|1` (default 0, §7), `OPENAI_PRICE_<AGENT|FAST|VISION>_<IN|OUT>` (optional, USD per 1M tokens, for the cost log in §7).

---

## 4. Process model & WebSocket transport

- Electron main generates a random 32-byte hex **token** and picks port **8765** (falls back to a free port). It spawns the agent the launcher selected with `GAZE_AGENT_MODE`, read from its own environment before `.env` is loaded: `live` → `uv run --project agent python -m gaze_agent.server`, only after checking the key, model, effort, `REPLAY` and `DEMO_MODE` settings; `preview` → `uv run scripts/fake_agent.py` (without API keys); `custom`, or no mode with `GAZE_AGENT_CMD` set → `GAZE_AGENT_CMD`. With neither it starts nothing and exits with an error, so the real agent is never an implicit default. The child gets `GAZE_TOKEN`, `GAZE_PORT` and the `.env` variables (the shell wins over `.env`). On Electron quit it stops the child's process group: SIGINT, then SIGTERM, then SIGKILL. The fake agent (§12.2) is run this way, so the overlay never needs a hardcoded token.
- The agent binds **127.0.0.1 only**. The renderer connects to `ws://127.0.0.1:{port}/?token={token}`, and a wrong or missing token gets close code 4401.
- The client reconnects with exponential backoff (250 ms → 4 s max). The status pill shows "Reconnecting…". In-flight tasks are cancelled server-side when the socket drops (§4.4). If the agent process Electron spawned exits, main closes the renderer's connection with code 4500 (main ↔ renderer only, never sent by an agent): the overlay shows "The agent stopped" and does not retry.
- **Permissions (TCC) belong to the *responsible process*, not to the process that uses them.**
  - **Dev** (`scripts/start.sh`, which runs `pnpm dev`, from a terminal): the responsible process is the **terminal app** (Terminal, iTerm, VS Code…). Accessibility, Screen Recording and Camera must be granted to *that app*. Electron and the Python child both inherit its grants, and nothing is granted to "Electron" or "python".
  - **Packaged, signed app:** the app itself is responsible, and its children inherit its grants.
  - **The demo runs in dev mode.** Grant permissions to the exact terminal app that will be used on stage, and rehearse from it. Each side checks its own permissions at runtime (§11); nobody assumes they were inherited.

### 4.1 Envelope (every message, both directions)
```json
{ "v": 1, "type": "string", "id": "uuid-v4", "re": "uuid-v4|null", "ts": 1761300000000, "payload": {} }
```
- `re` is **always a message `id`, never a task id**. The rules:
  - Direct replies set `re` to the request's `id`:
    - `hello_ack` → `hello`
    - `decode_result` → `decode_request`
    - `plans` → `intent_submit`
    - `profile_result` → `profile_get`/`profile_update`
    - `settings_result` → `settings_update`
    - `permissions_status` → `permissions_check`
    - `error` → the offending message
    - the first `task_status` → `plan_select`
  - Unsolicited messages (`suggestions`, later `task_status`, `choice_request`, `confirm_request`, `task_result`) have `re:null`. They are correlated by `task_id` / `list_id` in the payload.
  - `choice_response` / `confirm_response` set `re` to the `choice_request` / `confirm_request` id.
- Both sides **validate** incoming messages against the schema. Invalid messages are answered with `error{code:"bad_message"}` and ignored.
- **Versioning:** only the envelope `v` is checked. A `hello` with `v ≠ 1` → `error{code:"version_mismatch"}`, then close code 4400. `hello.version` / `hello_ack.version` are app versions for logs only.
- Error codes: `bad_message`, `version_mismatch`, `unknown_plan`, `stale_list`, `task_busy`, `no_task`, `llm_failed`, `internal`.

### 4.2 Overlay → Agent
| type | payload | notes |
|---|---|---|
| `hello` | `{client:"overlay", version:"0.1.0"}` | first message |
| `mode_set` | `{mode:"auto"\|"type"}` | agent pauses the auto watcher in `type` mode |
| `gaze_context` | `{dock_idle:boolean, idle_ms:number}` | sent when gaze has rested on the dock ≥1500 ms without a selection, and again when that ends |
| `auto_refresh` | `{}` | user dwelled the "Suggest now" card, or switched to the Auto tab (bypasses the 20 s cooldown; has its own 3 s minimum gap, §7). The agent answers every request: `suggestions`, or `error` with `re` = its id (`llm_failed` on a model failure, `internal` when too soon or the window changed). The overlay holds a request made within 4 s of the previous one until the gap has passed, and stops waiting after 90 s without either |
| `decode_request` | `{words:string[], raw_keys:string[][], context?:string}` | on DONE: the words picked from the prediction bar plus raw key groups of unfinished words (e.g. `[["GHI","ABC"]]`). Returns ≤3 sentences |
| `intent_submit` | `{text:string}` | the chosen decoded sentence → agent returns `plans` |
| `plan_select` | `{list_id:string, plan_id:string}` | starts a task (also used for selecting an Auto suggestion or a recovery card; all are plans). Never sent for `id:"other"` (handled locally: back to the keyboard with the text kept) |
| `choice_response` | `{task_id, choice_id:string\|null}` | `null` = cancel |
| `confirm_response` | `{task_id, confirmed:boolean}` | |
| `stop` | `{reason:"gaze"\|"hotkey"\|"user"}` | cancels the current task within 200 ms; releases held modifier keys. With no task running, it is a no-op (no error) |
| `profile_get` / `profile_update` | `{}` / `{patch:object}` | JSON merge-patch → `profile_result` |
| `settings_update` | `{patch:object}` | JSON merge-patch → `settings_result` |
| `permissions_check` | `{}` | |
| `open_settings_pane` | `{pane:"accessibility"\|"screen_recording"\|"camera"}` | agent runs `open x-apple.systempreferences:…` |

### 4.3 Agent → Overlay
| type | payload | notes |
|---|---|---|
| `hello_ack` | `{version, demo_mode:boolean, profile:Profile, settings:Settings, permissions:Permissions}` | |
| `permissions_status` | `{accessibility:boolean, screen_recording:boolean, camera:"unknown"}` | camera is reported by Electron itself |
| `suggestions` | `{list_id:string, window_key:string, app:string, items:Plan[] (3–4), cached:boolean}` | Auto mode |
| `decode_result` | `{sentences:string[] (1–3)}` | `re` = decode_request id |
| `plans` | `{list_id:string, items:Plan[] (2–4)}` | always includes a final `{id:"other", label:"Something else", kind:"other"}` |
| `profile_result` | `{profile:Profile}` | the full saved profile after any patch |
| `settings_result` | `{settings:Settings}` | the full saved settings after any patch; an invalid patch → `error{bad_message}` and nothing is saved |
| `task_status` | `{task_id, state:"running"\|"waiting_user"\|"done"\|"failed"\|"stopped", step:number, max_steps:15, message:string}` | `message` is short, human-readable text ("Opening Messages…") |
| `choice_request` | `{task_id, question:string, options:{id,label,detail?}[] (2–4)}` | ambiguity: never guess (§8.3) |
| `confirm_request` | `{task_id, action:"send"\|"buy"\|"delete"\|"submit"\|"post"\|"other", title:string, details:string[], source:"rule"\|"model"\|"both", demo_noop:boolean}` | |
| `task_result` | `{task_id, ok:boolean, summary:string, list_id?:string, recovery?:Plan[]}` | on failure the recovery cards are: Try again / Show me the screen / Cancel (§8.4) |
| `error` | `{code:string, message:string, task_id?:string}` | |

`Plan = {id:string, label:string (≤40 chars, imperative), detail?:string, kind:"task"|"other"|"recovery", risky:boolean}`. `risky` is only a UI hint (it shows an icon); the real gate is in §9.

Every message type is defined in the single file `protocol/messages.schema.json` (`#/$defs/payload_<type>`). **The protocol is frozen after T0 ends** (target: Sat 14:00). Any change after that needs a PR that touches the schema, both clients and the examples.

### 4.4 Task lifecycle & races (both sides implement exactly this)
- **One task at a time per connection.** The agent creates `task_id` (uuid-v4).
  - `plan_select` while a task is active → `error{code:"task_busy"}`. The overlay prevents this anyway, because the dock is collapsed during a task.
  - The **first** reply to an accepted `plan_select` is `task_status{state:"running", step:0}` with `re` = the `plan_select` id. The overlay collapses the dock only when it receives this message, not when it sends `plan_select`.
- **Every** task-scoped message carries `task_id`. The overlay ignores task-scoped messages whose `task_id` isn't the active task. The agent ignores a `choice_response` / `confirm_response` whose `task_id` isn't the active task or that has no pending wait, and replies `error{code:"no_task"}`.
- **Terminal states:** `task_result` is always preceded by exactly one terminal `task_status` (`done` / `failed` / `stopped`). After that, the task id is dead.
- **Stop wins.** `stop` cancels any pending choice or confirm wait. A `confirm_response{confirmed:true}` that arrives after `stop` is dropped and **never** executes the action. The gate is re-checked after the confirm wait returns, so the agent executes only if the task is still active.
- **Disconnect = stop.** The agent cancels the task, logs it as `stopped`, and drops pending waits. On reconnect (`hello_ack`), the overlay resets to idle: the dock is expanded in its last mode, and no confirm, choice or pill is shown.
- **Lists:** each `plans` / `suggestions` / `task_result.recovery` message has a fresh `list_id`, and only the **most recent** list is selectable. A new list invalidates every older one, whatever its source.
  - A `plan_select` with an old `list_id` → `error{code:"stale_list"}`.
  - A `plan_select` with an unknown `plan_id` in the current list → `error{code:"unknown_plan"}`.
- **Suggestions are dropped, not sent**, if after the LLM call the mode is no longer `auto`, a task has started, or the `window_key` changed. The overlay also ignores `suggestions` while it isn't showing the Auto dock.
- **Overlay timeouts:** the confirm screen auto-cancels after 60 s and sends `confirm_response{confirmed:false}`. Choice cards have no timeout, but the 90 s task clock is paused while waiting (§8.4).

---

## 5. Eye input (overlay)

### 5.1 GazeProvider
```ts
interface GazeSample { x:number; y:number; t:number; confidence:number } // screen px
interface GazeProvider { start():Promise<void>; stop():void; onSample(cb:(s:GazeSample)=>void):()=>void; }
```
- `webgazer.ts`: WebGazer with Kalman filter on, video preview hidden after calibration.
- `mouse.ts`: cursor position at 60 Hz with confidence 1, read by Electron main via `screen.getCursorScreenPoint()` and sent over IPC. It does **not** use DOM mouse events, so it works while the window is click-through (§6.1). Selected by `GAZE_SOURCE=mouse` or the hotkey ⌃⌥⌘M. **All UI must work with this provider.**
- `filter.ts`: One-Euro filter (minCutoff 1.0, beta 0.007) applied to every provider's output.

### 5.2 `<DwellTarget>` (the single selection component)
Used by keyboard keys, all cards, confirm buttons, STOP, mode tabs and calibration. No other component may implement selection.
```ts
<DwellTarget id="key-ABC" dwellMs={settings.dwellMs} hitPadding={24} onSelect={...} disabled={false} variant="key|card|confirm|stop">
```
- **Hit-testing via DwellManager** (one global instance): each frame it finds the target under the filtered gaze point. **Sticky:** the current target stays active until the gaze is outside its rect + 40 px for ≥150 ms. A new target must be under the gaze for ≥100 ms before it becomes active.
- **Progress ring:** a radial fill from 0 to 100% over `dwellMs`. Leaving the target decays progress at 2× speed instead of resetting it, which tolerates tremor.
- **Cooldown:** after any select, every target is locked for 600 ms (STOP is exempt) and the selected target flashes.
- **Blink (opt-in, `settings.blinkSelect`):** MediaPipe Face Landmarker, eye-aspect-ratio below threshold for **>400 ms** = a deliberate blink. It selects the active target only if that target is **armed** (active ≥200 ms). Normal blinks (<300 ms) are ignored and also pause dwell progress, so they don't break it.
- Settings: `dwellMs` 500–2000 (default 800). The confirm screen's CONFIRM uses `max(1500, dwellMs*1.5)`. STOP uses 400 ms.
- Every completed dwell becomes a WebGazer training sample at the target's center (passive recalibration).

### 5.3 Calibration (user picks on first run, and later from Settings)
- **Gaze-only:** 9 dots shown one at a time. Each self-advances after 1.2 s of fixation within 120 px, then a validation pass on 4 dots shows the mean error. If the error is above 200 px, it offers a redo.
- **Caregiver-assisted:** same dots; a helper clicks each dot while the user looks at it.
- A "Recalibrate" card is always reachable from the Settings tab.

---

## 6. Overlay UI

### 6.1 Window
- One transparent, frameless, always-on-top (`screen-saver` level) Electron window covering the primary display, with **`focusable:false`** and type `panel`. It **never** takes keyboard focus. Selection is by gaze/dwell only, so the window needs no mouse events for that.
- **Click-through rule:** `setIgnoreMouseEvents(true, {forward:true})` is the default, and stays on for the **entire time a task is running**, including over the pill and STOP. This way the agent's synthetic Quartz clicks always reach the app underneath, never the overlay.
  - When idle, the renderer turns it off only while the real mouse is over a caregiver-clickable control (Onboarding "Open Settings", Settings, Calibration in caregiver mode), and turns it back on when the mouse leaves.
  - The confirm screen is the exception: it is opaque and captures mouse clicks, because the agent never clicks while waiting for a confirm.
- `setVisibleOnAllWorkspaces(true, {visibleOnFullScreen:true})` so the overlay stays visible over full-screen apps.
- The agent never sees the overlay. AX reads only the frontmost app, and the overlay can't become frontmost because it can't take focus. Screenshots capture **only the target window** (§8.1).
- Visual style: **glass**: `backdrop-filter: blur(24px) saturate(140%)`, 55% tinted background, high-contrast text (WCAG AA on worst-case backgrounds; add a text shadow), and minimum target size **160×120 px**. Large type (≥28 px labels). There are two density presets; the default is "large".

### 6.2 Layout
- **Dock** (bottom, ~25% of screen height, full width, glass):
  - Left edge: two stacked mode tabs, **Auto | Type**.
  - Auto mode: a "Suggest now" card (spinner while waiting), then 3–4 suggestion cards + "Something else → Type".
  - Type mode: prediction bar (top row of the dock, 5 word cards) above the T9 keyboard. Pinned favorites appear as a row of cards when the input is empty.
- **While a task runs**, the dock collapses to a **status pill** (bottom center, `task_status.message` + step n/15) so the user can watch the agent work.
- **STOP target:** fixed **top-right, 160×160, red glass**, visible whenever a task is running *and* during confirms/choices. Dwell 400 ms. It is exempt from cooldown and is never covered by anything.
- **Choice / plan cards** appear in the dock (re-expanded) while `waiting_user`.
- **Confirm screen:** full-screen and opaque (no glass, so it can't be misread). It shows a big title ("Send message to Mom?") and the details lines (recipient, exact text, price…). **CONFIRM** is bottom-left and **CANCEL** top-right, far apart so a drifting gaze can't hit CONFIRM by accident. It auto-cancels after 60 s. In demo mode, a "DEMO: will not purchase" badge appears when `demo_noop`.

### 6.3 T9 keyboard & local decoding (zero tokens per keystroke)
- Keys (3 rows): `ABC DEF GHI` / `JKL MNO PQRS` / `TUV WXYZ ␣` plus a control column: `⌫ (delete group)`, `DONE`, `123?` (digits/punctuation sub-page). That is 12 big targets.
- `t9index.ts` builds a map `keySequence → words[]` at startup from `data/wordlist_en.txt` + profile phrases + contact aliases + favorites. Profile entries get a frequency boost of ×50.
- The prediction bar shows the top 5 words for the current key sequence. Dwelling on one commits it and inserts a space. Dwelling on ␣ commits the top prediction.
- **DONE** sends `decode_request` (words + any unfinished raw keys). The agent makes **one** `OPENAI_MODEL_FAST` call (`prompts/sentence_decode.md`) to fix grammar and choose between ambiguous words, using profile style. It returns ≤3 sentences as cards, followed by `intent_submit`.
- If the user commits only known words and there is no raw residue, show the sentence as-is plus the LLM variants.

---

## 7. Auto mode (on demand by default, ambient but cheap when enabled)

- **Default: on demand.** With `GAZE_AUTO_AMBIENT=0` (the default), the agent never calls the model by itself. The Auto dock shows a **"Suggest now"** card; dwelling it sends `auto_refresh`. The overlay also sends one `auto_refresh` when the user switches to the Auto tab (not at launch). Each `auto_refresh` makes at most one model call, at least **3 s** apart (extra requests inside 3 s are ignored).
- **Local polling stays cheap.** `auto.py` polls the **frontmost app + focused window** at 1 Hz with AX only (no LLM, no screenshot) in both settings.
  - `window_key` = `bundle_id` + the **normalized** window title: lowercase, digits and counters such as `(3)` removed, whitespace collapsed. So "Inbox (3)" → "Inbox (4)" is not a change.
  - `content_hash` = hash of the visible AX element roles+labels (truncated to 200 elements).
- **Ambient (`GAZE_AUTO_AMBIENT=1`).** An LLM call (`OPENAI_MODEL_FAST`, `prompts/auto_suggest.md`) happens only when **all** of these hold:
  1. mode is `auto` and no task is running;
  2. the app changed, **or** the normalized `window_key` changed, **or** the visible text changed meaningfully: >30% of elements **and** ≥40 characters of new label text;
  3. the change has been stable for 1.5 s (debounce);
  4. ≥**20 s** since the last auto call **attempt** (`AUTO_COOLDOWN_S`, env-overridable). The attempt time is recorded before the screen read, so a failed screenshot or model call also waits out the cooldown. `auto_refresh` bypasses this cooldown but keeps its 3 s gap.
  - There is no `gaze_context.dock_idle` requirement. `gaze_context` is still accepted but no longer gates calls.
  - Worst case: 3 ambient calls/min (180/h), plus manual requests.
- **Screenshots in Auto** (Type requests and tasks keep §8.1 unchanged):
  - only when AX gives **fewer than 3** labelled elements **and** fewer than **80 characters** of label text;
  - downscaled (`sips -Z 1280`, JPEG) before OCR, with Apple Vision's **Fast** recognition level; OCR is local and the image never goes to OpenAI;
  - at most **1 per 60 s**, counted from the last capture **attempt**. Inside that window, reuse the last OCR result for the same `window_key`, otherwise send AX text only.
- **Cache:** an LRU of 20 entries keyed by `(window_key, content_hash)`. Returning to a seen window is served from cache with `cached:true` and no model call.
- Suggestions are `Plan`s. Selecting one sends `plan_select` and starts the task directly (no extra plan step).
- **Cost log:** every model call (all prompts, not only Auto) records `response.usage` input/output tokens. A per-session meter counts calls, tokens and estimated USD per prompt, using `OPENAI_PRICE_*` from `.env` (no hardcoded prices; a missing price logs `est_usd: null` and warns once; replay hits count as 0). It writes a `usage` row to the task log every 5 minutes and at disconnect, and prints a one-line summary when the agent stops.

---

## 8. Agent (Python)

### 8.1 Screen understanding
`get_screen()` (called internally at the start and after each action, not exposed as a separate tool; its output is attached to every tool result):
1. **AX tree** (pyobjc `AXUIElement` of the frontmost app's focused window). It produces a compact list:
   `e12 | AXButton | "Send" | enabled | (x,y,w,h)` — interactive and labelled elements only, max 150 elements, plus the focused element and window title. IDs are valid **only for that snapshot** (`snapshot_id`). Using a stale id → tool error "stale_snapshot, re-read".
2. If the AX tree has fewer than 5 labelled elements (e.g. canvas apps, some web content) → **Apple Vision OCR** on a window screenshot. OCR text boxes become pseudo-elements `o7 | text | "Buy tickets" | (bbox)`, which are clickable by center point.
3. **`look_at_screen(question)`**: explicit tool. It sends a downscaled screenshot (max 1280 px long edge, JPEG q70) to `OPENAI_MODEL_VISION` with `prompts/look_at_screen.md`, and returns a text answer and optional coordinates. It is used only when 1 and 2 are insufficient. It is counted as a step.

**Screenshots (OCR and look_at_screen)** capture **only the target window**, so the overlay is never in the image: get the window id from `CGWindowListCopyWindowInfo` (frontmost app's pid, layer 0), then run `screencapture -x -o -l <window_id> <tmp.png>`. Don't rely on `CGWindowListCreateImage`, which is deprecated/obsoleted on recent macOS and may be missing on macOS 26. OCR bboxes are converted from window-relative to screen coordinates (add the window origin) before they are used as click targets.

Safari web content: Safari exposes web content through AX natively. Walk the `AXWebArea` children. **Don't** set `AXEnhancedUserInterface`: that's the Chrome/VoiceOver switch, and it can break window animation and positioning. If Safari's AX is poor on the ticket site, OCR is the expected fallback (that is the point of D4 rehearsal).

### 8.2 Function tools (OpenAI Responses API, `OPENAI_MODEL_AGENT`)
| tool | args | behavior |
|---|---|---|
| `click_element` | `{id, snapshot_id, requires_confirmation?:bool, confirmation_reason?:string}` | AXPress, else click at center via Quartz events (PyAutoGUI last resort) |
| `type_text` | `{text, id?, snapshot_id?, submit?:false}` | focus element → **set AXValue**; if that fails, clipboard paste (save and restore the user's clipboard); else per-key typing. `submit` is never implicit |
| `press_keys` | `{keys:string[] e.g. ["cmd","enter"], requires_confirmation?, confirmation_reason?}` | |
| `open_app` | `{name}` | `NSWorkspace` launch/activate; resolve aliases from the profile (e.g. "music" → Spotify if set) |
| `open_url` | `{url}` | opens in the default browser |
| `look_at_screen` | `{question}` | §8.1.3 |
| `ask_user` | `{question, options:[{id,label,detail?}] (2–4)}` | → `choice_request`, waits for `choice_response` |
| `finish` | `{ok:boolean, summary}` | ends the task |

The system prompt (`prompts/task_system.md`) gets the profile summary (favorites, aliases, style; **no** address unless the task needs form filling), the chosen plan, the rules ("never guess between ambiguous targets; use ask_user", "set requires_confirmation for anything irreversible"), and the current screen.

### 8.3 Ambiguity
If several elements or contacts plausibly match, the model **must** call `ask_user`. Code also enforces this for contacts: if an alias resolves to more than one handle → `choice_request` before the model sees it.

### 8.4 Loop limits
- Max **15 tool calls**, **90 s** wall clock (time spent in `waiting_user` is excluded) and **2 retries** per failing tool.
- When a limit is hit, or the task fails → `task_result{ok:false, list_id, recovery:[…]}`. The recovery cards are plans with `kind:"recovery"` and fixed ids, and are selected with a normal `plan_select`:
  - `recovery:retry` ("Try again"): starts a **new** task (new `task_id`) with the same plan.
  - `recovery:show_screen` ("Show me the screen"): starts a short task that runs `look_at_screen("What is on screen and what went wrong?")` (no other tools). It ends with `task_result{ok:true, summary:<answer>, list_id, recovery:[recovery:retry, recovery:cancel]}`. The overlay shows `summary` as a large read-only card above those cards.
  - `recovery:cancel` ("Cancel"): handled **locally** by the overlay (back to the idle dock), like `"other"`. No message is sent.
- `stop` cancels the asyncio task immediately, aborts the in-flight OpenAI request, releases any held keys and emits `task_status{state:"stopped"}`.

### 8.5 Intent → plans
`intent_submit` → one `OPENAI_MODEL_FAST` call (`prompts/plan_intent.md`) with the profile summary and the current app context → 2–4 concrete plans + "Something else" (which goes back to the keyboard with the text preserved). Profile references like "my favorite artist" must be resolved **in the plan label** ("Find Taylor Swift tickets on Ticketmaster") so the user can see what will happen.

### 8.6 Replay cache (demo safety net)
`llm.py` wraps every OpenAI call. With `REPLAY=record`, it stores `{key → response}` in `agent/replay/cache/*.json`, where key = sha256(prompt name + model + normalized input without timestamps/ids). With `REPLAY=replay`, it returns cached responses, and on a miss it falls back to live (or errors if offline). Screen snapshots inside inputs are normalized to role+label lists so replays survive small UI changes. The cache is recorded only with the **demo profile**.

---

## 9. Safety: confirmation gate

### 9.1 Rule gate (`safety.py`, deterministic, cannot be bypassed by the model)
It runs **before** every `click_element`, `press_keys`, and `type_text` with `submit:true`. It triggers `confirm_request` if:
- the target element's label/title/description (case-insensitive, also checked against OCR text) matches
  `send|reply all|buy|purchase|pay|checkout|place order|order now|book|reserve|delete|remove|trash|erase|submit|post|publish|tweet|confirm order|transfer|unsubscribe`;
- the keys are `cmd+enter`, `cmd+shift+d` (Mail send), `cmd+delete`, `cmd+backspace`, `shift+cmd+delete`; or `enter`/`return` while the focused element is in Messages/Mail compose, a chat input, or a form whose window/page title matches checkout/payment/order;
- the app is Finder and the action moves to Trash, or the target URL matches checkout/payment paths (`/checkout`, `/payment`, `/cart/buy`).

### 9.2 Model flag
If the model sets `requires_confirmation:true` (with a reason), confirm is triggered even if no rule matched. `source` = `rule` / `model` / `both`.

### 9.3 Flow
The gate blocks the action → `confirm_request` (`title` + `details` built by code from the actual target: app, recipient, exact text, amount if visible via OCR) → waits for `confirm_response` → it executes only on `confirmed:true` **and** if the task is still active (not stopped or disconnected, §4.4). A cancel tells the model "user cancelled", and the model should `finish`.

### 9.4 Demo mode
With `DEMO_MODE=1`, confirmed actions of type `buy` are **not executed** (`demo_noop:true`, and the overlay shows the badge). `send` actions in demo mode go to the demo persona's own contacts only.

### 9.5 Panic
- Global hotkey **⌃⌥⌘.** (Electron `globalShortcut`) → `stop{reason:"hotkey"}` + hides the overlay. Pressing it again shows the overlay.
- STOP target (§6.2) → `stop{reason:"gaze"}`.

---

## 10. Local data

All under `~/Library/Application Support/GazeCopilot/` (never in the repo):
- `profile.json`:
  ```json
  { "name":"", "favorites":{"artist":"","playlist":"","sites":[]},
    "contacts":{"Mom":["+1555…"]}, "style":{"tone":"casual","signature":"","phrases":["on my way","sounds good"]},
    "address":{"full_name":"","city":"","email":""} }
  ```
  **No payment data, ever.** The address is only sent to the LLM when the task is filling a form.
- `settings.json`: `{dwellMs:800, blinkSelect:false, density:"large", gazeSource:"webgazer", calibrationMode:"gaze"}`.
- `tasklog.jsonl`: one line per event `{ts, task_id, plan_label, tool, element_label, outcome, latency_ms}`. **Actions only**: no screenshots, AX dumps or message bodies unless `DEBUG=1`. Entries older than 7 days are pruned on startup.
- First run with `DEMO_MODE=1` copies `fixtures/demo_profile.json`.

---

## 11. Onboarding / permissions

The first launch (or any missing permission) shows the **Permissions checklist** screen: Accessibility, Screen Recording, Camera. Each row has a status dot and an **Open Settings** button (mouse-clickable, for a caregiver or dev). It re-checks every 2 s via `permissions_check`. When everything is green → Calibration (the user chooses gaze-only or caregiver mode) → Auto mode.

How each permission is checked:
- **Accessibility (agent):** `AXIsProcessTrusted()` (ApplicationServices). It never prompts on its own.
- **Screen Recording (agent):** `CGPreflightScreenCaptureAccess()` (Quartz). It never prompts. `CGRequestScreenCaptureAccess()` is called **once**, on the first "Open Settings" press, so the terminal app appears in the list.
- **Camera (overlay, Electron main):** `systemPreferences.getMediaAccessStatus('camera')` (`not-determined` / `granted` / `denied` / `restricted`). It is merged into the row by the overlay; the agent always reports `camera:"unknown"`. `systemPreferences.askForMediaAccess('camera')` is called when the user reaches the Camera row, not at app launch.
- On macOS 15+, Screen Recording may re-prompt periodically. A `false` mid-session shows the checklist again instead of failing silently.
- After granting Accessibility or Screen Recording, macOS often requires **restarting the responsible app** (the terminal in dev) before the check turns green. The checklist row says so when the check stays red for 10 s after "Open Settings".

---

## 12. Testing

1. **Protocol contract tests:** TS (vitest) and Python (pytest) both validate messages against `protocol/messages.schema.json` and round-trip them through their own types. `scripts/fake_overlay.py demo` is the executable end-to-end contract check. They run in CI on every PR.
2. **`scripts/fake_agent.py`:** a scripted WS server that implements the protocol (including all §4.4 rules) and replays D1–D4 (suggestions → plans → status steps → choice → confirm → result) with delays. The overlay track builds against this by setting `GAZE_AGENT_CMD`.
3. **`scripts/fake_overlay.py`:** a CLI (`intent "tell mom I'll be late"`, `select 2`, `confirm yes`, `stop`) so the agent track builds without Electron. It is a thin shell over `scripts/gaze_client.py` (an async client class: connect, send, wait-for-type, with validation).
4. **`scripts/rehearse.py`:** `REPLAY=replay DEMO_MODE=1` runs D1–D4 end-to-end through `scripts/gaze_client.py`, auto-answering choices and confirms, and prints PASS/FAIL + timings per task. It must be all green before recording the video and before going on stage.
5. Unit tests: safety gate rules (a table of labels/keys → expected decision), T9 index, AX compaction, the One-Euro filter and the DwellManager sticky logic (simulated sample streams, including tremor noise).

---

## 13. Parallel tracks & ownership

Human A orchestrates the overlay tracks; Human B orchestrates the agent tracks. Each track = one agent session/branch and one PR into `main`.

| Track | Scope | Depends on |
|---|---|---|
| **T0 Scaffold** (blocking, ~2 h) | `.gitignore`, `.env.example`, pnpm workspace, uv project, `protocol/` schemas + examples + codegen, contract tests, `dev.sh`, secrets check | — |
| T1 Gaze & dwell | §5 complete: providers, filter, DwellManager, `<DwellTarget>`, blink, calibration | T0 |
| T2 Dock & keyboard | §6.2–6.3: dock, mode tabs, cards, T9 + index + prediction bar, status pill | T0, T1 API (stub OK) |
| T3 Safety UI & window | §6.1, confirm screen, STOP, onboarding, settings, hotkeys, WS client | T0 |
| T4 Agent core | server, auth, routing, loop + limits, llm.py + replay, plans, decode, profile, tasklog | T0 |
| T5 Screen & actions | ax.py, ocr.py, shot.py, actions.py, permissions.py | T0 |
| T6 Safety & auto | safety.py + tests, auto.py watcher + cache, all `prompts/*.md` | T4 interfaces |
| T7 Harness | fake_agent, fake_overlay, rehearse, demo_profile fixture | T0 |

### Timeline
- **Sat 14:00:** T0 merged, protocol frozen.
- **Sat 23:00:** every track works against the fakes.
- **Sun 12:00:** integrated; D1–D3 pass live, D4 reaches the BUY confirm.
- **Sun 16:00:** record the replay cache, rehearse green, **feature freeze**.
- **Sun 16–21:** record and edit the 2-minute pitch video (show the user's gaze path, the confirm screen and STOP; voice-over on who it's for).
- **Sun 23:59:** submit.

### Cut list (in order, if behind)
Blink select → OCR fallback (AX + look_at_screen only) → pinned favorites → caregiver calibration → auto content-hash trigger (window change + refresh only).

---

## 14. Open items (decide during build, don't block)
- Final product name.
- Ticket site for D4 (test Ticketmaster vs Eventbrite AX/OCR on Saturday; pick one and hardcode it in the demo profile's `favorites.sites`).
- Concrete OpenAI model IDs for the three `.env` slots (pick the current best/mini/vision on Saturday).
