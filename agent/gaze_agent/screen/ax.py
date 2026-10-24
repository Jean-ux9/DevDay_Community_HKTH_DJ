"""AX tree snapshot and cheap window info (spec §8.1, §7). Owned by Task B.

PHASE 0 STUB: raises; never touches the desktop.
"""
from __future__ import annotations

from gaze_agent.contracts import WindowInfo


def window_info() -> WindowInfo:
    raise NotImplementedError("screen.ax.window_info is a Phase 0 stub (Task B implements it)")
