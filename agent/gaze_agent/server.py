"""WebSocket server: auth, routing, task lifecycle (spec §4, §4.4). Owned by Task B.

PHASE 0 STUB. Until Task B lands, use the mock agent: `uv run scripts/fake_agent.py` (repo root).
"""
from __future__ import annotations

import sys


def main() -> int:
    print("gaze_agent.server is a Phase 0 stub (Task B implements it). "
          "Use scripts/fake_agent.py meanwhile.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
