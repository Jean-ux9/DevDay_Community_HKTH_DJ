"""Auto mode: frontmost-window watcher + suggestion cache (spec §7). Owned by Task C.

PHASE 0 STUB: accepts every call, never emits suggestions.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, Literal

from gaze_agent.contracts import EmitSuggestions, Snapshot, WindowInfo


class AutoWatcher:
    def __init__(self, emit_suggestions: EmitSuggestions, window_info: Callable[[], WindowInfo],
                 get_screen: Callable[[], Snapshot], get_profile: Callable[[], dict[str, Any]]):
        self.emit_suggestions = emit_suggestions
        self.window_info = window_info
        self.get_screen = get_screen
        self.get_profile = get_profile
        self.mode: Literal["auto", "type"] = "auto"
        self.task_running = False

    def set_mode(self, mode: Literal["auto", "type"]) -> None:
        self.mode = mode

    def set_task_running(self, running: bool) -> None:
        self.task_running = running

    def on_gaze_context(self, dock_idle: bool, idle_ms: float) -> None:
        pass

    def refresh(self) -> None:
        pass

    async def run(self) -> None:
        await asyncio.Event().wait()  # the real watcher polls window_info() at 1 Hz
