Task H1: integrate reusable structured action providers into the existing Python
task loop, retaining overlay/planner and frozen WebSocket envelopes.

Ownership: new tools/__init__.py, tools/contracts.py, tools/registry.py under
agent/gaze_agent/; existing loop.py, server.py, safety.py; prompts/task_system.md;
agent/pyproject.toml and agent/uv.lock; new agent/tests/runtime/test_tool_routing.py
and test_tool_confirmation.py. No other files. Coordinator records your report.

FIRST implement only the additive ActionRequest, PreparedAction, ActionResult and
provider interfaces exactly specified in .plans/tasks.md. Send the coordinator
an early interface-only handoff so H2/H3 can align before completing the lane.
Do not make provider implementation depend on a general MCP transport. Reuse a
direct CLI/API adapter first; MCP is optional when it removes a concrete blocker.

Then add explicit internal model tools for approved app/web opening and structured
mail/message sending. Registry composition belongs here; H2 owns launch provider,
H3 owns communications. Test against local doubles until modules land. Preserve
existing native tools and their context guards. Structured actions should not
fail solely because native Mail body/recipient AX is unsupported; avoid mandatory
native snapshots for explicit structured operations while retaining native guards
for element actions. Preserve existing constructor compatibility where possible.

Resolve recipient_alias from the already selected private configuration, never
model-supplied handles. One approved destination, frozen exact payload and selected
provider/account. Use existing confirm_request for Send, showing recipient/content;
model flags cannot bypass it. Revalidate approvals/payload after waiting, before
dispatch. Cancel/STOP/disconnect dispatch zero new actions; claims prevent duplicate
sends. A possibly submitted send returns unknown and is never auto-retried. Preserve
BUY no-op, cooldowns, logs redaction and task/time/retry limits. Missing provider
must be honest setup failure. No live calls, native tests or new private settings.

Acceptance: fake routing; Cancel/unapproved recipient zero-send; mutation revokes
confirmation; STOP/disconnect; repeated request/uncertain result no duplicate send;
honest acknowledgements; legacy native path unchanged. Run owned focused tests,
existing runtime/loop regressions appropriate to changed code, mock protocol demo,
secret and diff checks. Report prompt-cache impact; do not refresh recordings.
