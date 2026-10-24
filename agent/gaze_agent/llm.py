"""OpenAI Responses API wrapper + record/replay cache (spec §8.6). Owned by Task C.

PHASE 0 STUB: `render` works (prompts must be loadable from day one); `complete` raises.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from gaze_agent.contracts import LLMError, LLMResponse, ModelSlot

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
_FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.S)
_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def placeholders(prompt: str) -> set[str]:
    """The {{placeholders}} used in a prompt body."""
    return set(_PLACEHOLDER.findall(_body(prompt)))


def render(prompt: str, vars: dict[str, Any]) -> str:
    """Fill a prompt's {{placeholders}}. Raises KeyError on a missing or extra variable."""
    body = _body(prompt)
    needed = set(_PLACEHOLDER.findall(body))
    missing, extra = needed - vars.keys(), vars.keys() - needed
    if missing or extra:
        raise KeyError(f"prompt {prompt!r}: missing {sorted(missing)}, extra {sorted(extra)}")
    return _PLACEHOLDER.sub(lambda m: str(vars[m.group(1)]), body)


def _body(prompt: str) -> str:
    return _FRONT_MATTER.sub("", (PROMPTS_DIR / f"{prompt}.md").read_text(), count=1)


async def complete(prompt: str, model: ModelSlot, vars: dict[str, Any], *,
                   tools: list[dict[str, Any]] | None = None,
                   input_items: list[dict[str, Any]] | None = None,
                   image_jpeg: bytes | None = None) -> LLMResponse:
    raise LLMError("llm.complete is a Phase 0 stub (Task C implements it)")
