# Gaze Copilot: Parallel Task Split

Source: `.plans/gaze-copilot-spec.md` (section references below, e.g. §4.2, point to it).

## P05 and P08 combined checkpoint: 2026-10-25

**Feature-branch integration based on `22b38f86bce84f1de940bc0407c2e59643a824f9`.**
P05's work was preserved and the human-supplied P08 handoff's exact three-file
patch was applied without conflicts. Validation below preceded publication. The
human then explicitly authorized committing and pushing the combined work to
`runtime-recipient-guards-c5be22b9` only. No branch merge or GitHub issue update
was performed; presence on `main` is not claimed. This checkpoint supersedes
older notes below that still describe these consumers as missing.

| Work | Implemented and verified with fakes |
|---|---|
| **P05: runtime confirmation, recipients and private store** | `loop.py` rechecks native window/focus, compact context, internal AX field values and policy after confirmation; uniquely rebinds unchanged targets and rejects ambiguous/unreadable context. STOP/disconnect, Cancel and demo BUY no-op remain. Internal `screen/recipients.py` requires a single exact native recipient handle and P04's approvals, then revalidates it after confirmation. Titles, aliases, incidental labels and active-profile edits cannot expand approvals. `server.py` shares P04's selected store/allowlist and isolated log storage. Ticket E normalization is unchanged and regression-tested. Before P08 import, focused acceptance passed **282 tests** and the extended backend/harness tree passed **810 tests**. |
| **P08: rehearsal private-config consumer** | Imported `scripts/rehearse.py` plus `scripts/tests/test_rehearsal.py` and `test_rehearsal_lifecycle.py` from the exact supplied P08 patch. Rehearsal validates P04's selected configuration before real startup and the exact approved persona before app preparation or task requests. Fake mode skips private configuration and removes the selector from its child; real mode pins the shell selector, even when empty. Send auto-confirmation, BUY STOP, cancellation and strict replay behavior are preserved. The **24 consumer + 18 lifecycle tests** pass in this combined checkout. |
| **P05/P08 integration and CLI test fixes** | Fixed the five shared CLI transport-guard failures with a per-instance connection restricted to the helper's active spawned fake agent/port/token; ordinary clients and wrong/expired targets remain blocked. Replaced four unsafe title-only assertions with negative cases and added native-evidence positives/negatives. Shared test isolation now clears `GAZE_DEMO_CONFIG`. Three new integration cases exercise P08 through P05's real loopback server/loop/recipient reader with a fake desktop: approved Send completes, unapproved Send is blocked, and a mismatched persona is rejected before preparation. Focused integration: **109 PASS**; full combined backend/harness suite: **855 PASS**, zero failures. |

Combined checks actually run (Python 3.12.15; fake desktop/API, temporary storage):

```sh
env GAZE_DEMO_CONFIG=/gaze-test-nonexistent-private-config UV_NO_ENV_FILE=1 PYTHON_DOTENV_DISABLED=1 uv run --project agent --python 3.12 pytest agent/tests scripts/tests --tb=short
env -u GAZE_DEMO_CONFIG UV_NO_ENV_FILE=1 PYTHON_DOTENV_DISABLED=1 uv run scripts/fake_overlay.py demo --spawn
env -u GAZE_DEMO_CONFIG UV_NO_ENV_FILE=1 PYTHON_DOTENV_DISABLED=1 uv run scripts/rehearse.py --target fake
sh scripts/check_secrets.sh
git diff --check
```

Results: **855 tests PASS**, **11/11 mock flows PASS**, **9/9 fake rehearsal PASS**;
secret scan and diff checks pass. The nonexistent selector is a synthetic
isolation tripwire, not an activated private configuration. The complete current
patch, including all new source/test/fixture files, is in
[`lambda-reports/P05.txt`](lambda-reports/P05.txt). The supplied P08 report itself
was read unchanged; only its code patch was imported.

**Still unverified:** real Messages/Mail recipient layouts, native context/STOP/
clipboard behavior, #6 launch/typing, live API, actual sends, recordings, private
real-app rehearsal and offline desktop behavior. Native recipient layouts have
only synthetic evidence and unsupported layouts fail closed. No actual private
configuration was inspected or activated. Keep #5/#9/#10 and #6 open pending
delivery review, human persona/storage agreement and staged native checks. The
human guide remains Stage 1. A later real rehearsal still auto-confirms Send;
private rehearsal requires a shell-exported selector, not only `.env`.

## Next session: GitHub fixes, real API integration and English recommendations

**Requested direction, 2026-10-25:** resolve the open GitHub issues and make the
working app use the real backend and API responses. Recommend English for the
first supported suggestion/planning flow and human tests. This section is the
next-session work queue; the checkpoint and original task split below provide
history and ownership. Updating this plan does not mean these tasks are done.

**Synced starting point:** this workspace ran `git fetch origin` and
`git pull --ff-only origin main`, advancing from `7e4f674` to `f72b21b`.
`7e4f674` contains the backend fixes and requested `.env.example` defaults;
`f72b21b` also includes the newer overlay layout/styling changes. The working
tree was clean before this documentation edit. Recheck Git status and ancestry
at the next session; preserve later local work and stay in this worktree.

### 1. Reconcile the seven open issues with delivered code

Read the current issue bodies/comments, `AGENTS.md`, the build spec,
[`backend-debug-handoff.md`](backend-debug-handoff.md), and
[`backend-human-testing.md`](backend-human-testing.md) before implementation.
All seven issues below were still **OPEN** when this plan was updated. Several
reports still describe fixes as uncommitted even though they shipped in
`7e4f674`; verify the code before rewriting or closing anything.

Owners here are backend A = screen/actions, B = LLM/planning/replay/policy,
C = runtime/loop/integration, D = CLI harness. Overlay A1/A2 are separate owners.

