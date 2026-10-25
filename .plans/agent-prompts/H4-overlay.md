Task H4, suitable for the second laptop without credentials: make the existing
overlay clearly present structured action confirmations, progress and results.

Own ONLY overlay/src/renderer/App.tsx, screens/ConfirmScreen.tsx,
screens/ConfirmScreen.test.ts, associated new action-flow tests under
overlay/src/renderer/, and .plans/agent-reports/H4.md. Do not modify WS/main/gaze/
platform code, schemas, generated protocol, dependencies or general styling.

Read the CURRENT .plans/tasks.md plan. Use existing confirm_request.details and
task_status/task_result/error messages. Recipient and outgoing content must be
readable before confirmation; Cancel and STOP remain gaze-accessible. Handle
long content accessibly using current layout. Show failure/uncertain result
honestly, without a success animation that implies delivery. No canned live
responses, permission assumptions or new protocol fields. Preserve T9, dwell,
camera calibration and all existing interaction behavior. Avoid a redesign.

Start immediately with protocol fakes; no backend dependency for component tests.
Use pnpm --dir overlay test <owned test paths>, pnpm --dir overlay typecheck,
and relevant existing UI regression tests. No Electron/browser UI, webcam,
screenshots, desktop actions or live APIs. Missing local dependencies may be
synced through the normal lockfile without changing it; report missing tooling.
Report any required cross-owner change instead of editing that file. Include
tests proving Cancel sends false, confirmations preserve exact displayed text,
STOP availability and honest unknown/failure states. Human visual/gaze checks
remain NOT RUN.
