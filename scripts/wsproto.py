"""Envelope + validation helpers for protocol/messages.schema.json (spec §4).

Shared by the mock agent and the mock overlay. Needs `jsonschema`.
"""
from __future__ import annotations

import json
import time
import uuid
from functools import cache
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "protocol" / "messages.schema.json"
SCHEMA: dict[str, Any] = json.loads(SCHEMA_PATH.read_text())
PROTOCOL_VERSION: int = SCHEMA["x-protocol-version"]
DIRECTIONS: dict[str, str] = SCHEMA["x-messages"]

Direction = Literal["o2a", "a2o"]


class ProtocolError(Exception):
    """An incoming message that must be answered with error{code}."""

    def __init__(self, code: str, message: str, msg_id: str | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.msg_id = msg_id  # id of the offending message, if it had a usable one


@cache
def _validator(def_name: str) -> Draft202012Validator:
    return Draft202012Validator({"$defs": SCHEMA["$defs"], "$ref": f"#/$defs/{def_name}"})


def def_errors(def_name: str, value: Any) -> list[str]:
    """Validate a value against any $defs entry (e.g. "Settings"); returns readable errors."""
    errs = sorted(_validator(def_name).iter_errors(value), key=lambda e: list(e.path))
    return [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errs]


def message_errors(msg: Any, direction: Direction | None = None) -> list[str]:
    errors = def_errors("Envelope", msg)
    if errors:
        return errors
    mtype = msg["type"]
    if mtype not in DIRECTIONS:
        return [f"unknown message type {mtype!r}"]
    if direction and DIRECTIONS[mtype] != direction:
        return [f"{mtype!r} is {DIRECTIONS[mtype]}, not allowed as {direction}"]
    return [f"payload/{e}" for e in def_errors(f"payload_{mtype}", msg["payload"])]


def new_id() -> str:
    return str(uuid.uuid4())


def make(mtype: str, payload: dict[str, Any], re: str | None = None) -> dict[str, Any]:
    """Build an outgoing envelope. Raises ValueError if it would not validate."""
    msg = {"v": PROTOCOL_VERSION, "type": mtype, "id": new_id(), "re": re,
           "ts": int(time.time() * 1000), "payload": payload}
    errors = message_errors(msg)
    if errors:
        raise ValueError(f"refusing to send invalid {mtype}: {errors}")
    return msg


def parse(raw: str | bytes, direction: Direction) -> dict[str, Any]:
    """Decode and validate an incoming frame. Raises ProtocolError."""
    try:
        msg = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as e:
        raise ProtocolError("bad_message", f"not JSON: {e}") from None
    msg_id = None
    if isinstance(msg, dict) and not def_errors("Uuid", msg.get("id")):
        msg_id = msg["id"]
    if isinstance(msg, dict) and "v" in msg and msg["v"] != PROTOCOL_VERSION:
        raise ProtocolError("version_mismatch",
                            f"protocol v{msg['v']} not supported (expected v{PROTOCOL_VERSION})", msg_id)
    errors = message_errors(msg, direction)
    if errors:
        raise ProtocolError("bad_message", "; ".join(errors[:3]), msg_id)
    return msg


def merge_patch(target: Any, patch: Any) -> Any:
    """RFC 7386 JSON merge-patch."""
    if not isinstance(patch, dict):
        return patch
    result = dict(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = merge_patch(result.get(key), value)
    return result


def brief(msg: dict[str, Any]) -> str:
    """One-line rendering for logs."""
    payload = json.dumps(msg["payload"], ensure_ascii=False)
    if len(payload) > 160:
        payload = payload[:157] + "..."
    re = f" re={msg['re'][:8]}" if msg.get("re") else ""
    return f"{msg['type']} id={msg['id'][:8]}{re} {payload}"
