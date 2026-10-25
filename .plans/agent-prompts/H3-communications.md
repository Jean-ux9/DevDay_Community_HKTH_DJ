Task H3: structured Mail and Messages providers that reuse existing automation,
without reading Mail AX fields or clicking Send. Scope and interfaces are in the
CURRENT .plans/tasks.md section.

Own ONLY new agent/gaze_agent/tools/mail.py, tools/messages.py, tools/scripts/**;
new agent/tests/tools/test_mail.py, test_messages.py; .plans/agent-reports/H3.md.
H1 owns initializers, dependencies, model schemas, registry and confirmation.

First provider: Apple Mail's supported scripting surface. Second: evaluate the
standard imsg send CLI, without private/injected modes. References:
https://support.apple.com/guide/mail/automate-mail-tasks-mlhlp1120/mac
https://github.com/openclaw/imsg
Verify capabilities using source/docs only. Never run osascript, imsg, app checks,
account discovery or real provider calls as this agent. Do not install tools,
disable SIP, read history/databases or set up OAuth/accounts/permissions.

Implement transport-injected prepare/execute. prepare freezes exact recipient,
subject/body/provider (no app draft/send side effect); H1 displays the proposal
and calls execute only after approval. Provider receives the already resolved
single destination, never reads a profile or resolves arbitrary aliases. One To,
no Cc/Bcc/groups/attachments. No scan of existing drafts or inbox. Bind Mail send
to the exact newly created draft; do not send whichever window is frontmost.
Prevent script/argument injection: static scripts, data passed separately, no
shell interpolation. Preserve content exactly. Respect cancellation, bound and
reap subprocesses. Timeouts after dispatch are unknown unless non-submission can
be established; no automatic retries or fallback sends. A provider acknowledgement
does not prove receipt/delivery. Never leak handles/bodies/stdout/stderr in results.

If safe Mail scripting cannot be completed from documented/source evidence, report
the blocker and smallest alternative, without broad OAuth/MCP implementation.
Messages can remain unavailable with an honest capability error if imsg is missing.
Use H1 contracts; local doubles until its early handoff. Request dependency edits
from H1. No change to native recipient guards.

Acceptance with fake process/HTTP only: prepare zero-send; exact bytes/content and
single recipient; injection rejection; correct draft identity; missing tool/account,
permission denial and failure sanitization; timeout/unknown/cancel cleanup. Report
per-device human setup requirements and limitations. Run owned tests, secret/diff
checks. No actual send is authorized for coding agents.
