Task H5, suitable for the second laptop: create focused fake integration coverage
and a short human demo runbook for the reusable action provider pivot.

Own ONLY new agent/tests/runtime/test_connector_demo.py,
.plans/hackathon-demo-runbook.md and .plans/agent-reports/H5.md.
Do not edit shared test guards, provider/runtime code, tasks.md or old rehearsal.

Start with a scenario matrix and runbook using the CURRENT .plans/tasks.md
interface; implement integration tests when H1/H2/H3 land. Use the real runtime
with injected fake providers/model and temporary selected configuration. Keep
native/HTTP/process guards active; no default/private profile, .env or history
reads. Test approved app/link routing, Send Cancel zero-dispatch, unapproved
destination zero-dispatch, confirmed exact payload, post-confirm mutation, STOP/
disconnect, duplicate request and unknown-send no-retry. No tautological tests
that only verify fake helpers. Report external owner bugs; don't repair them.

Runbook: per-laptop dependencies and capability checks; demo-machine permissions
and human-selected provider/account; app/link first, then Cancel, then separately
approved single controlled send, then gaze integration. Each human step must say
shell vs REPL, terminal/workspace, expected result, stop/cleanup and sanitized
feedback. Give one small block at a time during actual coordination. No private
handles or hardcoded personal paths in tracked docs. Do not unlock recording,
auto-confirming real rehearsal or more billed API probes by writing the runbook.

After integration, run owned tests and the safe combined backend/harness suite
once, mock demo and fake rehearsal with --target fake; secret/diff checks. Record
exact combined revision and actual results. Never label fake success as native
Mail/Messages/gaze success. If dependencies are missing, leave integration NOT RUN
and provide an exact handoff rather than inventing passing evidence.
