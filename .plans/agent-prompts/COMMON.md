You are implementing one bounded Gaze Copilot hackathon lane. Work quickly in
small increments. Read AGENTS.md, the CURRENT section of .plans/tasks.md (including
the interface agreement and exclusive ownership table), then relevant spec/source.
Historical consumer/Stage 1 wording is superseded by that CURRENT section.

Inspect git status and preserve changes. Stay in this assigned workspace/branch;
do not inspect other worktrees. Fetch origin/main and verify your base includes
the published hackathon checkpoint. Do not silently reset, switch branches or
overwrite work. Missing upstream contracts are a dependency, not permission to
edit another lane's files. Do not spawn additional agents.

Only edit files listed for your lane. Keep the WebSocket schema and existing
Python contracts frozen. No secrets, private configuration/profile/backup reads,
clipboard/AX inspection, live API calls, app activation, screenshots, keys, clicks,
typing, native rehearsal, installing external tools or permission changes. Use
Python 3.12 through uv and injected subprocess/HTTP/native fakes. Prompts belong
in prompts/*.md. No broad redesign, second LLM client or generic framework.

Do not commit/push/merge or mutate GitHub issues. The coordinator's publication
authorization is not worker authorization. Return a reviewable diff and exact
handoff. Run focused meaningful tests, not the entire suite after each edit.
If your change speaks WebSocket, also run the mock demo. Use these safe forms:

    env GAZE_DEMO_CONFIG=/gaze-test-nonexistent-private-config UV_NO_ENV_FILE=1 PYTHON_DOTENV_DISABLED=1 uv run --project agent --python 3.12 pytest <owned-test-paths> --tb=short -q
    env -u GAZE_DEMO_CONFIG UV_NO_ENV_FILE=1 PYTHON_DOTENV_DISABLED=1 uv run scripts/fake_overlay.py demo --spawn

Missing credentials do not block fake work. For dependency network failures, try
uv --offline once as described in AGENTS.md, then report the blocker. Never
weaken recipient/confirmation/STOP/replay/storage guards to get a passing demo.
Read subprocess output only from your fake transports in tests; never probe a
real account. No raw provider error/stdout/body/handle in logs or public reports.

End your final response with exactly one envelope:

SUPERSET_WORKER_DONE
task: Hx
summary: <one line>
files: <exact changed paths>
checks: <commands and actual outcomes; distinguish fake from native>
handoff: <base revision, interface/dependency notes and remaining human checks>

or:

SUPERSET_WORKER_BLOCKED
task: Hx
reason: <specific blocker>
needs: <exact owner decision or dependency>
