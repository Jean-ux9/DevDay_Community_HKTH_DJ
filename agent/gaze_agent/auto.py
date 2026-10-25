"""Debounced AX-only Auto watcher with bounded suggestion LRU (spec §7)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from collections import Counter, OrderedDict
from collections.abc import Callable
from functools import partial
from typing import Any, Literal

from gaze_agent import llm
from gaze_agent.contracts import EmitSuggestions, Snapshot, WindowInfo
from gaze_agent.planner import parse_plans
from gaze_agent.profile import profile_summary
from gaze_agent.protocol import Plan
from gaze_agent.screen import get_screen as read_screen

AUTO_COOLDOWN_S = 20.0
REFRESH_COOLDOWN_S = 3.0


def normalize_window_key(window_key: str) -> str:
    """Keep the app identity; ignore title case, digits and numeric counters."""
    bundle, separator, title = window_key.partition("|")
    if not separator:
        bundle, title = "", bundle
    title = re.sub(r"\(\s*\d+\s*\)", "", title.lower())
    title = " ".join(re.sub(r"\d+", "", title).split())
    return bundle + separator + title


def _fingerprint(info: WindowInfo) -> tuple[str, str]:
    encoded = json.dumps(sorted(info.element_sigs[:200]), ensure_ascii=False)
    return normalize_window_key(info.window_key), hashlib.sha256(encoded.encode()).hexdigest()


def _change(old: list[str], new: list[str]) -> float:
    a, b = Counter(old[:200]), Counter(new[:200])
    total = max(sum(a.values()), sum(b.values()))
    return (total - sum((a & b).values())) / total if total else 0.0


def _new_label_chars(old: list[str], new: list[str]) -> int:
    added = Counter(new[:200]) - Counter(old[:200])
    return sum(len(sig.partition("|")[2] if "|" in sig else sig) * count
               for sig, count in added.items())


class AutoWatcher:
    def __init__(self, emit_suggestions: EmitSuggestions, window_info: Callable[[], WindowInfo],
                 get_screen: Callable[[], Snapshot], get_profile: Callable[[], dict[str, Any]], *,
                 clock=None, ambient: bool | None = None, cooldown_s: float | None = None):
        self.emit_suggestions = emit_suggestions
        self.window_info = window_info
        # Preserve zero-argument injected desktop fakes and the frozen interface.
        self.get_screen = partial(get_screen, auto=True) if get_screen is read_screen else get_screen
        self.get_profile = get_profile
        self.clock = clock or time.monotonic
        self.ambient = os.getenv("GAZE_AUTO_AMBIENT", "0") == "1" if ambient is None else ambient
        self.cooldown_s = max(0.0, float(os.getenv("AUTO_COOLDOWN_S", AUTO_COOLDOWN_S))
                              if cooldown_s is None else cooldown_s)
        self.mode: Literal["auto", "type"] = "auto"
        self.task_running = False
        self._dock_idle = False
        self._refresh = False
        self._generation = 0
        self._candidate: tuple[str, str] | None = None
        self._stable_since = 0.0
        self._last_call = float("-inf")
        self._last_refresh = float("-inf")
        self._last_info: WindowInfo | None = None
        self._cache: OrderedDict[tuple[str, str], list[Plan]] = OrderedDict()
        self._profile_key: str | None = None
        self._emitted = False
        self.last_error: str | None = None
        # async (exception or None) -> None: an explicit refresh ended without suggestions.
        self.on_refresh_failed: Callable[[BaseException | None], Any] | None = None

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

    def refresh(self) -> bool:
        """Ask for suggestions now; False if ignored (one is pending, or the last ran < 3 s ago)."""
        if self._refresh or self.clock() - self._last_refresh < REFRESH_COOLDOWN_S:
            return False
        # Not a staleness signal (§4.4): a paid in-flight result for the same
        # window, content, mode and profile still answers this request.
        self._refresh = True
        return True

    def _allowed(self) -> bool:
        return self.mode == "auto" and not self.task_running

    async def _tick(self) -> None:
        info = self.window_info()
        now = self.clock()
        key = _fingerprint(info)
        if key != self._candidate:
            self._candidate, self._stable_since = key, now
        refresh = self._refresh
        if not self._allowed() or (not refresh and (not self.ambient or now - self._stable_since < 1.5)):
            return
        profile = self.get_profile()
        profile_key = json.dumps(profile, sort_keys=True, ensure_ascii=False)
        profile_changed = self._profile_key != profile_key
        if profile_changed:
            self._cache.clear()
            self._profile_key = profile_key
        window_changed = (self._last_info is None or info.app != self._last_info.app
                          or key[0] != normalize_window_key(self._last_info.window_key))
        content_changed = (self._last_info is not None
                           and _change(self._last_info.element_sigs, info.element_sigs) > 0.30
                           and _new_label_chars(self._last_info.element_sigs, info.element_sigs) >= 40)
        if not (window_changed or content_changed or refresh):
            return
        generation = self._generation
        cached = key in self._cache and not refresh
        if cached:
            items = self._cache[key]
        else:
            if not refresh and now - self._last_call < self.cooldown_s:
                return
            # Reserve the attempt before anything that can fail, including capture.
            self._last_call = now
            if refresh:
                self._last_refresh = now
            self._refresh = False
            snapshot = self.get_screen()
            if normalize_window_key(snapshot.bundle_id + "|" + snapshot.window_title) != key[0]:
                self._candidate = None
                return
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
        self._emitted = True
        await self.emit_suggestions(key[0], info.app,
                                    [p.model_copy(deep=True) for p in items], cached)
        self.last_error = None

    async def run(self) -> None:
        while True:
            started = self.clock()
            refresh, failure, self._emitted = self._refresh, None, False
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Permission loss/transient AX or API failures must not kill Auto.
                self.last_error = type(exc).__name__
                failure = exc
            # A refresh this tick consumed but did not answer (failure, changed window, stale result).
            if refresh and not self._refresh and not self._emitted and self.on_refresh_failed:
                try:
                    await self.on_refresh_failed(failure)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    pass
            await asyncio.sleep(max(0, 1 - (self.clock() - started)))
