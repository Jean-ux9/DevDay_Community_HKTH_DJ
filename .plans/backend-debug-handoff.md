# Backend stabilization handoff

Read `AGENTS.md`, the current-priority section at the top of `.plans/tasks.md`,
and the build spec before changing code. This handoff is for a **new workspace**;
never inspect or edit the previous workspace or other worktrees.

## Follow-up stabilization: 2026-10-25, base `3938bbc`

The new workspace began clean at `3938bbc`. A fresh `git fetch origin main`
confirmed that `origin/main` was also `3938bbc`, with `6d46172` and `cff07f8`
as ancestors. The delivered live-AX focus, bounded launch-readiness and ordered
key-release fixes are present. No other worktree was inspected; `.env` existence
alone was checked, without reading its contents. The inherited suite's profile
isolation exception is recorded under #11 below. Initial validation ran without
committing or pushing. The human subsequently explicitly authorized committing
and pushing both `.env.example` and these backend changes to GitHub `main`.
Verify the published follow-up commit using Git; the local `main` checkout in
another worktree must not be switched or edited.

The human also explicitly requested non-secret defaults in `.env.example`:
all three model slots use `gpt-6.1-sol`, with Agent/Vision `xhigh` and Fast `low`.
API key and prices remain empty. This is an authorized exception to the original
empty-template instruction; it does not change or establish private `.env` values.

### Bug and evidence matrix

