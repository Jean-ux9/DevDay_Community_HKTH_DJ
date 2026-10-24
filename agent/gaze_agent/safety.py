"""Confirmation gate (spec §9.1-9.2). Owned by Task C.

PHASE 0 STUB: only the label/description "Send" and the model flag trigger a confirm.
"""
from __future__ import annotations

from gaze_agent.contracts import GateDecision, ProposedAction, Snapshot


def gate(action: ProposedAction, snapshot: Snapshot) -> GateDecision:
    el = action.element
    rule = el is not None and "send" in (el.label.lower(), el.description.lower())
    if not (rule or action.model_flag):
        return GateDecision(required=False, action="other", title="", details=[], source="rule")
    source = "both" if rule and action.model_flag else "rule" if rule else "model"
    title = f"{el.label} in {snapshot.app}?" if el else f"Confirm in {snapshot.app}?"
    details = [f"App: {snapshot.app}"] + ([f"Reason: {action.model_reason}"] if action.model_reason else [])
    return GateDecision(required=True, action="send" if rule else "other", title=title, details=details,
                        source=source)
