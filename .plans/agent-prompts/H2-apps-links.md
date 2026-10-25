Task H2: fast, reusable app and webpage opening behind the interface in the
CURRENT .plans/tasks.md section. Opening links/webpages is required for the demo.

Own ONLY new agent/gaze_agent/tools/launch.py,
agent/tests/tools/test_launch.py and .plans/agent-reports/H2.md.
H1 owns package initializers, registry, dependencies, runtime and contracts.

Implement app.open {name} using a small approved app map and web.open {url} using
the system launcher. No arbitrary executable, shell, file/custom/javascript URL,
credentials in URL, control characters or option injection. Use validated argument
vectors and injected process transport, bounded wait/terminate/reap on cancellation.
prepare is side-effect free; execute returns structured result. Import/construction
must not launch processes, inspect installed apps/permissions or read configuration.
H1 retains risk/confirmation policy for URLs; do not implement a policy bypass.

Use the documented additive contracts; local test doubles are allowed until H1's
interface handoff. Report mismatches to H1 instead of changing shared code.
Opening a page is distinct from browsing/reading/clicking within it. Do not add
Playwright, a browser UI or general computer control in this lane. Report launcher
acceptance honestly; do not claim the page rendered or the app is focused without
separate observation. Keep native DesktopActions untouched.

Acceptance: faked valid app/HTTP(S), malformed/injected/unsupported inputs rejected,
missing launcher/nonzero exit sanitized, timeout/cancel cleanup, no import/prepare
side effects. Run owned tests, secret and diff checks; no actual app/URL launch.
Write concise setup and later human app/link check in your report.
