"""Window-only screenshot + look_at_screen (spec §8.1.3). Owned by Task B.

PHASE 0 STUB: raises; never takes a screenshot.
"""
from __future__ import annotations

from gaze_agent.contracts import LookResult


async def look_at_screen(question: str) -> LookResult:
    raise NotImplementedError("screen.shot.look_at_screen is a Phase 0 stub (Task B implements it)")
