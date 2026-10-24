"""Intent -> plans (§8.5) and T9 sentence decode (§6.3). Owned by Task C.

PHASE 0 STUB: deterministic fake output with the real shapes, no LLM.
"""
from __future__ import annotations

from typing import Any

from gaze_agent.contracts import Snapshot
from gaze_agent.protocol import Plan

OTHER = Plan(id="other", label="Something else", kind="other", risky=False)


async def make_plans(text: str, profile: dict[str, Any], snapshot: Snapshot | None) -> list[Plan]:
    label = f"(stub) {text}"
    if len(label) > 40:
        label = label[:39] + "…"
    return [Plan(id="p1", label=label, kind="task", risky=False),
            Plan(id="p2", label="(stub) Search the web", kind="task", risky=False),
            OTHER]


async def decode(words: list[str], raw_keys: list[list[str]], context: str | None,
                 profile: dict[str, Any]) -> list[str]:
    guesses = ["".join(group[0].lower() for group in keys) for keys in raw_keys]
    return [" ".join(words + guesses).strip() or "…"]