| Item / original owner | Evidence and current result | Remaining boundary |
|---|---|---|
| [#6](https://github.com/Jean-ux9/DevDay_Community_HKTH_DJ/issues/6), A / C integration | Delivered launch/focus/key-release regressions pass with native fakes. | Actual launch/focus and complete TextEdit/clipboard tests remain human-run; keep open. |
| [#7](https://github.com/Jean-ux9/DevDay_Community_HKTH_DJ/issues/7), D harness | **Done.** Fixed local Cancel/Other, actionable select/choose/confirm hints, positive bounded indices, invalid-answer preservation, stale wait and pending-selection cleanup (delivered in `7e4f674`). Re-verified against the real REPL handler/client with in-memory sockets and the fake agent; `3ad3d71` fixed the two remaining gaps (idle `choose`/`confirm` now points to `select N`; a failed send exits the REPL cleanly) and added 24 regressions in `scripts/tests/test_cli_repl.py`. Harness 26 + CLI 24 pass, mock protocol 11/11; all nine mutations of the fix were caught. Raw client selection still supports server negative tests. | No real REPL task was run; a human usability check is optional. The humans merge to `main` and close the issue. |
| [#9](https://github.com/Jean-ux9/DevDay_Community_HKTH_DJ/issues/9), C + A | Fake reproduction showed approval surviving changed context. Recheck the full observed context after confirmation; reject changes/read failure, uniquely rebind unchanged IDs, and retain/verify internal native window/focus identity before desktop dispatch. STOP still wins; BUY no-op and Cancel remain covered. | Fake evidence only. Context changes conservatively fail the task; dynamic title/text changes may therefore need a fresh attempt. Native behavior is unverified and OS races cannot be ruled out by a finite suite. |
| [#10](https://github.com/Jean-ux9/DevDay_Community_HKTH_DJ/issues/10), C, coordinate B | Fake reproduction showed incidental alias/handle labels and partial title matches satisfying the demo allowlist. Require a complete recipient token in the conversation/compose title and ignore unrelated element labels. Positive and negative fake cases pass. | Title matching is conservative, not verified extraction of an app's actual recipient. Unknown title formats fail closed. This does not resolve #5 or authorize real sends. |
| [#11](https://github.com/Jean-ux9/DevDay_Community_HKTH_DJ/issues/11), C test safety, coordinate D/Phase 0 | Found an inherited root-level stub test calling the default profile loader. Added suite-wide temporary ProfileStore/TaskLog defaults, explicit private-storage rejection and fake-client/API-key guards, plus two isolation regressions. | Initial/intermediate unguarded suite runs may have read an existing active profile or created a default if absent. Contents were not printed. No private file was opened for inspection or deleted/restored. Earlier broad no-profile-read claims were corrected in the public issue updates. |
| [#5](https://github.com/Jean-ux9/DevDay_Community_HKTH_DJ/issues/5), B / C | Current runtime, recording and rehearsal guards were re-read and still require the exact synthetic fixture. No guard was disabled or private profile/cache configured. P04 then added the opt-in provider (`demo_config.py`), a private `ProfileStore`, the manifest-only Send allowlist, a private replay namespace and the recording guard, with synthetic tests; see below. | The server/rehearsal/conftest consumer patch is pending its owners. The actual persona, recipients and folders remain human decisions after Stage 1/2. Keep `GAZE_DEMO_CONFIG` unset for real runs until both are done. Separate-account setup is still future human work. |
| [#4](https://github.com/Jean-ux9/DevDay_Community_HKTH_DJ/issues/4), A docs | Delivered HUMAN_CHECKS configuration/effort/ownership guidance matches current source. Stage 1 now distinguishes shell input, current-account expectations and all replay/Send modes. | No native success inferred from documentation review; no issue closed. |

Additional audit coverage remains in the combined suite: threaded activation
cancellation, key release and STOP, stale IDs, multi-format clipboard save/restore
including cancelled paste, OCR budgets/window identity/failure fallback, strict
cache misses/malformed responses with zero HTTP, model cancellation and errors,
latest-list replacement and disconnect cleanup. These rows identify finite fake
coverage, not new reports of real incidents or a claim that all bugs are gone.

### Checks on these follow-up changes

| Command | Actual result |
|---|---|
| `uv run --project agent --python 3.12 pytest agent/tests scripts/tests --tb=short` | PASS: 517 tests with the suite-wide isolation guard and both isolation regressions, Python 3.12.15, exit 0. Baseline before changes was 449 PASS. |
| `uv run scripts/fake_overlay.py demo --spawn` | PASS: all 11 flows, exit 0. |
| `uv run scripts/rehearse.py --target fake` | PASS: all 9 cases, exit 0. Fake lifecycle regression only, no real-app rehearsal. |
| `sh scripts/check_secrets.sh` / `git diff --check` | PASS: Secret scan passed / clean diff, exit 0. |
| Stage 1 Python blocks, `compile()` only | PASS: four blocks compile; no diagnostic or permission command executed. |

Focused new loop regressions first failed against the old implementation for
changed context/fresh-ID handling and incidental/partial recipient matching.
The old CLI also failed displayed-command and stale-wait assertions. Further
native-window/STOP cases cover the fix without running native actions.

No schema, shared contracts, generated types, prompt bodies/placeholders,
dependencies, fixture data or recorded caches changed. No private environment
values, clipboard, real AX contents or user backup was inspected. See #11 for
the inherited test's possible profile read/default creation before isolation.
No overlay checks were rerun because overlay code is unchanged.
No live API call, native launch probe, capture, mouse/key/typing action, actual
Send, recording or real rehearsal was run. Only Stage 1 is provided now; wait
for the human's sanitized results before advancing.

## P04 follow-up: private demo provider (#5), base `48abe9d`

Branch `private-demo-provider-8eef5fcd`. Verify the published commit with Git;
this section does not claim the work is on `main`. The full API, the manifest
example with fake values, the evidence and the exact consumer patch are in
[`lambda-reports/P04.txt`](lambda-reports/P04.txt); the human-facing summary is in
`agent/replay/README.md`.

- **Done (fakes only):** `GAZE_DEMO_CONFIG` names an absolute manifest path and
  requires `DEMO_MODE=1`. The manifest holds the persona, `approved_recipients`
  (exactly the persona's contacts), and private `data_dir`/`cache_dir` outside
  every Git work tree and outside the default user store. The private
  `ProfileStore` rejects contacts outside the allowlist. Record/replay use
  `cache_dir/<config_id>-<fingerprint>`. The recording guard checks the
  selected persona. Replay stays strict. With the selector unset, nothing changes.
- **Checks run:** Python 3.12 suite 611 passed (baseline 517); mock protocol
  11/11; fake rehearsal 9/9; secret scan and diff checks passed. On a clean
  `HEAD` export, the consumer patch on top passed 615 tests, 9/9 and 11/11.
- **Not run:** live API, desktop actions, real rehearsal, overlay tests. The
  `check_planner.py`/`check_prompts.py` command lines were not run because they
  load `.env`; the shipped-cache replay passed in-process.
- **Remaining:** owners apply the consumer patch (`server.py`: shared store and
  `store.approved_contacts()`; `scripts/rehearse.py`: compare with the selected
  persona and drop the selector for `--target fake`; `agent/tests/conftest.py`:
  `delenv("GAZE_DEMO_CONFIG")` for #11). The human then chooses the actual
  persona, recipients and folders and writes the manifest outside Git. Prompt
  body changes require honest re-recording, never rekeying.

## Original delivery contents

The checkpoint combines backend integration `6d46172`, upstream main `cff07f8`,
and the lane A launch/focus/keyboard fixes. The delivery commit has both histories
as parents. The user authorized merging this result into GitHub `main`; verify
the actual published commit/ancestry before starting a new workspace from it.
If these files or the AX-focused-application fix are missing, report the mismatch
instead of silently working on the old code.

The old A/B/C remote branches were deleted after preserving their work in the
integration. Their names in historical task sections are not current fetch targets.
Private `.env` files, actual profiles/backups and temporary connection files were
not copied into Git or this handoff.

## Checks on the combined delivery tree

These commands were actually run after upstream main and the backend fixes were
combined in the same worktree, using native/LLM fakes. No desktop test ran.

| Command | Result |
|---|---|
| `uv run --project agent --python 3.12 pytest agent/tests scripts/tests --tb=short` | 449 passed, Python 3.12.15, exit 0 |
| `uv run scripts/fake_overlay.py demo --spawn` | 11/11 flows PASS, exit 0 |
| `uv run scripts/rehearse.py --target fake` | 9/9 cases PASS, exit 0 |
| `pnpm install --frozen-lockfile --ignore-scripts` | PASS, pnpm 9.15.9 |
| `pnpm -C overlay typecheck` | PASS, exit 0 |
| `pnpm -C overlay test` | 28 files / 241 tests passed, exit 0 |
| `sh scripts/check_secrets.sh` and `git diff --check` | PASS before delivery |

Node 24.22.1 was used for overlay checks. A new workspace must run appropriate
checks itself; this table is evidence for this checkpoint, not a future change.
No real app activation, typing, clicks, screenshots, live OpenAI request, delivery,
music playback, ticket flow or offline real-app rehearsal was run by the agent.
The old 431-test integration and lane-specific results in tasks.md are historical.

## Human state to carry forward

- The human's tools, ignored key presence/model settings and AX/Screen Recording
  permissions were checked in the previous workspace. New workspace/account
  settings are unverified until Stage 1 runs there. Backend camera `unknown` is
  expected; actual camera access remains unverified.
- An existing profile was backed up and verified outside the repo. No settings
  file existed then. Do not read, replace or copy the private backup automatically.
- Harmless Messages AX/OCR was reported good by the human. No raw AX output or
  screenshot was supplied to the agent or posted in issues.
- The original live TextEdit task failed. The human correctly used `choose 1`,
  but direct launch was still not verified from the observed screen. Some
  confusion came from bare numbers, `select` versus `choose`, and broken local
  recovery Cancel. The STOP terminal sequence worked during a pending choice.
  Those CLI problems are fixed (#7, `3ad3d71`).
- A recovery `Show me the screen` summary with `ok:true` does not prove the
  original task succeeded. Clipboard testing was inconclusive after copying logs.
- Manual `open -a TextEdit` showed TextEdit's Open dialog with Stage Manager on
  and off; New Document produced a blank document. Opening an app does not imply
  creating a document. Stage Manager has not been established as the cause.
- The updated zero-OpenAI launch/focus checker needs an explicit PASS/error; the
  user clarified that a document chooser is an acceptable result. Full updated
  hello-world/clipboard/native-key delivery tests still need a human retest.
- The human wants backend bugs addressed before any demo run. They plan a
  separate macOS account called `GazeDemo` later. Do not create it, assume it
  exists, or assume it inherits settings/accounts/permissions from this account.

## Open work and owners

1. **A / C integration, issue #6:** validate the new AX focus/launch readiness/key
   fixes with fakes, then request the small human launch check before live typing.
   Keep the issue open until actual native behavior is confirmed.
2. **D CLI harness, issue #7: done.** Local `recovery:cancel` / `other` handling,
   actionable `select N` versus `choose N` prompts and wait-state cleanup are
   verified, with the last gaps fixed in `3ad3d71`. The server still never
   executes local Cancel, and the frozen protocol is unchanged.
3. **B / C, issue #5:** the opt-in private provider and storage now exist (P04,
   above). The server and rehearsal still require the exact tracked fake fixture
   until the consumer patch lands. After that, agree the actual private persona,
   allowlist and storage folders before actual sends/recording. Never put real
   handles in tracked fixtures/caches or disable demo safeguards to bypass this.
4. **A docs, issue #4:** the stale reasoning/configuration/ownership instructions
   were corrected in `screen/HUMAN_CHECKS.md`; verify the delivered guide before
   closing the report.

Issues: https://github.com/Jean-ux9/DevDay_Community_HKTH_DJ/issues/4,
https://github.com/Jean-ux9/DevDay_Community_HKTH_DJ/issues/5,
https://github.com/Jean-ux9/DevDay_Community_HKTH_DJ/issues/6.

Also audit the targeted edge cases in tasks.md. Add meaningful regression tests
for confirmed bugs, keep an explicit evidence matrix, and do not promise that a
finite suite proves the whole backend bug-free.

## Copyable prompt for the next agent

```text
Continue backend stabilization in this NEW workspace. Read AGENTS.md,
.plans/gaze-copilot-spec.md, the current-priority section of .plans/tasks.md,
.plans/backend-debug-handoff.md and .plans/backend-human-testing.md first.
Verify that this workspace contains the delivered main checkpoint and the live
AX focus / verified app launch / ordered key-release fixes. Inspect Git status
and preserve all existing local changes. Stay inside this workspace.

The priority is to find and fix backend bugs, using fake-based regression tests
and small HUMAN-RUN probes. Do not advance to demo recording or rehearsal while
known backend blockers remain. Do not claim that all possible bugs are gone.

Your follow-up assignment owns non-frozen Python backend implementation files
under agent/gaze_agent, relevant agent/tests runtime/brain/cost tests, prompts/*.md
(fixed placeholder contract), and scripts/fake_overlay.py, scripts/gaze_client.py,
scripts/rehearse.py plus their scripts/tests coverage when needed for backend
testing. Update the handoff/task documents as work progresses. Keep issue owner
labels A screen/actions, B LLM/planning/replay/policy, C runtime/loop, D harness.
Do not redesign the overlay or change protocol/**, contracts.py, protocol.py,
generated protocol types or other frozen shared interfaces. Do not change
dependency files unless a dependency is necessary and explicitly justified.
Keep LLM prompt text in prompts/*.md. Do not rekey old recordings and pretend
they were generated with a changed prompt.

Start with issues #6 (native focus/activation retest) and #5 (private controlled
demo persona and cache configuration). #7 (CLI local Cancel, select versus
choose and wait cleanup) is done. Read the current reports before changing code and
distinguish human observations, model narratives, fake evidence and hypotheses.
Never weaken confirmations, STOP, BUY no-op, recipient restrictions, or strict
replay to make a test pass.

NEVER run code on this Mac that activates apps, moves/clicks the mouse, types,
posts key events or captures screenshots. Use the existing desktop/API fakes
and guards. Do not run scripts/start.sh real, real rehearsal, gaze_agent.screen
without --fixture, or the human-only native launch probe yourself. Do not make
live OpenAI calls or inspect private .env/profile/clipboard/AX contents. If the
new workspace lacks a key, report that; do not read other worktrees or guess/copy
private configuration. No secrets or personal data in tracked files, public
issues, caches or handoff documents. No commits or pushes unless I explicitly
ask later. Do not spawn additional agents unless I ask.

Prepare beginner-friendly human testing instructions from the actual code.
Give ONLY Stage 1 initially and wait for my results before Stage 2. Each stage
must explain prerequisites, exact commands and terminal, what happens, PASS,
stop/cleanup and the safe results to send back. Use small steps and clearly
distinguish shell commands from REPL commands and select N from choose N.

Stages, in order:
1. Tools, sanitized local environment settings and Mac permission checks.
2. Back up the existing profile and agree an isolated test/demo profile.
   DEMO_MODE=1 does not replace an existing profile.
3. Harmless Messages AX and local OCR.
4. TextEdit new document / hello world, clipboard preservation and STOP.
5. Music, message/email confirmations using Cancel, then tickets up to BUY
   without purchasing. Actual sends may only target accounts I control.
6. Only after the earlier stages and blockers pass, guide recording complete
   paths and final real-app replay rehearsal.

For the future demo I plan to create a separate macOS user named GazeDemo.
Do not create/configure it or switch accounts yourself. Separate-account setup
does not resolve the exact-fixture/private-recipient guard issue. Recheck tools,
key/model configuration, permissions and app accounts in whichever account is
actually used. Do not assume the demo persona or recipients have been agreed.

Explain that scripts/rehearse.py defaults to REAL and automatically confirms
Send in D1/D2; --target real does too. fake_overlay.py demo also automatically
confirms Send when connected to a real agent. These are not Cancel-only tests.
The REPL requires manual confirmation. --target fake and demo --spawn use fakes.
DEMO_MODE=1 does not make all desktop actions a dry run. Strict REPLAY=replay
makes zero OpenAI calls and fails on a miss, but still performs real app actions;
websites, mail, Messages and streaming may still require network access. Zero
OpenAI calls is not the same as a completely offline demo.

Run the combined backend/harness suite with Python 3.12, mock protocol demo,
fake rehearsal, secret scan and appropriate checks after fixes. Use free ports
and existing fixtures/fakes. Report exactly what passed, failed or was not run,
including any live/native checks only I performed. Report bugs to their owning
lane with sanitized reproductions; never attach raw AX logs, screenshots,
credentials, private paths or my full terminal transcript without my explicit
permission. Fix the current issue before asking me to retry a costly live loop.
```
