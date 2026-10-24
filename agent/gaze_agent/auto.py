"""Debounced AX-only Auto watcher with bounded suggestion LRU (spec §7)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import Counter, OrderedDict
from collections.abc import Callable
from typing import Any, Literal

from gaze_agent import llm
from gaze_agent.contracts import EmitSuggestions, Snapshot, WindowInfo
from gaze_agent.planner import parse_plans
from gaze_agent.profile import profile_summary
from gaze_agent.protocol import Plan


def _fingerprint(info: WindowInfo) -> tuple[str, str]:
    encoded = json.dumps(sorted(info.element_sigs[:200]), ensure_ascii=False)
    return info.window_key, hashlib.sha256(encoded.encode()).hexdigest()


def _change(old: list[str], new: list[str]) -> float:
    a, b = Counter(old[:200]), Counter(new[:200])
    total = max(sum(a.values()), sum(b.values()))
    return (total - sum((a & b).values())) / total if total else 0.0


class AutoWatcher:
    def __init__(self, emit_suggestions: EmitSuggestions, window_info: Callable[[], WindowInfo],
                 get_screen: Callable[[], Snapshot], get_profile: Callable[[], dict[str, Any]]):
        self.emit_suggestions = emit_suggestions
        self.window_info = window_info
        self.get_screen = get_screen
        self.get_profile = get_profile
        self.mode: Literal["auto", "type"] = "auto"
        self.task_running = False
        self._dock_idle = False
        self._refresh = False
        self._generation = 0
        self._candidate: tuple[str, str] | None = None
        self._stable_since = 0.0
        self._last_call = float("-inf")
        self._last_info: WindowInfo | None = None
        self._cache: OrderedDict[tuple[str, str], list[Plan]] = OrderedDict()
        self._profile_key: str | None = None
        self.last_error: str | None = None

    def set_mode(self, mode: Literal["auto", "type"]) -> None:
        if mode not in {"auto", "type"}:
            raise ValueError("Unknown mode")
        if mode != self.mode:
            self._generation += 1
            self._candidate = None
        self.mode = mode

    def set_task_running(self, running: bool) -> None:
        if running != self.task_running:
            self._generation += 1
            self._candidate = None
        self.task_running = running

    def on_gaze_context(self, dock_idle: bool, idle_ms: float) -> None:
        self._dock_idle = dock_idle and idle_ms >= 1500

    def refresh(self) -> None:
        self._refresh = True
        self._generation += 1

    def _allowed(self) -> bool:
        return self.mode == "auto" and not self.task_running

    async def _tick(self) -> None:
        info = self.window_info()
        now = time.monotonic()
        key = _fingerprint(info)
        if key != self._candidate:
            self._candidate, self._stable_since = key, now
        if not self._allowed() or now - self._stable_since < 1.5:
            return
        profile = self.get_profile()
        profile_key = json.dumps(profile, sort_keys=True, ensure_ascii=False)
        profile_changed = self._profile_key != profile_key
        if profile_changed:
            self._cache.clear()
            self._profile_key = profile_key
        window_changed = self._last_info is None or info.window_key != self._last_info.window_key
        content_changed = self._last_info is not None and _change(self._last_info.element_sigs, info.element_sigs) > 0.30
        refresh = self._refresh
        if not (window_changed or content_changed or refresh or profile_changed):
            return
        if not (window_changed or self._dock_idle or refresh):
            return
        generation = self._generation
        cached = key in self._cache and not refresh
        if cached:
            items = self._cache[key]
        else:
            if not refresh and now - self._last_call < 10:
                return
            snapshot = self.get_screen()
            if (snapshot.bundle_id, snapshot.window_title) != (info.bundle_id, info.window_title):
                self._candidate = None
                return
            self._last_call = now
            self._refresh = False
            response = await llm.complete("auto_suggest", "fast", {
                "profile_summary": profile_summary(profile), "app": info.app,
                "window_title": info.window_title, "screen": snapshot.to_prompt(),
            })
            items = parse_plans(response.text, minimum=3, maximum=4)
            cached = response.cached
        # STOP/task start or a mode round-trip invalidates an in-flight request.
        # Re-read cheap AX state after the await, including content, not just title.
        if (not self._allowed() or self._generation != generation
                or _fingerprint(self.window_info()) != key
                or json.dumps(self.get_profile(), sort_keys=True, ensure_ascii=False) != profile_key):
            return
        self._cache[key] = [p.model_copy(deep=True) for p in items]
        self._cache.move_to_end(key)
        while len(self._cache) > 20:
            self._cache.popitem(last=False)
        self._last_info = info
        self._refresh = False
        await self.emit_suggestions(info.window_key, info.app,
                                    [p.model_copy(deep=True) for p in items], cached)
        self.last_error = None

    async def run(self) -> None:
        while True:
            started = time.monotonic()
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Permission loss/transient AX or API failures must not kill Auto.
                self.last_error = type(exc).__name__
            await asyncio.sleep(max(0, 1 - (time.monotonic() - started)))