| Priority / issue | Owner | Next-session work and completion evidence |
|---|---|---|
| P0 — [#11: private profile access in tests](https://github.com/Jean-ux9/DevDay_Community_HKTH_DJ/issues/11) | C, coordinate D/Phase 0 | P05 now clears `GAZE_DEMO_CONFIG` in the shared guard used by backend/script tests; a synthetic inherited-selector tripwire and the full 855-test combined run pass. Preserve temporary storage/fake API guards. Delivery review is still required. Preserve the disclosure that earlier unguarded runs may have read/created the profile; do not inspect or delete it to investigate. |
| P0 — [#9: changed context after confirmation](https://github.com/Jean-ux9/DevDay_Community_HKTH_DJ/issues/9) | C + A | P05's local patch rechecks compact context, native window/focus, internal AXValue and policy; rejects ambiguity/read failure; and retains unique target rebinding and STOP/disconnect dominance. Combined fake regressions pass. Keep open for delivery and staged human/native verification, including same-title windows; do not infer native success. |
| P0 — [#10: incidental recipient matches](https://github.com/Jean-ux9/DevDay_Community_HKTH_DJ/issues/10) | C, coordinate A/B | P05 replaces title authorization with narrowly scoped native recipient evidence and P04's approved handles, checked before and after confirmation. Missing/ambiguous/group/incidental/unapproved evidence fails closed. Synthetic positive/negative and combined rehearsal/runtime tests pass. Real Messages/Mail controls are unverified; keep open pending human evidence and delivery. |
| P0 — [#5: private controlled recipients/cache](https://github.com/Jean-ux9/DevDay_Community_HKTH_DJ/issues/5) | B + C; A for storage | P04's delivered provider/private storage/recording guard is now consumed by the local P05 server/runtime and exact P08 rehearsal patch. Selected store/allowlist, exact persona validation, fake-child selector removal and shared test isolation are integrated; all 855 combined tests, 11 mock flows and 9 fake rehearsal cases pass. The human authorized feature-branch publication only; no main delivery is claimed. Keep open for human delivery, actual controlled persona/recipients/folders and staged native/recording/rehearsal checks; no private setup was activated. |
| P1 — [#6: TextEdit launch/focus](https://github.com/Jean-ux9/DevDay_Community_HKTH_DJ/issues/6) | A + C | Retain the live-AX focus, bounded activation and ordered-key-release fixes already shipped. After the human testing prerequisites pass, request the small zero-OpenAI native launch probe, then a separate blank-document/hello-world, clipboard and STOP retest. An Open dialog is a valid launch result. Diagnose each reported failure with a focused fake regression before another costly live loop. Keep open until the required human result is explicit. |
| P1 — [#7: CLI Cancel/choice handling](https://github.com/Jean-ux9/DevDay_Community_HKTH_DJ/issues/7) | D | **Done.** The fix shipped in `7e4f674` was re-verified against the real CLI handler and client with in-memory sockets and the fake agent. Two small gaps were fixed in `3ad3d71`: `choose`/`confirm` at an idle plan list now points to `select N`, and a failed send exits the REPL cleanly instead of with a traceback. `scripts/tests/test_cli_repl.py` adds 24 regressions; harness 26 + CLI 24 PASS, mock protocol 11/11 PASS. Low-level negative tests and server `task_busy`/`unknown_plan`/`no_task` are unchanged. The humans merge to `main` and close the issue; a human REPL run is optional. |
| P1 — [#4: stale human guide](https://github.com/Jean-ux9/DevDay_Community_HKTH_DJ/issues/4) | A docs, coordinate B/C | Check the delivered guide against current model/effort handling, defaults, ownership and startup modes. Keep exact terminal versus REPL commands and automatic-Send warnings. Close the documentation issue with source/commit evidence once corrected; do not imply that its closure verifies native desktop behavior. |

For every issue, record: reproduction, delivered/new fix, tests actually run,
remaining human dependency and closure decision. Post only sanitized code-level
evidence and commit references; keep unresolved blockers open. Do not close all
seven merely because one combined suite passes.

### 2. Replace simulation in the app flow with real API responses

**Current implementation:** `agent/gaze_agent/llm.py` already calls
`AsyncOpenAI.responses.create`. Planner/decode, Auto suggestions, the task loop
and explicit vision use that wrapper. The missing work is to audit and complete
the live end-to-end wiring, fix integration gaps and prove actual API behavior;
do not build a second parallel client or describe the existing client as a stub.

- Make the normal user-facing app path use the real Python backend. Currently
  `scripts/start.sh` without arguments and `scripts/dev.sh` launch a fake agent,
  and browser preview is fake-only. Coordinate launcher/main-process changes
  with overlay A1/A2 and script owners. Make live entry deliberate and clearly
  disclosed; retain an explicitly named fake/preview mode. Do not silently turn
  a formerly harmless preview command into desktop control, or launch it as a
  coding agent.
- Trace the whole path: Electron environment/agent launch → authenticated
  WebSocket → `planner.make_plans` / `planner.decode` / `AutoWatcher` →
  `llm.complete` → model response → validated UI cards; then selected plan →
  `TaskLoop` → gated native tools → observed result. Fix any remaining canned
  suggestions, success messages or mock routing in the live path.
- For live API validation use `REPLAY=off`, a real-agent command and the private
  key/model settings. Preserve the requested `.env.example` defaults:
  `gpt-6.1-sol` in all slots, Agent/Vision `xhigh`, Fast `low`, blank key/prices.
  Check configuration without printing secrets. An absent key is a clear setup
  failure, never a reason to copy another worktree's `.env` or return fake success.
- Keep T9 per-keystroke work local. Route DONE decoding, intent planning,
  explicit Suggest now and task/vision requests to their existing model slots;
  preserve Auto cooldowns, caches, token accounting and cancellation. Surface
  real API/auth/timeout/invalid-output failures honestly, with sanitized errors
  and no silent canned-response fallback.
- Add a narrowly scoped opt-in live API smoke check using synthetic input,
  with no native actions or screen/profile capture. The human runs live checks
  after Stage 1 configuration passes; this plan does not authorize a coding
  agent to inspect private configuration or spend API credits automatically.
  Require evidence of an uncached API request/usage and a validated result;
  unit tests and replay hits alone are insufficient.
- **Keep fakes for automated regression tests.** Dropping simulation from the
  working product flow does not remove desktop/API test doubles, storage guards,
  protocol mocks or strict replay. Do not weaken confirmations, recipient
  restrictions, STOP or BUY no-op to obtain a live-looking result.

### 3. English recommendation and generated suggestions

Recommend **English** for the first supported UI recommendations, plan labels,
choice/confirmation explanations, T9 requests and controlled test/demo script.
The current word list, sample prompts and safety vocabulary are English; this
is a practical initial scope, not verified multilingual support.

- Make Auto recommendations and interpreted plans come from the real model and
  current context, in concise natural English by default. Preserve schema item
  counts, imperative labels of at most 40 characters, visible resolved favorites
  and honest risk hints. Do not show canned demo suggestions as live output.
- Keep recipient handles, proper names, exact user-approved message text and
  observed native labels intact. English recommendations must not silently
  translate an outgoing message or alter the user's committed T9 words.
- If explicit language instructions are missing, update the existing
  `prompts/*.md` bodies while preserving their placeholder contract. Add
  fake-response coverage for format/meaning validation; assess actual English
  quality in the human-run live check. No prompt text belongs in Python/TS.
- Prompt changes invalidate affected cache keys. Refresh recordings honestly
  when that later stage is authorized; never rekey old responses and present
  them as new calls. Private controlled-recipient recordings stay outside Git.

### 4. Verification, human testing and next-session handoff

After code changes, run the Python 3.12 combined suite, mock protocol flows,
fake rehearsal, secret scan and diff checks:

```sh
uv run --project agent --python 3.12 pytest agent/tests scripts/tests --tb=short
uv run scripts/fake_overlay.py demo --spawn
uv run scripts/rehearse.py --target fake
sh scripts/check_secrets.sh
git diff --check
```

If overlay/main-process code changes, also run `pnpm -C overlay typecheck` and
`pnpm -C overlay test`. Treat the previous 517/11/9 results as historical until
rerun on the changed combined tree. Keep protocol/schema, `contracts.py`,
`protocol.py`, generated types and prompt placeholders frozen. Changes outside
the backend follow-up's owned files require coordination with their owner;
this task list does not authorize editing every lane or spawning more agents.

The human guide is still at **Stage 1**, awaiting results. Continue independent
fake-based fixes while waiting, but give only one human stage at a time. Keep
the order: setup/permissions, profile backup/agreement, harmless AX/OCR,
TextEdit/clipboard/STOP, Cancel-first app flows, then controlled sends and any
later recording/rehearsal. Do not create/configure/switch to `GazeDemo` now.
Coding agents must not activate apps, click, type, post key events, capture
screenshots or run real-app rehearsal.

Retain the mode distinctions in every updated guide: real rehearsal (including
its default target) and scripted demo against a real agent automatically confirm
Send; the REPL uses manual confirmation. `DEMO_MODE=1` is not a general dry run.
Strict `REPLAY=replay` makes zero OpenAI calls and fails on a miss, but still
performs real app actions; online app services may need network access. A
completely offline demo is a separate, unverified requirement.

Finish the next session with an updated issue/evidence matrix, tests and exact
remaining blockers, plus only the human stage currently unlocked. Do not claim
the backend is bug-free. Do not commit or push that session's new work without
a new explicit instruction; the prior authorization covered `7e4f674`.

---

## Current priority: backend stabilization and human testing handoff

**2026-10-25 follow-up (base `3938bbc`):** fixed D's #7 local
REPL Cancel/Other and pending/input cleanup; fixed fake-reproduced C/A
confirmation-context/native-window gap (#9) and C's incidental/partial demo
recipient matching (#10). Final isolated Python 3.12 suite: **517 PASS**, mock
protocol: **11/11 PASS**, fake rehearsal: **9/9 PASS**. Full evidence matrix and
boundaries are in [`backend-debug-handoff.md`](backend-debug-handoff.md).
Issue #6 still needs human native retesting; #5 still blocks actual demo sends,
recording and real rehearsal pending explicit private persona/cache agreement.
No demo profile/cache was configured and no real desktop test ran. The human
guide remains at Stage 1; wait for results. Frozen interfaces and tracked demo
fixtures/recordings are unchanged. Initial validation ran before committing;
the human subsequently authorized committing and pushing the backend changes
and `.env.example` defaults to GitHub `main`. Verify delivery with Git.
The requested model/effort defaults are non-secret; the API key and price values
remain empty. Private `.env` values were not read or changed.
The subsequent #11 audit found the inherited root stub test could read/create
the active profile during initial suite runs, without printing its contents.
A suite-wide temporary-storage/fake-API guard now isolates defaults; the full
517-test suite passed with that guard and two explicit storage regressions.

Updated 2026-10-25. **Fix and verify backend bugs before advancing to demo
recording or rehearsal.** The user will later use a separate macOS account named
`GazeDemo`; it has not been created or configured by this agent. A separate Mac
account and a new Superset workspace are different things. Demo settings and
recipients are still to be agreed; do not silently replace the active profile.

Read this section before the historical build split below, then read
[`backend-debug-handoff.md`](backend-debug-handoff.md) for the next-agent prompt
and [`backend-human-testing.md`](backend-human-testing.md) for Stage 1 only.
Give the human one stage at a time and wait for results. Do not run desktop
actions, captures or real-app rehearsals as a coding agent.

### Code and branch checkpoint

- This checkpoint combines backend integration `6d46172`, upstream `main`
  `cff07f8` (the overlay/gaze merge), and the activation/focus/key-release fixes
  described below. The user explicitly requested publishing this combination
  to GitHub `main`. Verify the actual delivery commit with Git; do not assume a
  branch name proves that code was published.
- Upstream `main` was brought into the integration workspace without conflicts;
  its changes do not replace the four local backend-fix files. First-run dwell
  now defaults to **1300 ms** in both the backend and fake agent; existing saved
  settings are retained. Older 800 ms references describe the original build.
- The old remote lane branches A/B/C were deleted at the user's request after
  verifying their source was preserved in `6d46172`. Their commit IDs below are
  historical provenance, not branches a new worker should expect to fetch.
- Do not switch branches, read/edit other worktrees, or update the local `main`
  checkout elsewhere. A new worker should start in its own workspace from the
  delivered GitHub `main` and confirm that these handoff files and fixes exist.
- No protocol schema, shared Python contract, prompt placeholders or private
  environment files were changed by this stabilization fix.

### Backend fixes included in this checkpoint

Lane A files: `agent/gaze_agent/actions.py`, `screen/ax.py`,
`screen/HUMAN_CHECKS.md`, and `agent/tests/runtime/test_screen_store.py`.

1. Foreground detection reads the live system-wide AX focused application and
   its PID. It no longer depends on `NSWorkspace.frontmostApplication` being
   refreshed by a Cocoa main run loop in the long-running Python process.
2. App launching resolves the app, uses the system launcher, then waits up to
   10 seconds for the target bundle's focused AX window. It fails clearly on
   launch/activation errors, invalidates old snapshot IDs, and kills/reaps a
   stalled launcher on cancellation or timeout. A TextEdit Open dialog is a
   valid app window; creating a document is a separate action.
3. Keyboard chords press modifiers first, then release keys in reverse order
   with the correct remaining modifier flags. The previous unordered release
   and missing key-up flags were reproduced with fake Quartz events.
4. Eighteen fake-native regression cases cover stale/unavailable focus,
   activation/readiness, launch errors, cancellation/timeouts and key ordering.
   Five selected regressions failed on the old implementation before the fix.

### Validation and human evidence

The pre-upstream-merge backend-fix tree passed **449 backend/harness tests** on
Python 3.12.15, **125 targeted screen/action/screenshot tests**, all **11 mock
protocol flows**, all **9 fake rehearsal cases**, and the secret/diff checks.
Those results are historical until the combined delivery tree is checked.
The delivery results are recorded in `backend-debug-handoff.md`; never substitute
separate lane results for a combined run.

Human-reported checks so far (no raw AX output or screenshots retained here):

- Tools worked in a fresh Terminal session: Node 24.22.1, pnpm 9.15.9, uv 0.13.5.
  The pnpm PATH issue was resolved for new zsh sessions.
- The private `.env` was ignored by Git; the key was present without being
  displayed. All three model slots and their effort settings matched the shipped
  synthetic recordings. This is not proof of settings in a new workspace/account.
- Accessibility and Screen Recording checks returned true. Backend camera
  `unknown` is expected and is not camera verification.
- The existing profile was backed up and verified outside the repo; no settings
  file existed at backup time. Keep the private backup/receipt; no personal path
  or contents are recorded in this tracked document.
- Harmless Messages AX and OCR checks were reported good by the human. Raw output
  was not supplied to the coding agent or uploaded to GitHub.
- The real LLM-driven TextEdit task failed: Spotlight/direct opening could not be
  verified from the observed screen. Backend STOP during a pending choice worked.
  Clipboard preservation was inconclusive after copying terminal text.
- A recovery `Show me the screen` returned `ok:true` only for its summary. That
  does not make the failed TextEdit task a PASS.
- Manual `open -a TextEdit` showed TextEdit's Open dialog with Stage Manager both
  on and off; the human confirmed New Document opens a blank document. This does
  not isolate Stage Manager as the cause. The updated zero-OpenAI backend launch
  check still needs its explicit PASS/error and the full typing/clipboard retest.

### Remaining issues and order of work

| Issue | Owner | Next action |
|---|---|---|
| [#6](https://github.com/Jean-ux9/DevDay_Community_HKTH_DJ/issues/6) launch/focus | A; C for integration | Re-run focused fake tests; request the small human zero-OpenAI launch/focus check, then the isolated TextEdit task. Do not declare native success from fake tests. |
| [#7](https://github.com/Jean-ux9/DevDay_Community_HKTH_DJ/issues/7) CLI Cancel and prompts | Original D harness | **Done.** Re-verified and completed in `3ad3d71`; see the next-session table above. The server's `task_busy`/`unknown_plan` responses remain correct. |
| [#5](https://github.com/Jean-ux9/DevDay_Community_HKTH_DJ/issues/5) private controlled demo contacts | B and C; A for profile storage if needed | Provider/storage done in P04 with fakes (see the next-session table). Next: apply the consumer patch to `server.py`, `scripts/rehearse.py` and `agent/tests/conftest.py`, then agree the actual private persona, recipients and folders before actual sends/recording. Until then the server still uses the exact tracked fake fixture; a separate Mac account alone does not fix that. |
| [#4](https://github.com/Jean-ux9/DevDay_Community_HKTH_DJ/issues/4) stale human guide | A | Guidance is corrected in this checkpoint; verify against delivered code before closing the issue. |

Audit additional backend edge cases with focused fake reproductions: focus/window
changes while a confirm is pending, recipient matching versus incidental screen
text, STOP during native worker work, stale element IDs, clipboard formats and
restoration, OCR limits/fallback errors, model/cache failures, list replacement
and disconnect races. These are review targets, not claims of observed incidents.
Keep an explicit bug/test matrix; passing a finite suite is not proof that every
possible bug has been eliminated.

### Follow-up assignment for the new workspace

The copyable prompt in `backend-debug-handoff.md` assigns one backend
stabilization worker across A/B/C and the original D CLI/test-harness paths needed
to fix #7. This is a follow-up assignment, distinct from original Task C. The
assigned files are listed in that prompt; it does not authorize overlay redesign
or changes to the frozen protocol/shared contracts. Continue to label issues by
their original owning lane and publish only sanitized code-level reports.

No coding agent may run real clicks, typing, screenshots, app activation or a
real-app rehearsal. No secrets, private handles, personal AX dumps or real-user
recordings go into tracked files or public reports. Prompts stay in `prompts/*.md`;
changes to prompt bodies require honest recording refreshes, not relabeling old
responses as new recordings. A handoff does not authorize future commits/pushes.

---

There are four tasks (A is split into A1 and A2), plus follow-up Ticket E. Each one has its own files, branch and PR, and **no file belongs to two tasks**. They can only run in parallel after **Phase 0** (the list below) is merged. Phase 0 freezes the WebSocket protocol and the internal Python interfaces, so the tasks never need to edit each other's files.

| Task | Branch | Covers spec tracks |
|---|---|---|
| A2. Overlay platform (Electron main, window, WS client, gaze, dwell) | `task/overlay-platform` | T1, T2 (main/WS) |
| A1. Overlay screens (dock, keyboard, screens, styles, "Suggest now") | `task/overlay-screens` | T2 (UI), T3 |
| B. Agent server (Python runtime + screen understanding + desktop actions) | `task/agent-server` | T4 (minus planning), T5 |
| C. Planner, prompts & policy (LLM wrapper, plans, decode, Auto mode, safety gate) | `task/planner` | T4 (planning/LLM parts), T6 |
| D. Harness & demo (fakes, rehearsal, demo persona, docs) | `task/harness` | T7 |
| E. Auto-mode cost controls (follow-up, after B and C) | `task/auto-cost` | §7 |

---

## Historical backend integration: 2026-10-25

Integration branch: `integrate-backend-lanes-90ceca37`. At the start of that run,
`git fetch origin` confirmed base `553ca13` was both HEAD and `origin/main`.
The workspace was clean before integration; no local edits needed preservation.
All three requested GitHub branches were available, and none of their commits
after this base was already merged into `origin/main` or the integration HEAD.

| Lane | Fetched branch | Tip | Missing commits applied without creating commits |
|---|---|---|---|
| A | `backend-screen-actions-db4810e6` | `88ee622` | `3321bc6`, `6dac244`, `88ee622` |
| B | `backend-replay-validation-a2d2d2e7` | `55706a8` | `e4174ad`, `67ff8f7`, `55706a8` |
| C | `backend-loop-integ-8e17e085` | `1c81d06` | `f321839`, `1c81d06` |

The three code patches applied cleanly. Their overlapping task documentation
was combined, and rehearsal descriptions were corrected to match lane B's
strict replay behavior. No protocol/schema, shared Python contract, generated
overlay type, dependency file or private environment file changed.

**Checks actually run against the combined code in this integration workspace:**

| Command | Result |
|---|---|
| `uv run --project agent --python 3.12 pytest agent/tests scripts/tests --tb=short` | PASS: 431 tests, Python 3.12.15, exit 0 |
| `uv run scripts/fake_overlay.py demo --spawn` | PASS: all 11 flows, exit 0 |
| `uv run scripts/rehearse.py --target fake` | PASS: all 9 cases, exit 0 |
| `uv run --project agent --python 3.12 python agent/replay/check_planner.py replay` | PASS with recorded model/effort settings below and API key removed, exit 0 |
| `uv run --project agent --python 3.12 python agent/replay/check_prompts.py replay` | PASS with the same settings and API key removed; no tools executed, exit 0 |
| `sh scripts/check_secrets.sh` | PASS: Secret scan passed, exit 0 |
| `git diff HEAD --check` | PASS |

Both standalone replay commands used `env -u OPENAI_API_KEY`, all three
`OPENAI_MODEL_*` slots set to `gpt-6.1-sol`, and
`OPENAI_REASONING_EFFORT_AGENT=xhigh`, `OPENAI_REASONING_EFFORT_FAST=low`,
`OPENAI_REASONING_EFFORT_VISION=xhigh`. These settings were supplied only to the
commands; no `.env` was copied or changed. The helpers can load an existing
`.env` and also remove the API key before replay. The first full test run passed
431 tests on Python 3.14.7 before the explicit Python 3.12 verification above.

**Failed checks:** none. **Not run:** overlay tests, live OpenAI calls, real
desktop screen/action/permission/clipboard checks, live D1-D4, real-app cache
recording and offline real-app rehearsal. No other worktree was read or edited,
and no commit or push was created. The historical per-lane results below are
retained for provenance and are not evidence for this combined pass.

---

## Backend follow-up lane A: Screen understanding & actions

Updated 2026-10-25. **Backend lane A is a later assignment, separate from the original overlay Task A/A1/A2 below.** It continues the screen/action work originally assigned to B and the screen capture work in E.

**Branch:** `backend-screen-actions-db4810e6`. Implementation commits: `3321bc6` (screen/action improvements) and `6dac244` (window-switch race). Both were pushed to this branch; merging into `main` is not claimed here.

**Owns only:**

- `agent/gaze_agent/screen/**` (including the human-check guide).
- `agent/gaze_agent/actions.py`, `permissions.py`, `profile.py`.
- `agent/tests/runtime/test_screen_store.py` and `agent/tests/runtime/fixtures/**`.

**What this lane does:**

- Read the focused app window through Accessibility (AX), then use local OCR when AX is sparse. Prepare Messages, Mail, Music/Safari and the ticket-site screen paths for human testing.
- Keep at most 150 compact elements, including the focused element. Exclude hidden controls and preserve useful native controls and handles when adding OCR.
- Capture only the target window. Convert OCR boxes and vision points to screen coordinates, including window offsets and secondary displays; reject invalid coordinates.
- Keep AX and OCR tied to the same native window during a read. A detected switch, move, resize or closure raises `window_changed, re-read`, publishes no mixed snapshot and invalidates old element IDs.
- Reuse Auto OCR only for the same native window at the same bounds, while keeping E's one-capture-attempt-per-minute limit. An ordinary OCR failure can keep AX if the window is still unchanged.
- Support native click/type/key fallbacks, clipboard preservation, stale/disabled target checks, and separate Accessibility and Screen Recording permission checks.
- Provide AX dump and fixture-reading commands. Turn reviewed human AX dumps into regression fixtures once they are supplied. The four current `demo_*.json` app fixtures are **synthetic**, not live recordings.

**Historical lane A verification, after `6dac244`'s code changes:**

| Command | Result | Environment |
|---|---|---|
| `uv run --project agent pytest agent/tests scripts/tests` | 356 passed | Python 3.12.15; fake desktop APIs, fixtures and fake OpenAI responses |
| `uv run --project agent pytest agent/tests/runtime/test_screen_store.py agent/tests/cost/test_screenshots.py --tb=short` | 107 passed | Fake desktop APIs and fixtures |
| `uv run scripts/fake_overlay.py demo --spawn` | All 11 flows PASS | Fake overlay and fake agent; no real Mac apps or OpenAI calls |
| `sh scripts/check_secrets.sh` | PASS | Local files only |

The window-race follow-up added 37 test cases covering different apps, same-title windows, switches during AX/capture/OCR, changed bounds or capture IDs, failed captures, cache reuse and separate read contexts. These are fake-based results; they do **not** prove live D1–D4 work.

**Still human-run / unverified:**

- Task B item 2: real AX/OCR output, actual button labels, correct coordinates and no overlay text in captures.
- Task B item 3: real TextEdit typing and clipboard restoration.
- Task B item 5: Screen Recording revocation and recovery on the stage terminal.
- Real window switching/movement during OCR, followed by a stable fresh read.
- Reviewed AX recordings for the demo apps. No real Send/Buy/Delete/Submit labels have been reported by this lane.

Exact human-run commands and expected results: [`agent/gaze_agent/screen/HUMAN_CHECKS.md`](../agent/gaze_agent/screen/HUMAN_CHECKS.md). Coding agents must continue to use fakes and must not run real screen captures, clicks, typing or desktop tasks.

**Outside this lane:** overlay code, WebSocket server/task-loop changes, model reasoning settings, prompts, the safety gate and replay recording. The relevant owners must complete real D1–D4 integration, confirmation checks and offline replay. The protocol and `contracts.py` remain frozen.

---

## Backend Lane B: current scope and checks

The table above names the **original build tasks**. The later backend testing
lanes use different letters: **backend Lane B** is the LLM, prompts and planning
lane on `backend-replay-validation-a2d2d2e7`. It continues original Task C and the
LLM/Auto parts of Ticket E. It is not original Task B's Mac runtime work.

**Lane B owns:** `agent/gaze_agent/{llm,planner,auto,safety}.py`, `prompts/**`,
`agent/replay/**`, `agent/tests/brain/**` and `agent/tests/cost/**`. It chooses
plans and validates model output; the runtime lane executes actions. Original
ownership of the server, screen APIs, action tools and shared protocol remains
as listed below.

**Implemented and checked with fakes or synthetic demo data:**

- Per-slot model and reasoning settings: `gpt-6.1-sol` for all slots, agent and
  vision at `xhigh`, fast at `low`. Model IDs and effort are separate settings.
- Production T9 validation: reject invalid groups before calling the model;
  retain only answers matching the committed words and every raw key group;
  fail clearly if no valid answer remains. No extra model call is made.
- Ticket search risk hints: a standalone "No purchase" disclaimer is not a buy
  instruction. Actual buy labels, positive purchase instructions and model risk
  flags remain risky. The deterministic action confirmation gate is unchanged.
- Strict replay: missing or invalid cache entries fail clearly, even with an
  API key present. Fake-client tests prove no client is created and no live call
  is counted on these paths. This supersedes the older §8.6 live fallback.
- Five recorded OpenAI responses from the demo persona and synthetic screens,
  with replay checks that require no API key. These are **prompt checks, not a
  complete D1-D4 desktop recording**.

**Authorized Phase 0 test maintenance:** the user requested fixing
`agent/tests/test_stubs.py::test_stub_planner_shapes`. Its fake response now has
matching committed words and the raw groups for "late". The same test verifies
that its former inconsistent input still fails. No shared contract changed.

**Historical lane B verification, 2026-10-25:**

| Command | Result | Scope |
|---|---|---|
| `uv run --project agent pytest agent/tests/test_contract.py agent/tests/test_prompt_vars.py agent/tests/test_stubs.py` | PASS: 68 tests | Phase 0 contract, prompt and stub tests |
| `uv run --project agent pytest agent/tests scripts/tests` | PASS: 331 tests | Backend and harness tests with fakes/local recordings |
| `uv run scripts/fake_overlay.py demo --spawn` | PASS: all 11 flows, exit 0 | Fake overlay against a spawned fake agent |

These are local test results, not a real desktop end-to-end pass. No live
OpenAI calls, screenshots, clicks, typing or desktop tasks ran for this fix.

**Still requires human checks:** real AX/OCR and vision, real app actions and
delivery, clipboard restoration, permissions, Auto usage over time, the real
D1-D4 recording and an offline real-app rehearsal. No human pass has been
reported here. Demo contacts are placeholders; safe test-recipient setup must
be agreed before confirming real sends. `.env` remains private.

---

## Backend Lane C: task loop and integration

**Status, 2026-10-25:** rehearsal fixes and integration tests are committed and pushed as `f321839` on `backend-loop-integ-8e17e085`. Real-app D1–D4 and offline replay have **not** been verified by this lane. Passing fake tests is not a live end-to-end PASS.

**Purpose:** connect the backend pieces through the frozen protocol and make D1–D4 testable through the task loop. This lane covers task lifecycle/races (§4.4), tool dispatch, choices, confirmation gates, STOP, the 15-call / 90-active-second limits, recovery cards (§8.4), and the D4 rehearsal gate (§12).

**Owns for this follow-up:**

- `agent/gaze_agent/server.py`, `loop.py`, `tasklog.py`;
- `agent/tests/runtime/test_loop.py`, `test_server.py`, `conftest.py`, `support.py`;
- `scripts/rehearse.py`.

For these paths, this follow-up ownership replaces the original B/D/E assignments. Other paths retain their original owners. Lane C does not edit the overlay, protocol/schema, frozen contracts, screen/actions implementation, planner/LLM wrapper, prompts, or replay cache.

**Implemented in `f321839`:**

- Rehearsal planning/decode/suggestion waits allow 120 seconds. Each task has one cumulative 100-second active-time budget (the server's 90-second limit plus transport slack); `waiting_user` time is excluded. The old 45-second whole-demo deadline is removed from live demos.
- Before each live demo, activate and verify the frontmost app: D1 Messages, D2 Mail, D3 Music, D4 Safari. Check that D2 suggestions also identify Mail before selecting a plan. Demo profile and permissions are checked before app preparation.
- Answer repeated choices using each request's own message id, choosing the first offered demo option. D3 may also ask a choice. Reply suggestions can be matched by their label or detail; they need not start with the mock label "Reply". Send gates need not have an exact mock count.
- Confirm only the expected action type. **The real rehearsal automatically confirms Send actions in D1/D2 and can send real messages.** An unexpected risky action is not confirmed. D4 never answers BUY with a purchase confirmation: it sends STOP and checks the stopped terminal result. Failed or timed-out runs also request STOP for any active task.
- Add D1–D4 tests through the real WebSocket server, task loop, planner, Auto watcher and safety gate, with scripted model replies and a fake desktop. Cover multiple ticket choices, long user waits, wrong-app suggestions, profile checks, unexpected Delete, repeated Send gates, timeout cancellation, and app-focus checks using fake Cocoa/subprocess objects. Runtime guards prevent real app preparation and real OpenAI calls during these tests.

Only `scripts/rehearse.py` and the runtime `support.py`, `conftest.py`, and `test_server.py` changed in that commit. The runtime loop/server implementation and frozen interfaces were unchanged.

**Historical lane C verification, using fakes only:**

| Command | Actual result |
|---|---|
| `uv run --project agent pytest agent/tests scripts/tests` | PASS: 284 tests, exit 0 |
| `uv run scripts/fake_overlay.py demo --spawn` | PASS: all 11 flows, exit 0 |
| `uv run scripts/rehearse.py --target fake` | PASS: all 9 cases, exit 0 |
| `git diff --check` | PASS |

**Remaining work and dependencies:**

- Human-run: screen/AX/OCR checks, D1–D4 in real apps through the overlay, actual STOP timing, clipboard checks, recording the demo cache, and offline replay. No real OpenAI request, screenshot, click, typing, or real-app rehearsal was run by this lane.
- Screen/actions owner: verify native app controls, OCR coordinates, clipboard restoration and real Send/Buy targets. Planner/replay owner: verify live model output and record only demo-persona data. Overlay owner: verify the visible choice, confirmation and STOP flows with the real backend.
- Resolved by integrated lane B: `llm.py` accepts separate reasoning-effort settings. Its recorded prompt configuration is Agent `xhigh`, Fast `low`, Vision `xhigh`; model IDs and efforts remain environment settings, not defaults added by integration.
- Before a human runs the real rehearsal, prepare demo-only app content, the exact demo profile, working API/model settings and terminal permissions. `REPLAY=replay` still performs real Mac actions. Integrated lane B makes replay strict: a cache miss fails without calling OpenAI. The safe agent-run command is `uv run scripts/rehearse.py --target fake`.

---

## Phase 0: must exist before parallel work starts (blocking, target Sat 14:00)

**Status: done** (branch `phase0-agent`). Items 2, 6, 7 and 8 below were moved into Task A or Task D, because only those tasks use them. B and C needed items 3–5 before starting; A and D could start as soon as the protocol and mocks were merged. **After this merge, the protocol and the interfaces in `contracts.py` are frozen.** A change needs a PR that updates the schema/contract, both sides and the examples (§4.3).

1. **Protocol (`protocol/`)**
   - ✅ **Done:** `protocol/messages.schema.json`, **one** JSON Schema file (draft 2020-12) for the envelope and every message type in §4.2 and §4.3. Validate type `T` against `#/$defs/payload_T`; `x-messages` maps each type to its direction. It includes `profile_result`, `settings_result`, `list_id` on `plans` / `suggestions` / `task_result` / `plan_select`, `task_id` on `choice_response` / `confirm_response`, and `Plan.kind:"recovery"` (draft 2020-12).
   - Shared definitions in the same file: `Plan`, `Profile`, `Settings`, `Permissions`, `ChoiceOption`, `ErrorCode` (the enum from §4.1).
   - ✅ **Done:** the scripted flows are executable code instead of JSON files. `scripts/fake_overlay.py demo` runs D1–D4 plus `recovery`, `stop_during_confirm`, `task_busy`, `stale_list`, `settings` and `bad_input` against any agent on `GAZE_PORT`/`GAZE_TOKEN`, and prints PASS/FAIL. `scripts/fake_agent.py` serves the agent side of the same flows. Both validate every frame against the schema.
   - ✅ `protocol/README.md`: points to the §4.1 correlation rules and the §4.4 lifecycle rules (the spots where A and B are most likely to diverge).
2. **➡ Moved to Task A.** **Node workspace:** root `package.json`, `pnpm-workspace.yaml` and the `overlay/` skeleton (electron-vite + React + TS strict, `pnpm dev` / `test` / `typecheck` scripts).
   - Main reads `GAZE_AGENT_CMD` (§3/§4) already in the skeleton, so A can start against the fake on hour one.
   - Codegen: `pnpm gen:protocol` writes `overlay/src/renderer/ws/protocol.gen.ts` from `protocol/messages.schema.json` (generated file, never edited by hand).
   - The overlay contract test (vitest) compiles `protocol/messages.schema.json` with ajv and checks sample messages from the fake agent.
3. ✅ **Python project:** `agent/pyproject.toml` (Python 3.12, uv, deps from §3, pytest) and `agent/gaze_agent/__init__.py`.
   - `agent/gaze_agent/protocol.py`: pydantic models for every message.
   - `agent/tests/test_contract.py`: hand-written valid and invalid samples for every message type; each must be accepted (or rejected) by **both** the JSON Schema and pydantic, and valid ones must round-trip unchanged.
   - `gaze_agent` is an installed package, so `uv run --project agent python -m gaze_agent.server` works from any directory.
4. ✅ **Internal Python interfaces (`agent/gaze_agent/contracts.py`):** the only shared Python surface between B and C. It holds dataclasses and signatures. Phase 0 also commits **stub implementations** with these signatures in each module listed below, so imports work on day one. Each task then replaces only its own stubs.
   ```python
   # ---- Owned by B (screen/, profile.py) ----
   @dataclass class Element:    id: str; role: str; label: str; description: str; enabled: bool
                                bbox: tuple[int,int,int,int]   # screen coords (OCR already offset by window origin)
                                source: Literal["ax","ocr"]
   @dataclass class Snapshot:   snapshot_id: str; app: str; bundle_id: str; window_title: str; url: str | None
                                focused: Element | None        # the focused element itself, not just its id (safety needs it)
                                elements: list[Element]        # .to_prompt() -> str  ("e12 | AXButton | \"Send\" | enabled | (x,y,w,h)")
   @dataclass class WindowInfo: bundle_id: str; app: str; window_title: str; window_key: str; element_sigs: list[str]  # role+label, ≤200
   @dataclass class LookResult: answer: str; point: tuple[int,int] | None
   def get_screen() -> Snapshot                       # screen/__init__.py: AX, falls back to OCR (§8.1)
   def window_info() -> WindowInfo                    # screen/ax.py: cheap, AX only, no LLM (for the Auto watcher)
   async def look_at_screen(question: str) -> LookResult   # screen/shot.py: window-only capture + complete(model="vision")
   def load_profile() -> dict; def profile_summary(p: dict, include_address: bool = False) -> str   # profile.py

   # ---- Owned by C (llm.py, planner.py, auto.py, safety.py) ----
   @dataclass class ToolCall:    call_id: str; name: str; args: dict
   @dataclass class LLMResponse: text: str | None; tool_calls: list[ToolCall]; response_id: str | None; cached: bool
   def render(prompt: str, vars: dict) -> str         # raises KeyError on a missing/extra placeholder
   async def complete(prompt: str, model: Literal["agent","fast","vision"], vars: dict, *,
                      tools: list[dict] | None = None,       # OpenAI function-tool JSON (B defines the tools in loop.py)
                      input_items: list[dict] | None = None, # prior turns + tool outputs for the loop (B builds them)
                      image_jpeg: bytes | None = None) -> LLMResponse
       # Cancellation: the caller cancels the asyncio task; complete() aborts the HTTP request and re-raises CancelledError.
       # Failures: raises LLMError (B maps it to error{code:"llm_failed"} or a failed task).
   async def make_plans(text: str, profile: dict, snapshot: Snapshot | None) -> list[Plan]        # 2–4 + "other"
   async def decode(words: list[str], raw_keys: list[list[str]], context: str | None, profile: dict) -> list[str]  # 1–3
   class AutoWatcher:  # __init__(emit_suggestions: async (window_key, app, items, cached) -> None, window_info, get_screen, get_profile)
       set_mode(mode); set_task_running(running: bool); on_gaze_context(dock_idle, idle_ms); refresh(); async run()
       # emit_suggestions is only called if mode == "auto" and no task is running both before AND after the LLM call (§4.4)
   @dataclass class ProposedAction: tool: str; element: Element | None; keys: list[str] | None; text: str | None
                                    submit: bool; url: str | None; model_flag: bool; model_reason: str | None
   @dataclass class GateDecision:   required: bool; action: str; title: str; details: list[str]; source: Literal["rule","model","both"]
   def gate(action: ProposedAction, snapshot: Snapshot) -> GateDecision                              # pure, deterministic
   ```
   **Lifecycle duties of B toward C (frozen):**
   - B calls `AutoWatcher.set_task_running(True)` before emitting the first `task_status{running}`, and `set_task_running(False)` on **every** terminal path: done, failed, stopped, disconnect, exception.
   - B calls `set_mode` on `mode_set`, and on reconnect, from the overlay's last `mode_set`; the default is `auto`.
   - B assigns `list_id` (C returns only items).
5. ✅ **Prompt placeholder contract:** `prompts/*.md` stubs (5 files), each with a front-matter list of its `{{placeholders}}`. Static text (rules, tool usage) lives in the prompt body, not in variables. Images are passed with `image_jpeg`, never through a placeholder.
   - `task_system`: `profile_summary, plan_label, plan_detail, screen`
   - `plan_intent`: `profile_summary, intent, app_context`
   - `auto_suggest`: `profile_summary, app, window_title, screen`
   - `sentence_decode`: `profile_style, words, raw_keys, context`
   - `look_at_screen`: `question`

   The list above lives in code as `contracts.PROMPT_VARS`. `agent/tests/test_prompt_vars.py` renders every prompt with exactly those variable names and fails on any missing or extra placeholder. Because B and C own the two sides, this test keeps them in sync.
6. **➡ Moved to Task D.** **Fixture:** a minimal `fixtures/demo_profile.json` (fake persona, valid against `profile.json`). D owns its content after Phase 0.
7. **➡ Moved to Task D.** **Scripts and CI:**
   - `scripts/dev.sh`
   - `scripts/check_secrets.sh` (fails if `sk-` appears in tracked files)
   - `.github/workflows/ci.yml`: contract tests (TS + Python), `pnpm -C overlay test`, `uv run pytest`, secrets check.
8. **➡ Moved to Tasks A and D.** `.gitignore` and `.env.example` exist. A adds `GAZE_AGENT_CMD=` to `.env.example`. D keeps `agent/replay/cache/` **tracked** (it holds demo-persona data only): add a comment in `.gitignore` saying it is intentionally not ignored.
9. **Local setup for each human (not committed):**
   - A `.env` with `OPENAI_API_KEY` and the three model IDs (§14).
   - Grant **Accessibility, Screen Recording and Camera to the terminal app that runs `pnpm dev`**, not to Electron or Python (§4). Then quit and relaunch that terminal.
   - Decide now which terminal app will be used on stage, and use only that one from then on.

**Original Phase 0 acceptance checks (historical, not current live readiness):**
- `cd agent && uv sync && uv run pytest` passes (contract, prompt-vars and stub tests: 68 tests).
- `uv run --project agent python -m gaze_agent.server` prints the stub message (importable from the repo root).
- `uv run scripts/fake_overlay.py demo --spawn` prints 10× PASS.

---

## Task A: Overlay (Electron + eye tracking + UI)

This is the original overlay Task A. For the later backend assignment, see [Backend follow-up lane A](#backend-follow-up-lane-a-screen-understanding--actions).

Spec: §4.4 (client side), §5, §6, §9.5, §11. This is the user's whole visible product.

Task A is split into **A2 (platform)** and **A1 (screens)** so two agents can work on it at once. A2 owns everything that talks to Electron, the camera, the gaze source or the WebSocket. A1 owns everything the user sees, and reaches the platform **only** through `overlay/src/renderer/platform/index.ts` (the A1/A2 interface below). Files marked *(exists)* are already on `main` with tests.

**Shared by A1 and A2:**
- **`protocol/**` and `overlay/src/renderer/ws/protocol.gen.ts`:** neither touches them (regenerate only, `pnpm gen:protocol`).
- **"Mouse = gaze" debug mode:** both develop and test with it. `GAZE_SOURCE=mouse` (or ⌃⌥⌘M at runtime) makes the cursor position the gaze point, with confidence 1. Hovering a target dwells it; no clicks needed. `scripts/dev.sh` starts the overlay this way against the fake agent.

### A1/A2 interface: `overlay/src/renderer/platform/index.ts`

A2 owns this file and lands it **first**: types plus a working mouse-only implementation, so A1 can start. Changing a signature afterwards needs both agents to agree in their PRs. A1 imports nothing else from `main/`, `preload/`, `gaze/`, `dwell/` or `ws/`.

```ts
// Selection: the only way any UI selects anything (spec §5.2).
export function DwellTarget(props: {
  id: string
  variant: 'key' | 'card' | 'confirm' | 'stop'
  dwellMs?: number            // default settings.dwellMs; confirm = max(1500, 1.5×), stop = 400
  hitPadding?: number         // default 24
  disabled?: boolean
  onSelect: () => void
  className?: string
  children: React.ReactNode
}): JSX.Element
// The wrapper gets data-dwell="idle|active|armed|cooldown|selected" and the CSS variable
// --dwell-progress (0..1). A2 does hit-testing only; A1 owns all visuals (ring, flash) in CSS.

// Gaze
export function useGaze(): { source: 'webgazer' | 'mouse'; point: { x: number; y: number } | null; confidence: number; debug: boolean }
export function setGazeSource(source: 'webgazer' | 'mouse'): void
export const calibration: {
  start(): Promise<void>                       // camera + WebGazer ready
  train(x: number, y: number): void            // a calibration dot was looked at
  validate(points: { x: number; y: number }[]): Promise<{ meanErrorPx: number }>
}

// Agent session (wraps ws/client.ts + ws/session.ts; A1 never sends raw messages)
export function useSession(): SessionState    // includes suggestPending: boolean
export const agent: {
  setMode(mode: 'auto' | 'type'): void
  suggestNow(): void                           // auto_refresh; sets suggestPending until suggestions/error
  setDockIdle(idle: boolean): void             // gaze_context
  decode(words: string[], rawKeys: string[]): void
  submitIntent(text: string): void
  selectPlan(listId: string, planId: string): boolean
  respondChoice(choiceId: string | null): boolean
  respondConfirm(confirmed: boolean): boolean
  stop(reason: 'gaze' | 'hotkey'): boolean
  getProfile(): void
  updateProfile(patch: object): void
  updateSettings(patch: object): void
  checkPermissions(): void
  openSettingsPane(pane: 'accessibility' | 'screen_recording' | 'camera'): void
}
```

### Task A2: Platform (Electron main, window, WS client, gaze, dwell)

**Owns:**
- Root `package.json`, `pnpm-workspace.yaml`, `pnpm-lock.yaml`, `.env.example`.
- `overlay/package.json`, `overlay/electron.vite.config.ts`, `overlay/tsconfig*.json`, `overlay/vitest.config.ts`, `overlay/scripts/**` (`gen-protocol.mjs` *(exists)*, `record_frames.py` *(exists)*).
- `overlay/src/main/**`: `index.ts` (skeleton exists), `agent.ts` *(exists)*:
  - transparent `panel` window, `focusable:false`, `setVisibleOnAllWorkspaces`;
  - click-through rule from §6.1 (fully click-through while a task runs), driven by session state. A1 never calls Electron;
  - token + port, spawns `GAZE_AGENT_CMD` or the real agent, kills it on quit;
  - `globalShortcut` ⌃⌥⌘. (stop + hide/show) and ⌃⌥⌘M (mouse = gaze toggle);
  - cursor polling at 60 Hz via `screen.getCursorScreenPoint()` for `mouse.ts`;
  - camera permission via `systemPreferences`.
- `overlay/src/preload/**`: the `contextBridge` API (cursor samples, token/port, camera status, hotkey events).
- `overlay/src/renderer/gaze/**`: `GazeProvider`, `webgazer.ts`, `mouse.ts`, `filter.ts` *(exists)*, `blink.ts` (MediaPipe, cut-list item).
- `overlay/src/renderer/dwell/**`: `DwellManager.ts` *(exists)*, `DwellTarget.tsx`, the React context holding the single `DwellManager`.
- `overlay/src/renderer/ws/**` except `protocol.gen.ts`: `client.ts` *(exists)*, `session.ts` *(exists)*, `validate.ts` *(exists)*, `fixtures/` *(exists)*, `test-utils.ts` *(exists)*. To add: `suggestNow()` → `auto_refresh` and `suggestPending` in the session state (true from the send until `suggestions` or an `error` for it).
- `overlay/src/renderer/platform/**` (the interface above).
- `overlay/src/shared/app.ts` *(exists)*.
- Tests for all of the above (`*.test.ts` next to each file).

**WebSocket: sends (through `agent.*`, triggered by A1's UI):**
| message | when |
|---|---|
| `hello` | on every (re)connect, first message; followed by `mode_set` with the last mode |
| `mode_set` | `agent.setMode` (Auto/Type tab dwelled) |
| `gaze_context` | `agent.setDockIdle` (gaze rests on the dock ≥1500 ms with no selection, and again when that ends). Kept for compatibility; it no longer gates model calls (spec §7) |
| `auto_refresh` | `agent.suggestNow` |
| `decode_request` | `agent.decode` |
| `intent_submit` | `agent.submitIntent` |
| `plan_select{list_id, plan_id}` | `agent.selectPlan`. **Never** for `"other"` or `recovery:cancel` (both handled locally) |
| `choice_response{task_id}` | `agent.respondChoice`; `re` = `choice_request` id |
| `confirm_response{task_id}` | `agent.respondConfirm`; `re` = `confirm_request` id |
| `stop` | `agent.stop` (STOP dwelled → `gaze`), and the hotkey (`hotkey`) directly from main |
| `profile_get`, `profile_update`, `settings_update` | Settings screen; state updates only from `profile_result` / `settings_result` |
| `permissions_check` | `agent.checkPermissions` |
| `open_settings_pane` | `agent.openSettingsPane` (Accessibility / Screen Recording; Camera is handled in main) |

**WebSocket: receives** (already reduced in `session.ts`):
- `hello_ack`: resets to the idle dock.
- `permissions_status`: merged with Electron's own camera status.
- `suggestions`: ignored unless the Auto dock is showing; clears `suggestPending`.
- `decode_result`, `plans`.
- `task_status`: the dock collapses to the pill **only** on the first `running` message.
- `choice_request`, `confirm_request` (demo badge when `demo_noop`), `task_result` (recovery cards; `recovery:show_screen` summary).
- `profile_result`, `settings_result`.
- `error`: `task_busy` / `stale_list` / `unknown_plan` refresh the dock rather than crash; clears `suggestPending`. Close code 4401 / 4400 shows an error state.

**Done when:**
0. `pnpm install && pnpm gen:protocol && pnpm -C overlay typecheck` passes, and the regenerated `protocol.gen.ts` has no diff.
1. `pnpm -C overlay typecheck && pnpm -C overlay test` passes, with unit tests for:
   - the One-Euro filter *(exists)*;
   - DwellManager *(exists)*: sticky (+40 px / 150 ms), 100 ms entry delay, 2× decay, 600 ms cooldown with STOP exempt; a simulated tremor stream (±30 px noise) still selects within `dwellMs + 300 ms`;
   - `<DwellTarget>`: registers/unregisters with the manager, sets `data-dwell` and `--dwell-progress`, calls `onSelect` once;
   - mouse provider: IPC cursor samples become `GazeSample`s with confidence 1;
   - WS client *(exists)*: rejects an invalid message; ignores dead `task_id` / superseded `list_id` with the recorded frames; `hello_ack` resets to idle;
   - `suggestNow()`: sends `auto_refresh`, `suggestPending` turns true, and false again on `suggestions` or `error`.

**Human-run** (safety rule in `AGENTS.md`). The agent prepares the exact commands; the human runs them and reports back:

2. STOP hotkey: ⌃⌥⌘. sends `stop{reason:"hotkey"}` and hides the overlay; pressing it again shows it. ⌃⌥⌘M switches between WebGazer and mouse = gaze.
3. Focus and click-through:
   - While the overlay is visible, typing in TextEdit still works.
   - While a fake task is running, a **real mouse click on the pill or on STOP passes through** to the window below. STOP still works by hover-dwell (mouse = gaze reads the cursor from main, not DOM events).
   - When idle, the Onboarding "Open Settings" button is mouse-clickable.
4. Killing the agent process shows "Reconnecting…". After a restart it reconnects, and the UI returns to idle without reloading the app.
5. WebGazer: `calibration.validate` reports the mean error in px. The Camera row shows `granted` / `denied` / `not-determined` correctly.

### Task A1: Screens, styles and the "Suggest now" card

**Owns:**
- `overlay/src/renderer/index.html`, `overlay/src/renderer/main.tsx` (skeleton exists), `overlay/src/renderer/App.tsx` (screen routing from `useSession()`).
- `overlay/src/renderer/dock/**`: dock layout, Auto/Type tabs, suggestion and plan cards, the **"Suggest now"** card, status pill, choice and recovery cards.
- `overlay/src/renderer/keyboard/**`: T9 keyboard, prediction bar, sentence cards, `t9index.ts` *(exists)*.
- `overlay/src/renderer/screens/**`: Confirm, Onboarding (permissions checklist), Calibration (9-dot + 4-dot validation UI, using `calibration.*`), Settings.
- `overlay/src/renderer/stop/**`: the STOP target.
- `overlay/src/renderer/styles/**`: glass style, density presets, dwell ring and flash (from `data-dwell` / `--dwell-progress`), and a visible gaze dot when `useGaze().debug` is true.
- `data/wordlist_en.txt` (~20k words with frequency).
- Tests for all of the above.

**Uses only** `overlay/src/renderer/platform/index.ts`. Every selectable element is a `<DwellTarget>`; no other component implements selection.

**"Suggest now" card** (spec §1, §6.2, §7):
- It is the first card in the Auto dock and a normal `<DwellTarget variant="card">`. Dwelling it calls `agent.suggestNow()`.
- While `suggestPending` is true it shows a spinner and is `disabled`, so repeated dwells don't queue requests.
- Switching **to** the Auto tab (not the app launch) calls `agent.setMode('auto')` and then `agent.suggestNow()` once.
- Suggestions replace the cards next to it; "Something else → Type" stays last.

**Develops against:** `scripts/dev.sh` (fake agent + `GAZE_SOURCE=mouse`). Until A2's real implementation lands, A1 works on A2's mouse-only stub of `platform/index.ts`.

**Done when:**
1. `pnpm -C overlay typecheck && pnpm -C overlay test` passes, with unit tests for:
   - `t9index` *(exists)*: `"8355"` → includes `"tell"`; a profile phrase outranks a common word with the same keys;
   - "Suggest now": dwell calls `suggestNow` once; spinner and `disabled` while pending; switching to the Auto tab calls it once; launching in Auto does not;
   - Confirm screen: CONFIRM bottom-left uses `max(1500, dwellMs×1.5)`, CANCEL top-right, 60 s auto-cancel sends `false`, "DEMO: will not purchase" badge when `demo_noop`.

**Human-run:**

2. With the fake agent spawned via `scripts/dev.sh` (mouse = gaze), a person using **only mouse hovering, no clicks**, completes all four fake flows D1–D4:
   - "Suggest now" → spinner → suggestions;
   - Type → T9 → DONE → sentence cards → plan cards;
   - status pill with step n/15;
   - choice cards;
   - confirm screen as above;
   - result;
   - the recovery path, including the "Show me the screen" card.
3. Dwelling STOP (400 ms, top-right, never covered) sends `stop{reason:"gaze"}`.
4. Calibration: the 9-dot and 4-dot screens run and show the mean error from `calibration.validate`.

---

## Task B: Agent server (Python runtime + screen understanding + desktop actions)

This is the original Mac runtime task. The current [backend Lane B](#backend-lane-b-current-scope-and-checks) owns LLM, prompts and planning; [backend Lane C](#backend-lane-c-task-loop-and-integration) owns the loop and integration follow-up.

Spec: §4 (server side incl. §4.4), §8.1–8.4, §10, §11 (agent side). B owns the socket and everything that touches macOS.

**Owns:**
- `agent/gaze_agent/server.py`:
  - binds 127.0.0.1 only, `GAZE_TOKEN` auth (4401), validation, `bad_message`, `version_mismatch` (close 4400);
  - routing, `re` correlation per §4.1;
  - the current-list registry (`list_id` → plans; a new list replaces the old one);
  - one active task;
  - disconnect = stop.
- `agent/gaze_agent/loop.py`:
  - OpenAI function-tool definitions (§8.2) and the task loop: builds `input_items` and calls `complete()`;
  - limits: 15 calls / 90 s (excluding `waiting_user`) / 2 retries;
  - `stop` within 200 ms; it cancels pending choice and confirm waits;
  - calls `safety.gate` before `click_element`, `press_keys` and `type_text{submit:true}`, and re-checks that the task is alive after the confirm wait;
  - contact-alias ambiguity (§8.3);
  - recovery plans (`recovery:retry`, `recovery:show_screen`);
  - `AutoWatcher` lifecycle duties (Phase 0 §4).
- `agent/gaze_agent/screen/__init__.py` (+ `__main__.py`), `screen/ax.py`, `screen/ocr.py`, `screen/shot.py`:
  - AX snapshot → compact list (≤150, including the focused element);
  - Vision OCR on a **window-only** capture (`screencapture -x -o -l <id>`), with bboxes offset to screen coordinates;
  - `look_at_screen`.
- `agent/gaze_agent/actions.py`:
  - AXPress → Quartz click → pyautogui;
  - AXValue → clipboard paste (saves and restores the clipboard) → per-key typing;
  - keys, `open_app` (profile aliases), `open_url`;
  - releases held modifiers.
- `agent/gaze_agent/permissions.py`: `AXIsProcessTrusted`, `CGPreflightScreenCaptureAccess`, a one-time `CGRequestScreenCaptureAccess`, `open x-apple.systempreferences:…`.
- `agent/gaze_agent/profile.py`: store, merge-patch, settings validation, demo-profile copy on first run.
- `agent/gaze_agent/tasklog.py`: JSONL, 7-day prune.
- `agent/tests/runtime/**`.

**Does not touch:** `llm.py`, `planner.py`, `auto.py`, `safety.py`, `prompts/**`, `protocol/**`, `contracts.py`. B calls these only through the Phase 0 signatures.

**WebSocket: receives (all of §4.2)**
| message | handled by → reply |
|---|---|
| `hello` | B → `hello_ack` (`re` = hello id) |
| `mode_set`, `gaze_context`, `auto_refresh` | forwarded to `AutoWatcher` (C); no reply |
| `decode_request` | `planner.decode` (C) → `decode_result` (`re` = request id) |
| `intent_submit` | `planner.make_plans` (C) → B assigns `list_id` → `plans` (`re` = request id) |
| `plan_select` | `stale_list` / `unknown_plan` / `task_busy` check → `task_status{running, step:0}` (`re` = plan_select id) → loop |
| `choice_response`, `confirm_response` | resume the waiting task if `task_id` matches; else `error{no_task}` |
| `stop` | cancel the task + waits, release keys → terminal `task_status{stopped}` + `task_result`; no-op if idle |
| `profile_get` / `profile_update` | `profile_result` |
| `settings_update` | `settings_result` or `error{bad_message}` |
| `permissions_check` | `permissions_status` |
| `open_settings_pane` | runs `open …`; no reply |

**WebSocket: sends:**
- `hello_ack`, `permissions_status`, `task_status`, `choice_request`, `confirm_request` (built from C's `GateDecision`; `demo_noop` set for `buy` when `DEMO_MODE=1`), `task_result`, `profile_result`, `settings_result`, `error`;
- it also sends C's outputs as `suggestions` (with a `list_id`), `plans` and `decode_result`.

**Develops against:** `scripts/fake_overlay.py` (Task D), plus the Phase 0 stubs for C's modules. In unit tests, use monkeypatched fakes for `complete`, `gate` and `make_plans` rather than C's stubs.

**Done when:**
1. `cd agent && uv run pytest tests/runtime` passes, with tests for:
   - Connection: a wrong or missing token gives close code 4401; an invalid message gives `error{bad_message}`; `v:2` gives `version_mismatch` + close 4400.
   - `uv run scripts/fake_overlay.py demo stop_during_confirm task_busy stale_list settings bad_input` passes against the **real** agent (with a scripted fake `complete()`).
   - Races (§4.4):
     - `stop` during a fake 10 s tool → `task_status{stopped}` in <200 ms;
     - `stop` while a confirm is pending, then `confirm_response{true}` → the action is **never** executed;
     - `plan_select` during a task → `task_busy`;
     - an old `list_id` → `stale_list`;
     - disconnect mid-task → the task is cancelled and `set_task_running(False)` is called.
   - Loop limits: the 16th call → `task_result{ok:false, list_id, recovery}`. Time in `waiting_user` is not counted toward 90 s.
   - AX compaction of a recorded fixture tree: ≤150 lines in the exact format, with the focused element populated.
   - A stale `snapshot_id` → tool error `stale_snapshot`.
   - tasklog prunes entries older than 7 days; no message bodies are logged when `DEBUG=0`.
**Items 2–5 are human-run** (safety rule in `AGENTS.md`: agents never run code that clicks, types or takes screenshots). The agent builds and unit-tests the code against fixtures and fakes, then hands the human the exact commands.

2. On a Mac with permissions granted to the terminal:
   - `uv run python -m gaze_agent.screen` prints a snapshot of the frontmost window (Messages: shows the compose field and the Send button or equivalent);
   - on a canvas app (or with AX forced off), the same command prints `o…` OCR elements whose coordinates land on the right text;
   - with the overlay running, the OCR output contains **no overlay text**.
3. Live, with a real key: `python scripts/fake_overlay.py` → `intent "open TextEdit and type hello world"` → `select 1`:
   - TextEdit opens and the text appears, followed by `task_result{ok:true}`;
   - the user's clipboard is unchanged afterwards.
4. Live: a task that reaches Messages' send step emits `confirm_request{action:"send"}` and does **not** send until `confirm yes`.
5. Revoking Screen Recording for the terminal → `permissions_status{screen_recording:false}` within one check. Nothing crashes.

---

## Task C: Planner, prompts & policy

This is the original build Task C. For the current backend task-loop/testing assignment, see [Backend Lane C](#backend-lane-c-task-loop-and-integration).

Spec: §6.3 (decode), §7, §8.5, §8.6, §9.1–9.4, all prompts. C owns everything that decides *what* to do: every LLM call, every prompt, and the rule gate. C has **no socket code**. It returns data that B sends.

**Owns:**
- `prompts/task_system.md`, `plan_intent.md`, `auto_suggest.md`, `sentence_decode.md`, `look_at_screen.md`. The placeholders are fixed by Phase 0, and no prompt text may live in code.
- `agent/gaze_agent/llm.py`:
  - `render`, and `complete` on the OpenAI Responses API, mapping model slots to env vars;
  - returns `LLMResponse`; cancellation aborts the request;
  - record/replay cache (key = sha256 of prompt name + model + normalized input, with timestamps, ids and coordinates removed and snapshots reduced to role+label).
- `agent/gaze_agent/planner.py` (+ `__main__` CLI): `make_plans` and `decode`.
  - `make_plans` resolves profile references into the label, keeps labels ≤40 chars and imperative, appends `{id:"other", kind:"other"}`, and sets `risky`.
  - **This file is new:** the spec puts this logic in "agent core"; it is split out here so B and C don't share files.
- `agent/gaze_agent/auto.py`: `AutoWatcher`.
  - Polls `window_info()` at 1 Hz and applies the 5 trigger conditions in §7.
  - 1.5 s debounce; 10 s minimum interval (bypassed by refresh); LRU of 20 keyed by `(window_key, content_hash)`.
  - Rechecks mode, task and window state after the LLM call and drops stale results (§4.4).
- `agent/gaze_agent/safety.py`: `gate()` with the label, description, key, focused-element, app and URL rules from §9.1. It merges the model flag (§9.2) into `source`, and builds `title`/`details` from the real target.
- `agent/replay/cache/**` (recorded Sun 16:00 with the demo profile only).
- `agent/tests/brain/**`.

**Does not touch:** `server.py`, `loop.py`, `screen/**`, `actions.py`, `profile.py`, `protocol/**`, `contracts.py`.

**WebSocket (indirect; through B):**
| C consumes the data from | C produces the payload for |
|---|---|
| `intent_submit.text` | `plans.items` (2–4 + "Something else"); B adds `list_id` |
| `decode_request.{words, raw_keys, context}` | `decode_result.sentences` (1–3) |
| `mode_set`, `gaze_context`, `auto_refresh` | `suggestions.{window_key, app, items (3–4), cached}`; B adds `list_id` |
| (each risky tool call, inside B's loop) | `confirm_request.{action, title, details, source}` via `GateDecision` |

**Develops against:** `contracts.py` with fake `Snapshot` / `WindowInfo` objects. C needs no Mac permissions for its tests.

**Done when:**
1. `cd agent && uv run pytest tests/brain` passes, with tests for:
   - safety table (≥40 rows). It must include:
     - `"Send"` → send; `"Reply All"` → send; `"Place order"` → buy; a button whose *description* (not label) is "Send" → send; `"Move to Trash"` in Finder → delete;
     - `cmd+enter` → required; `enter` with the focused element in a Messages compose field → required; `enter` in TextEdit → **not** required;
     - URL `/checkout` → required;
     - a model flag with no rule match → `source:"model"`; both → `"both"`;
   - `AutoWatcher` with a fake clock and a scripted window stream:
     - no call before the 1.5 s debounce;
     - no second call within 10 s;
     - `refresh()` bypasses the 10 s limit;
     - returning to a seen window → `cached:true` with zero LLM calls;
     - LRU evicts the 21st entry;
     - no calls in `type` mode or while a task runs;
     - `set_task_running(True)` **during** an in-flight LLM call → the result is dropped, not emitted;
   - replay: two inputs that differ only in ts/ids/coordinates produce the same key; a miss in replay mode with no network → `LLMError`;
   - `complete()` cancelled mid-request raises `CancelledError` promptly (fake transport);
   - a test greps `agent/gaze_agent/` and fails if prompt text appears inline;
   - plans: every result validates against `#/$defs/Plan` in `protocol/messages.schema.json`, the last item is `"other"`, every label is ≤40 chars.
2. Live (`REPLAY=record`, demo profile):
   - `uv run python -m gaze_agent.planner intent "tickets for my favorite artist"` → 2–4 plans whose label contains the demo persona's artist name and site;
   - `… planner decode --words tell mom --raw GHI,ABC` → 1–3 sentences.
3. The same two commands with `REPLAY=replay` and **Wi-Fi off** return identical output.

---

## Task D: Harness & demo

Spec: §1 demo table, §10 (fixture), §12.2–12.4, README. D provides the stand-ins that let A and B work without each other, plus the final rehearsal gate.

**Owns:**
- `scripts/gaze_client.py`: an async overlay-side client (connect with token, send, `wait_for(type, task_id=…)`, schema validation). It is shared by the two scripts below.
- `scripts/fake_overlay.py`: an interactive CLI on top of `gaze_client` (`intent "…"`, `select N`, `choose N|cancel`, `confirm yes|no`, `stop`, `mode auto|type`, `refresh`). It prints every incoming message.
- `scripts/fake_agent.py`: a WS server playing the **agent** side.
  - It reads `GAZE_TOKEN`/`GAZE_PORT` from the environment, so Electron can spawn it via `GAZE_AGENT_CMD`.
  - It serves the D1–D4 / recovery flows from a built-in plan catalog, reacting to each overlay message, with realistic delays.
  - It implements every §4.4 rule: one task, `list_id`s, stale/busy errors, stop wins, disconnect = stop.
- `scripts/rehearse.py`: runs D1–D4 through `gaze_client` with `REPLAY=replay DEMO_MODE=1`, auto-answering choices and confirms, and prints PASS/FAIL + timings. `--target fake` spawns `fake_agent`; the default target is the real agent.
- Moved here from Phase 0 (items 6–8): `scripts/check_secrets.sh` (do this first: the repo is public), `scripts/dev.sh`, `.github/workflows/ci.yml` (runs `cd agent && uv run pytest`, `uv run scripts/fake_overlay.py demo --spawn`, the secrets check, and A's overlay tests once they exist), and a `.gitignore` comment saying `agent/replay/cache/` is tracked on purpose.
- `fixtures/demo_profile.json`: fake persona (Mom contact = a handle the team controls, favorite artist, playlist, ticket site from §14, phrases).
- `README.md`:
  - run instructions;
  - **permissions go to the terminal app** (§4), and the terminal must be relaunched after granting;
  - rehearsal steps.
- `scripts/tests/**`.

**Does not touch:** anything under `overlay/`, `agent/`, `prompts/` or `protocol/`. If the schema is wrong, open a protocol PR.

**WebSocket:**
- `fake_agent.py` **receives** every §4.2 message and **sends** every §4.3 message. Each step is an overlay message paired with the agent replies it triggers, e.g. D1:
  1. `intent_submit` → `plans{list_id}`
  2. `plan_select` → `task_status{running}` … `task_status{running, step n}` → `confirm_request{send}`
  3. `confirm_response{true}` → `task_status{done}` → `task_result{ok:true}`
- `gaze_client.py` (and therefore `fake_overlay.py` and `rehearse.py`) **sends** §4.2 messages and **receives** §4.3 messages, applying the same `task_id`/`list_id` filtering as the overlay.

**Priority inside D:** ship `gaze_client.py`, `fake_overlay.py` and `fake_agent.py` first (target Sat 16:00), because A and B develop against them.

**Done when:**
1. `uv run pytest scripts/tests` passes:
   - `demo_profile.json` validates against `profile.json`;
   - every message `fake_agent` can emit validates against its schema;
   - `gaze_client` drops messages for a dead `task_id`.
2. `python scripts/rehearse.py --target fake` prints `PASS` for D1–D4, plus a `PASS` for each extra flow: `stop_during_confirm`, `stale_list`, `task_busy`, `recovery_show_screen`.
3. `scripts/check_secrets.sh` passes, and the fixture contains no real personal data.
4. **Integration check, human-run (needs A, B and C merged; this is the Sun 16:00 gate):** run from the stage terminal, with the real agent and the recorded cache. `REPLAY=replay DEMO_MODE=1 python scripts/rehearse.py` prints 4× PASS, and D4 stops at the BUY confirm without purchasing.

---

## Ticket E: Auto-mode cost controls (Python, follow-up)

Spec: §1, §7 (rewritten), §8.1. Runs after B and C are merged; it takes over the files below from them.

**Owns:**
- `agent/gaze_agent/auto.py`, `agent/gaze_agent/llm.py`, `agent/gaze_agent/tasklog.py`.
- `agent/gaze_agent/screen/shot.py`, plus `screen/__init__.py` (the capture decision in `get_screen`) and `screen/ocr.py` (recognition level), which the screenshot rule needs.
- In `agent/gaze_agent/server.py`: only the `GAZE_AUTO_AMBIENT` setting, the usage summary at disconnect, and the `window_key` comparison in `Session.suggestions()`. It must use the same `normalize_window_key()` from `auto.py` on both sides, and the `suggestions` payload carries the normalized key.
- Tests: `agent/tests/brain/test_auto.py`, `agent/tests/brain/test_llm.py`, `agent/tests/runtime/test_screen_store.py`, and new `agent/tests/cost/**`.
- Mock parity: `scripts/fake_agent.py` and the `d2` flow in `scripts/fake_overlay.py` (see 4).
- Appending `GAZE_AUTO_AMBIENT=0` and the empty `OPENAI_PRICE_*` lines to `.env.example` (tell A2 in the PR).

**Work:**
1. **Model call only on a meaningful change** (`auto.py`):
   - keep the 1 Hz AX-only poll;
   - `window_key` uses the normalized title (lowercase, digits and counters such as `(3)` removed, whitespace collapsed);
   - trigger on an app change, a normalized title change, or a content change of >30% of elements **and** ≥40 characters of new label text;
   - remove the `dock_idle` gate (the overlay never sent `gaze_context`); keep the 1.5 s debounce and the 20-entry cache, keyed on the normalized key.
2. **Cooldown** (`auto.py`):
   - `AUTO_COOLDOWN_S = 20` (env-overridable) between ambient calls;
   - set the last-attempt time **before** `get_screen()`. This fixes today's bug: a failing screenshot or a title change during the read retries every 1–1.5 s;
   - `auto_refresh` bypasses the cooldown but has its own 3 s minimum gap; extra requests inside 3 s are ignored.
3. **Screenshots in Auto** (`screen/__init__.py`, `shot.py`, `ocr.py`):
   - capture only when AX has fewer than 3 labelled elements **and** fewer than 80 characters of label text;
   - downscale with the existing `sips -Z 1280` (JPEG) before OCR, and use Vision's Fast recognition level;
   - at most 1 per 60 s, counted from the last capture **attempt**; inside the window, reuse the last OCR result for the same `window_key`, else AX text only;
   - Type requests (`intent_submit`) and task steps keep the §8.1 behavior: pass an `auto=True` flag (or a separate function) rather than changing `get_screen()` for everyone.
4. **Auto off by default, agent side** (`server.py`, `auto.py`):
   - `GAZE_AUTO_AMBIENT=0` (default): the watcher still polls but calls the model only on `auto_refresh`. `=1` enables (1)–(3);
   - mock parity: `fake_agent.py` honors the same variable (default 0: suggestions only after `auto_refresh`), and the `d2` flow sends `auto_refresh` instead of `gaze_context`. `demo --spawn` still passes.
5. **Cost log** (`llm.py`, `tasklog.py`, `server.py`):
   - `_live()` returns `response.usage` input/output tokens on `LLMResponse`; replay hits count as 0;
   - a per-session `UsageMeter` counts calls, tokens and estimated USD per prompt (`auto_suggest`, `make_plans`, `decode`, agent steps, `look_at_screen`);
   - prices come from `OPENAI_PRICE_<AGENT|FAST|VISION>_<IN|OUT>` (USD per 1M tokens); a missing price logs `est_usd: null` and warns once; nothing is hardcoded;
   - a `usage` row goes to the task log every 5 minutes and at disconnect, and the agent prints a one-line summary when it stops. No prompt text or screen content in the row.

**Test plan** (no real desktop; safety rule in `AGENTS.md`):
- **Fake clock:** inject `clock` into `AutoWatcher` (and the screenshot limiter) instead of `time.monotonic`, and drive `_tick()` directly. No `sleep`.
- **Desktop fakes:** reuse `agent/tests/runtime/conftest.py`'s `prohibit_real_desktop`; feed `WindowInfo` / `Snapshot` sequences from fakes; count `capture_window` calls with a fake. Fake `llm.complete` returns fixed plans and usage and counts calls.
- Cases:
  - title "Inbox (3)" → "Inbox (4)": 0 calls; real title change: 1 call;
  - `Session.suggestions()`: a "Inbox (3)" → "Inbox (4)" change before the emit still sends the suggestions; a real title change drops them;
  - 35% element change with <40 new characters: 0 calls; with ≥40: 1 call (after the cooldown);
  - two window changes 10 s apart: 1 call; 21 s apart: 2 calls;
  - `get_screen` raises: next attempt only after 20 s, not 1 s;
  - `auto_refresh` inside the cooldown: 1 call; a second one within 3 s: ignored;
  - ambient off: window changes cause 0 calls; `auto_refresh` causes 1;
  - sparse AX (2 labels, 30 chars): 1 capture, then 0 more for 59 s on any window, then 1 at 60 s; 5 labels or ≥80 chars: 0 captures;
  - the captured image is downscaled before OCR (fake `sips` records its arguments);
  - usage: three fake calls with known tokens and prices give the expected `est_usd`; a missing price gives `null` and one warning; replay hits are 0;
  - the `usage` row has no prompt or screen text.
- Plus `uv run --project agent pytest agent/tests scripts/tests` and `uv run scripts/fake_overlay.py demo --spawn` both pass.

**Human-run:** with `DEMO_MODE=1` and the real agent, leave Auto on for 10 minutes while switching between Mail, Messages and Safari, once with `GAZE_AUTO_AMBIENT=0` and once with `=1`. Report the `usage` rows.

---

## Ownership summary (no overlap)

The table records the original build assignments. The backend follow-up lane A, B and C sections above replace ownership only for their explicitly listed paths; all other assignments still apply. This integration workspace is authorized to combine and fix work across those three backend lanes, keeping shared contracts frozen.

| Path | Owner |
|---|---|
| `protocol/**`, `agent/gaze_agent/contracts.py`, `agent/gaze_agent/protocol.py`, `agent/gaze_agent/__init__.py`, `agent/tests/test_{contract,prompt_vars,stubs}.py`, `agent/pyproject.toml`, `agent/uv.lock`, `overlay/src/renderer/ws/protocol.gen.ts` (generated) | Phase 0 (frozen; changes go through a protocol PR) |
| `overlay/src/{main,preload}/**`, `overlay/src/renderer/{gaze,dwell,ws,platform}/**` (except the generated file), `overlay/src/shared/**`, `overlay/scripts/**`, overlay config files (`package.json`, `electron.vite.config.ts`, `tsconfig*.json`, `vitest.config.ts`), root `package.json`, `pnpm-workspace.yaml`, `pnpm-lock.yaml`, `.env.example` | A2 |
| `overlay/src/renderer/{index.html,main.tsx,App.tsx}`, `overlay/src/renderer/{dock,keyboard,screens,stop,styles}/**`, `data/**` | A1 |
| `agent/gaze_agent/{server,loop,actions,permissions,profile,tasklog}.py`, `agent/gaze_agent/screen/**`, `agent/tests/runtime/**` | B |
| `agent/gaze_agent/{llm,planner,auto,safety}.py`, `prompts/**`, `agent/replay/**`, `agent/tests/brain/**` | C |
| `scripts/**` (mocks, `rehearse.py`, `dev.sh`, `check_secrets.sh`, `tests/`), `fixtures/**`, `.github/**`, `.gitignore`, `README.md` | D |
| After B and C merge: `agent/gaze_agent/{auto,llm,tasklog}.py`, `agent/gaze_agent/screen/{__init__,shot,ocr}.py`, the `GAZE_AUTO_AMBIENT`, usage-summary and `Session.suggestions()` window-key lines in `server.py`, `agent/tests/brain/test_{auto,llm}.py`, `agent/tests/runtime/test_screen_store.py`, `agent/tests/cost/**`, `scripts/fake_agent.py` + the `d2` flow (mock parity), appended `.env.example` lines | E |

Adding a dependency to `pyproject.toml` or `package.json` after Phase 0 is the only allowed shared edit: keep it to a one-line change in its own commit, so it rebases cleanly.

## Cut list (unchanged from spec §13, mapped to tasks)
1. Blink select (A2)
2. OCR fallback (B)
3. Pinned favorites (A1)
4. Caregiver calibration (A1)
5. Auto content-hash trigger (E)
