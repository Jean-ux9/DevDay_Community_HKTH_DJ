# A2 platform handoff to A1

The initial mouse/stub contract is commit `3ab8a46`; the implementation keeps its signatures.
A1 owns all screens and styling. No A1 files were edited by A2.

## Imports and dwell

Import only from `../platform` (adjust relative path). No provider setup is required: the first
`useSession()`, `useGaze()` or `<DwellTarget>` mounts the shared platform runtime. There is one
DwellManager for the entire overlay.

```tsx
import { DwellTarget, agent, useSession } from '../platform'

const session = useSession()
<DwellTarget id="suggest-now" variant="card" disabled={!session.ready || session.suggestPending}
  onSelect={() => agent.suggestNow()} className="suggest-card">
  {session.suggestPending ? 'Thinking…' : 'Suggest now'}
</DwellTarget>
```

Use unique stable target IDs. The wrapper exposes `data-dwell-id`,
`data-dwell="idle|active|armed|selected|cooldown"`, `aria-disabled` and the CSS variable
`--dwell-progress` (0–1). A1 draws the ring/flash. It measures DOM bounds every frame, so
layout changes need no explicit registration. Disabled, hidden and zero-size targets cannot select.
The default duration comes from acknowledged settings (800 ms initially); confirm uses
`max(1500, 1.5 * dwellMs)`, STOP always uses 400 ms, and hit padding defaults to 24 px.
STOP ignores the 600 ms global cooldown. Source changes, lost eyes and reconnects discard partial dwell.

`useGaze().point` uses overlay viewport CSS pixels, matching DOM bounds and the gaze-dot position.
Mouse gaze comes from main-process cursor IPC at 60 Hz, including while click-through is on.
`setGazeSource('mouse'|'webgazer')` switches locally; persist a settings-screen change with
`agent.updateSettings({ gazeSource: source })`. The runtime hotkey is Ctrl+Alt+Cmd+M.
`useGaze().error` reports eye-tracker / optional blink initialization failures.

## Session and click-through

`useSession()` exposes the reducer's `connection` (`connecting|open|reconnecting|error`),
`ready`, `closeCode`, `mode`, `list`, `task`, `confirm`, `choice`, `sentences`, `result`,
`lastError`, `suggestPending`, `profile` and `settings`. Fatal close codes 4400/4401 do not retry.
Reconnect resends hello first, then the last mode, and resets task UI at hello_ack.
`cameraStatus` comes from Electron; `permissions` merges it with the agent's two permission flags.
`agentPermissions` remains the unmodified protocol payload (camera `unknown`).

`agent.suggestNow()` does not run at launch. It sends auto_refresh and guards duplicate requests.
A1 calls it once after switching to Auto. `agent.decode(words, rawKeys)` treats rawKeys as the
unfinished word's ordered groups, e.g. `['JKL','ABC','TUV','DEF']`, and wraps it for the wire schema.
Local `other` / `recovery:cancel` selections reset locally; no plan_select is sent.

Main is click-through by default and throughout tasks, including STOP and the status pill.
Only a pending confirm captures the full window. At idle, real mouse hover over native
`button`, `input`, `select`, `textarea`, links, or an element marked `data-caregiver-clickable`
enables caregiver mouse interaction. A1 should use/mark those controls in onboarding, settings
and caregiver calibration. Pointer input never drives the gaze source. The main-process panic
hotkey Ctrl+Alt+Cmd+. sends STOP over the same agent connection and toggles window visibility.

## Calibration (A1 renders all dots)

1. At the Camera row, `agent.openSettingsPane('camera')` requests camera permission when needed;
   `agent.checkPermissions()` rechecks without prompting. No camera is opened at app launch.
2. `await calibration.start()` requests permission and initializes WebGazer (Kalman on, preview hidden).
3. A1 implements the nine training dots: fixation within 120 px for 1.2 s, or caregiver click.
   `calibration.train(x,y)` records the current dot. Bootstrap training must provide initial
   samples before relying on gaze predictions; WebGazer cannot predict from an empty regression.
4. For the four held-out dots, call `calibration.validate(points)` and render the position from
   `useCalibration().validationPoint`. It publishes each dot for 1.2 s (400 ms settling + 800 ms
   measurement), returns `{meanErrorPx}`, and rejects if tracking produces no samples.
   Do not call train during validation. A1 offers a redo above 200 px.

Passive recalibration trains on completed dwell centers. Validation pauses dwell and does not train.
Optional blink selection uses MediaPipe EAR, pauses normal blinks, and selects an armed target once
on reopening after >400 ms. It shares WebGazer's camera. Eyebrow selection is not in the frozen spec.
All vendor model/wasm/script assets are served locally; the build preparation downloads the public
Face Landmarker model once into ignored node_modules, then caches it.

## Automated verification

```sh
pnpm install
pnpm gen:protocol
pnpm -C overlay typecheck
pnpm -C overlay test
pnpm -C overlay build
uv run scripts/fake_overlay.py demo --spawn
```

`pnpm test` includes a live TS-client test that spawns **only** task D's fake agent on a free
loopback port, plus recorded-protocol replay tests. DOM/camera/transport tests use fakes.
The platform is a separate renderer build entry so bundling is checked before A1 imports it.

## Human-run desktop checks (not performed by A2)

After A1's UI is integrated, run from the repository root with Node 20+ and pnpm on PATH:

```sh
GAZE_SOURCE=mouse GAZE_AGENT_CMD='uv run scripts/fake_agent.py --delay 0.6' pnpm -C overlay dev
```

- Complete D1–D4 by hovering only; check the Suggest now spinner, choice and confirmation screens,
  STOP dwell, recovery cards, and settings results.
- In TextEdit, verify typing stays in TextEdit while the overlay is visible. During a fake task,
  mouse clicks on pill/STOP must pass through; hover-dwell STOP still sends stop.
- At idle, verify onboarding/settings controls are caregiver-clickable. Confirm captures clicks.
- Press Ctrl+Alt+Cmd+. to stop/hide, again to show. Press Ctrl+Alt+Cmd+M to toggle gaze source.
- Test reconnect: use this window's fake-agent PID only, stop it, verify Reconnecting…, then restart
  the fake with the same GAZE_PORT/GAZE_TOKEN (available locally via `window.gazePlatform.config()`
  in Electron devtools). Verify idle reset after hello_ack; do not kill another workspace's server.
- Test real eyes only as a human: camera denied/not-determined/granted states, nine training dots,
  four validation dots and reported pixel error, redo above 200 px, source toggling, optional blink.

The renderer entry in this worktree is still A1's placeholder, so real screen flows require A1's changes.

## Required A1 change: camera CSP

A2 must not edit A1's `src/renderer/index.html`. Its current `default-src 'self'` blocks
WebAssembly. The pinned WebGazer classic MediaPipe glue also constructs JavaScript Functions
(`new Function`), so `wasm-unsafe-eval` alone is insufficient for that vendor bundle.
A1 needs this CSP for the chosen eye-tracking libraries (keep renderer Node integration disabled):

```html
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-eval'; worker-src 'self' blob:; connect-src 'self' ws://127.0.0.1:*; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:" />
```

No remote scripts/model hosts are needed. Mouse gaze and the WS client do not require this relaxation:
protocol validators are generated ahead of time by `scripts/gen-validators.mjs`, with runtime
contract parity tested against a fresh Ajv compilation. Real-eye operation remains dependent on
A1's CSP change and the human camera checks above.
