"""Frozen interfaces between Task B (runtime, screen, actions) and Task C (LLM, planner, Auto, safety).

This file is the only shared Python surface between the two tasks (.plans/tasks.md, Phase 0 §4).
Changing it needs a PR that updates both sides.

Functions each side implements (Phase 0 ships stubs with these exact signatures):

  Owned by B
    screen/__init__.py  get_screen() -> Snapshot                        AX, falls back to OCR (§8.1)
    screen/ax.py        window_info() -> WindowInfo                     cheap, AX only, no LLM
    screen/shot.py      async look_at_screen(question) -> LookResult    window-only capture + complete("vision")
    profile.py          load_profile() -> dict; profile_summary(profile, include_address=False) -> str

  Owned by C
    llm.py      render(prompt, vars) -> str                             KeyError on missing/extra placeholder
                async complete(prompt, model, vars, *, tools=None, input_items=None, image_jpeg=None)
                    -> LLMResponse                                      cancel = cancel the asyncio task;
                                                                        failures raise LLMError
    planner.py  async make_plans(text, profile, snapshot) -> list[Plan] 2-4 plans + "other" last
                async decode(words, raw_keys, context, profile) -> list[str]   1-3 sentences
    auto.py     class AutoWatcher(emit_suggestions, window_info, get_screen, get_profile)
                    set_mode(mode); set_task_running(running); on_gaze_context(dock_idle, idle_ms);
                    refresh(); async run()
    safety.py   gate(action: ProposedAction, snapshot: Snapshot) -> GateDecision   pure, deterministic

Lifecycle duties of B toward C:
  - call AutoWatcher.set_task_running(True) before the first task_status{running}, and
    set_task_running(False) on EVERY terminal path (done, failed, stopped, disconnect, exception);
  - call set_mode on mode_set and on reconnect (default "auto");
  - B assigns list_id to plans/suggestions; C returns only the items.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from gaze_agent.protocol import Plan

ModelSlot = Literal["agent", "fast", "vision"]

# Placeholders each prompt receives, exactly as its caller passes them (Phase 0 §5).
# Static text (rules, tool usage) lives in the prompt body; images go through image_jpeg.
PROMPT_VARS: dict[str, frozenset[str]] = {
    "task_system": frozenset({"profile_summary", "plan_label", "plan_detail", "screen"}),
    "plan_intent": frozenset({"profile_summary", "intent", "app_context"}),
    "auto_suggest": frozenset({"profile_summary", "app", "window_title", "screen"}),
    "sentence_decode": frozenset({"profile_style", "words", "raw_keys", "context"}),
    "look_at_screen": frozenset({"question"}),
}


# ---- screen (B) -------------------------------------------------------------------------------

@dataclass(frozen=True)
class Element:
    id: str                              # "e12" (AX) or "o7" (OCR); valid only within its snapshot
    role: str                            # "AXButton", or "text" for OCR
    label: str
    description: str
    enabled: bool
    bbox: tuple[int, int, int, int]      # x, y, w, h in screen coords (OCR already offset by window origin)
    source: Literal["ax", "ocr"]

    def to_line(self) -> str:
        x, y, w, h = self.bbox
        state = "enabled" if self.enabled else "disabled"
        return f'{self.id} | {self.role} | "{self.label}" | {state} | ({x},{y},{w},{h})'


@dataclass(frozen=True)
class Snapshot:
    snapshot_id: str
    app: str
    bundle_id: str
    window_title: str
    url: str | None
    focused: Element | None              # the focused element itself (safety needs it)
    elements: list[Element] = field(default_factory=list)   # max 150

    def to_prompt(self) -> str:
        lines = [f"snapshot {self.snapshot_id} | app {self.app} | window \"{self.window_title}\""]
        if self.url:
            lines.append(f"url {self.url}")
        lines.append(f"focused: {self.focused.to_line() if self.focused else 'none'}")
        lines.extend(e.to_line() for e in self.elements)
        return "\n".join(lines)


@dataclass(frozen=True)
class WindowInfo:
    bundle_id: str
    app: str
    window_title: str
    window_key: str                      # bundle_id + "|" + window_title
    element_sigs: list[str]              # role+label of visible elements, max 200 (for content_hash)


@dataclass(frozen=True)
class LookResult:
    answer: str
    point: tuple[int, int] | None = None


# ---- LLM (C) ----------------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCall]
    response_id: str | None
    cached: bool                         # served from the replay cache


class LLMError(Exception):
    """The OpenAI call failed (network, API error, replay miss while offline). B maps it to llm_failed."""


# ---- safety (C) -------------------------------------------------------------------------------

@dataclass(frozen=True)
class ProposedAction:
    tool: Literal["click_element", "press_keys", "type_text", "open_url"]
    element: Element | None = None
    keys: list[str] | None = None
    text: str | None = None
    submit: bool = False
    url: str | None = None
    model_flag: bool = False             # the model set requires_confirmation
    model_reason: str | None = None


@dataclass(frozen=True)
class GateDecision:
    required: bool
    action: Literal["send", "buy", "delete", "submit", "post", "other"]
    title: str
    details: list[str]
    source: Literal["rule", "model", "both"]


# ---- Auto (C) ---------------------------------------------------------------------------------

# emit_suggestions(window_key, app, items, cached); B adds list_id and sends `suggestions`
EmitSuggestions = Callable[[str, str, list[Plan], bool], Awaitable[None]]
