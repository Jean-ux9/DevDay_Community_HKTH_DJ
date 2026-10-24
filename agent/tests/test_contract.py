"""protocol.py must agree with protocol/messages.schema.json (Phase 0 §3).

Every sample is checked against the JSON Schema AND the pydantic model, and must round-trip
unchanged. Invalid samples must be rejected by both.
"""
import json
import uuid
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from gaze_agent import protocol

SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "protocol" / "messages.schema.json").read_text())
T = str(uuid.UUID(int=1))
PLAN = {"id": "p1", "label": "Text Mom: I'll be late", "kind": "task", "risky": True}
OTHER = {"id": "other", "label": "Something else", "kind": "other", "risky": False}
RETRY = {"id": "recovery:retry", "label": "Try again", "kind": "recovery", "risky": False}
PROFILE = {"name": "Sam", "favorites": {"artist": "A", "playlist": "B", "sites": []}, "contacts": {"Mom": ["+1"]},
           "style": {"tone": "casual", "signature": "", "phrases": []},
           "address": {"full_name": "", "city": "", "email": ""}}
SETTINGS = {"dwellMs": 800, "blinkSelect": False, "density": "large", "gazeSource": "mouse", "calibrationMode": "gaze"}
PERMS = {"accessibility": True, "screen_recording": False, "camera": "unknown"}

VALID: dict[str, list[dict]] = {
    "hello": [{"client": "overlay", "version": "0.1.0"}],
    "mode_set": [{"mode": "type"}],
    "gaze_context": [{"dock_idle": True, "idle_ms": 1500}],
    "auto_refresh": [{}],
    "decode_request": [{"words": ["tell"], "raw_keys": [["GHI", "ABC"]]},
                       {"words": [], "raw_keys": [], "context": "Messages"}],
    "intent_submit": [{"text": "tell mom I'll be late"}],
    "plan_select": [{"list_id": "L1", "plan_id": "p1"}],
    "choice_response": [{"task_id": T, "choice_id": "a"}, {"task_id": T, "choice_id": None}],
    "confirm_response": [{"task_id": T, "confirmed": False}],
    "stop": [{"reason": "hotkey"}],
    "profile_get": [{}],
    "profile_update": [{"patch": {"favorites": {"artist": None}}}],
    "settings_update": [{"patch": {"dwellMs": 1200}}],
    "permissions_check": [{}],
    "open_settings_pane": [{"pane": "screen_recording"}],
    "hello_ack": [{"version": "0.1.0", "demo_mode": True, "profile": PROFILE, "settings": SETTINGS,
                   "permissions": PERMS}],
    "permissions_status": [PERMS],
    "suggestions": [{"list_id": "L", "window_key": "k", "app": "Mail", "items": [PLAN, PLAN, PLAN],
                     "cached": False}],
    "decode_result": [{"sentences": ["Tell Mom I'll be late."]}],
    "plans": [{"list_id": "L", "items": [PLAN, {**PLAN, "id": "p2", "detail": "Messages"}, OTHER]}],
    "task_status": [{"task_id": T, "state": "running", "step": 0, "max_steps": 15, "message": "Starting"}],
    "choice_request": [{"task_id": T, "question": "Which date?",
                        "options": [{"id": "a", "label": "Fri"}, {"id": "b", "label": "Sat", "detail": "late"}]}],
    "confirm_request": [{"task_id": T, "action": "buy", "title": "Buy?", "details": ["Qty: 2"], "source": "both",
                         "demo_noop": True}],
    "task_result": [{"task_id": T, "ok": True, "summary": "Done"},
                    {"task_id": T, "ok": False, "summary": "Failed", "list_id": "L", "recovery": [RETRY]}],
    "profile_result": [{"profile": PROFILE}],
    "settings_result": [{"settings": SETTINGS}],
    "error": [{"code": "stale_list", "message": "old"}, {"code": "no_task", "message": "x", "task_id": T}],
}

INVALID: list[tuple[str, dict]] = [
    ("plans", {"list_id": "L", "items": [{**PLAN, "label": "x" * 41}, PLAN, OTHER]}),   # label > 40
    ("plans", {"list_id": "L", "items": [PLAN, OTHER]}),                                  # too few
    ("task_status", {"task_id": T, "state": "running", "step": 16, "max_steps": 15, "message": ""}),
    ("task_result", {"task_id": T, "ok": False, "summary": "x", "recovery": [RETRY]}),   # recovery w/o list_id
    ("choice_response", {"task_id": T}),                                                  # choice_id required
    ("confirm_response", {"task_id": "not-a-uuid", "confirmed": True}),
    ("hello", {"client": "overlay", "version": "1", "extra": 1}),                         # unknown field
    ("settings_result", {"settings": {**SETTINGS, "dwellMs": 50}}),
    ("error", {"code": "nope", "message": ""}),
]


def schema_errors(mtype: str, payload: dict) -> list[str]:
    v = Draft202012Validator({"$defs": SCHEMA["$defs"], "$ref": f"#/$defs/payload_{mtype}"})
    return [e.message for e in v.iter_errors(payload)]


def test_every_message_type_has_a_model_and_samples():
    assert set(protocol.PAYLOADS) == set(SCHEMA["x-messages"])
    assert set(VALID) == set(SCHEMA["x-messages"])
    directions = {t: "o2a" for t in protocol.O2A} | {t: "a2o" for t in protocol.A2O}
    assert directions == SCHEMA["x-messages"]


@pytest.mark.parametrize("mtype,payload", [(t, p) for t, ps in VALID.items() for p in ps])
def test_valid_sample_round_trips(mtype, payload):
    assert schema_errors(mtype, payload) == []
    model = protocol.parse_payload(mtype, payload)
    dumped = protocol.dump_payload(model)
    assert dumped == payload
    assert schema_errors(mtype, dumped) == []


@pytest.mark.parametrize("mtype,payload", INVALID)
def test_invalid_sample_rejected_by_both(mtype, payload):
    assert schema_errors(mtype, payload), "schema accepted an invalid payload"
    with pytest.raises(ValidationError):
        protocol.parse_payload(mtype, payload)


def test_envelope():
    env = {"v": 1, "type": "stop", "id": T, "re": None, "ts": 0, "payload": {"reason": "user"}}
    v = Draft202012Validator({"$defs": SCHEMA["$defs"], "$ref": "#/$defs/Envelope"})
    assert list(v.iter_errors(env)) == []
    assert protocol.Envelope.model_validate(env).model_dump(mode="json") == env
    with pytest.raises(ValidationError):
        protocol.Envelope.model_validate({**env, "v": 2})
