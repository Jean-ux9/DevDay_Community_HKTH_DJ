"""Pure confirmation policy for proposed actions (spec §9.1–9.3).

Execution, demo no-ops, recipient allowlists and post-confirm task checks belong
to B's loop. This module never touches the desktop or reads the environment.
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

from gaze_agent.contracts import GateDecision, ProposedAction, Snapshot
from gaze_agent.tools.contracts import PreparedAction

_RULES = (
    ("buy", r"buy|purchase|pay|checkout|place\s+order|order\s+now|book|reserve|confirm\s+order"),
    ("send", r"send|reply\s+all"),
    ("delete", r"delete|remove|trash|erase"),
    ("post", r"post|publish|tweet"),
    ("submit", r"submit"),
    ("other", r"transfer|unsubscribe"),
)
_FIELD_ROLES = {"axtextfield", "axtextarea", "axcombobox", "textbox", "text", "input"}
_KEY_ALIASES = {"command": "cmd", "meta": "cmd", "⌘": "cmd", "return": "enter",
                "⌫": "backspace", "⇧": "shift", "option": "alt", "control": "ctrl"}
_AMOUNT = re.compile(r"(?:[$€£¥]\s*\d[\d,.]*|\d[\d,.]*\s*(?:USD|EUR|GBP|CAD|AUD))", re.I)


def classify(text: str) -> str | None:
    """Classify a visible action label; also used for the planner's UI risk hint."""
    for kind, pattern in _RULES:
        if re.search(r"\b(?:" + pattern + r")\b", text, re.I):
            return kind
    return None


def _checkout(url: str | None) -> bool:
    if not url:
        return False
    try:
        path = unquote(urlsplit(url).path).lower()
    except ValueError:
        return False
    return bool(re.search(r"/(?:checkout|payment|cart/buy)(?:/|$)", path))


def _enter_kind(snapshot: Snapshot) -> str | None:
    focused = snapshot.focused
    if focused is None or focused.role.lower() not in _FIELD_ROLES:
        return None
    field = f"{focused.label} {focused.description}".lower()
    if re.search(r"\b(search|find|filter)\b", field):
        return None
    if re.search(r"checkout|payment|\border\b", snapshot.window_title, re.I) or _checkout(snapshot.url):
        return "buy"
    app = f"{snapshot.app} {snapshot.bundle_id}".lower()
    if any(name in app for name in ("messages", "mobilesms", "mail")):
        return "send"
    if re.search(r"\b(chat|message|compose|reply)\b", field):
        return "send"
    return None


def gate(action: ProposedAction, snapshot: Snapshot) -> GateDecision:
    element = action.element
    target = f"{element.label} {element.description}" if element else ""
    kind = None
    eligible = action.tool in {"click_element", "press_keys", "open_url"} or action.submit
    if eligible:
        kind = classify(target)
        if _checkout(action.url) or (action.tool != "open_url" and _checkout(snapshot.url)):
            kind = kind or "buy"
        if action.tool == "press_keys":
            keys = {_KEY_ALIASES.get(k.lower(), k.lower()) for k in action.keys or []}
            if "cmd" in keys and keys & {"delete", "backspace"}:
                kind = "delete"
            elif "cmd" in keys and ("enter" in keys or {"shift", "d"} <= keys):
                kind = "send"
            elif keys == {"enter"}:
                kind = kind or _enter_kind(snapshot)
        if action.tool == "type_text" and action.submit:
            kind = kind or _enter_kind(snapshot) or "submit"
    rule = kind is not None
    if not rule and not action.model_flag:
        return GateDecision(False, "other", "", [], "rule")

    kind = kind or "other"
    source = "both" if rule and action.model_flag else "rule" if rule else "model"
    verbs = {"send": "Send", "buy": "Buy", "delete": "Delete", "post": "Post",
             "submit": "Submit", "other": "Confirm action"}
    title = f"{verbs[kind]} in {snapshot.app}?"
    details = [f"App: {snapshot.app}", f"Window: {snapshot.window_title}"]
    if element:
        details.append(f"Target: {element.label}")
        if element.description:
            details.append(f"Description: {element.description}")
    if action.keys:
        details.append(f"Keys: {'+'.join(action.keys)}")
    if action.text is not None:
        details.append(f"Exact text: {action.text}")
    if action.url or snapshot.url:
        details.append(f"URL: {action.url or snapshot.url}")
    if kind == "send":
        # Element has no value/recipient field: quote only observed context.
        details.append(f"Recipient/compose context: {snapshot.window_title}")
        if action.text is None and snapshot.focused:
            details.append(f"Focused field: {snapshot.focused.label} {snapshot.focused.description}".rstrip())
    for visible in snapshot.elements:
        value = f"{visible.label} {visible.description}".strip()
        if _AMOUNT.search(value):
            line = f"Visible amount: {value}"
            if line not in details:
                details.append(line)
    if action.model_reason:
        details.append(f"Reason: {action.model_reason}")
    return GateDecision(True, kind, title, details, source)


def structured_gate(action: PreparedAction) -> GateDecision:
    """Build confirmation only from the immutable provider payload, without AX."""
    payload = action.payload
    if action.operation in {"mail.send", "messages.send"}:
        account = payload["sender"] if action.provider == "apple_mail" else payload["account"]
        details = [f"Recipient: {payload['recipient']}", f"Provider: {action.provider}",
                   f"Account: {account}"]
        if action.operation == "mail.send":
            details.append(f"Subject: {payload['subject']}")
        details.append(f"Exact content: {payload['body']}")
        return GateDecision(True, "send", "Send this message?", details, "rule")
    if action.operation == "web.open" and _checkout(payload.get("url")):
        return GateDecision(True, "buy", "Open checkout page?", [f"URL: {payload['url']}"], "rule")
    return GateDecision(False, "other", "", [], "rule")
