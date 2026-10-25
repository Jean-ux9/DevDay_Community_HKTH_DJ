# Backend stabilization handoff

Read `AGENTS.md`, the current-priority section at the top of `.plans/tasks.md`,
and the build spec before changing code. This handoff is for a **new workspace**;
never inspect or edit the previous workspace or other worktrees.

## Delivery contents

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
2. **D CLI harness, issue #7:** fix local `recovery:cancel` / `other` handling,
   actionable `select N` versus `choose N` prompts, and stale wait-state cleanup.
   Do not make the server execute local Cancel or change the frozen protocol.
3. **B / C, issue #5:** current demo send, recording and real rehearsal guards
   require the exact tracked fake fixture. A private controlled-recipient profile
   cannot simply replace its handles. Agree an explicit private persona/allowlist
   and private recording/cache path before actual sends/recording. Never put real
   handles in tracked fixtures/caches or disable demo safeguards to bypass this.
4. **A docs, issue #4:** the stale reasoning/configuration/ownership instructions
   were corrected in `screen/HUMAN_CHECKS.md`; verify the delivered guide before
   closing the report.

Issues: https://github.com/Jean-ux9/DevDay_Community_HKTH_DJ/issues/4,
https://github.com/Jean-ux9/DevDay_Community_HKTH_DJ/issues/5,
https://github.com/Jean-ux9/DevDay_Community_HKTH_DJ/issues/6,
https://github.com/Jean-ux9/DevDay_Community_HKTH_DJ/issues/7.

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

Start with issues #6 (native focus/activation retest), #7 (CLI local Cancel,
select versus choose and wait cleanup), and #5 (private controlled demo persona
and cache configuration). Read the current reports before changing code and
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
