# Hackathon agent launch prompts

Create one Superset workspace per lane from the published `origin/main`
checkpoint containing the CURRENT section of `.plans/tasks.md`. On another
laptop, sign in and fetch independently; do not copy private files. Do not run
these agents in the coordinator's dirty worktree.

Paste **COMMON.md followed by exactly one lane file** into each agent:

| Laptop | Lane prompt | Start / dependency |
|---|---|---|
| 1 | [H1-runtime.md](H1-runtime.md) | First: publish additive interface handoff; then runtime wiring |
| 1 | [H2-apps-links.md](H2-apps-links.md) | Now against documented interface; integrate H1 contracts |
| 1 | [H3-communications.md](H3-communications.md) | Now with injected fake transports; integrate H1 contracts |
| 2 | [H4-overlay.md](H4-overlay.md) | Now against existing protocol fakes |
| 2 | [H5-validation.md](H5-validation.md) | Runbook/scenarios now; combined validation after backend lanes |

If running only three agents, start H1/H2/H3; run H4/H5 as capacity opens. Do not
combine lanes in one dirty workspace. Coordinator owns `.plans/tasks.md`; workers
record findings in their reports. Humans publish worker branches when ready.
The coordinator integrates contracts first, provider modules next, runtime wiring
next; overlay independently; final H5 validation against the combined revision.

No remote host has been configured and no workers have been started by this
handoff. These are copyable prompts, not a claim that parallel execution ran.
