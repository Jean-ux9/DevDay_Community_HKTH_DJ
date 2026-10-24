from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import fake_agent
import wsproto
from gaze_client import GazeClient


def test_demo_profile_validates_against_protocol_profile() -> None:
    profile = json.loads((ROOT / "fixtures" / "demo_profile.json").read_text(encoding="utf-8"))
    assert wsproto.def_errors("Profile", profile) == []
    assert profile["contacts"]["Mom"] == ["+1 555 0100"]
    assert profile["contacts"]["Alex"] == ["alex@example.com"]
    assert profile["address"]["email"] == "sam@example.com"


def outbound_payloads() -> dict[str, dict[str, Any]]:
    profile = json.loads((ROOT / "fixtures" / "demo_profile.json").read_text(encoding="utf-8"))
    plan = {"id": "p1", "label": "Open Safari", "kind": "task", "risky": False}
    recovery = {"id": "recovery:show_screen", "label": "Show me the screen",
                "kind": "recovery", "risky": False}
    task_id = wsproto.new_id()
    return {
        "hello_ack": {
            "version": fake_agent.APP_VERSION, "demo_mode": True, "profile": profile,
            "settings": fake_agent.DEFAULT_SETTINGS, "permissions": fake_agent.Session.permissions(),
        },
        "permissions_status": fake_agent.Session.permissions(),
        "suggestions": {"list_id": wsproto.new_id(), "window_key": "com.apple.Safari|Start Page",
                        "app": "Safari", "items": [plan, plan, plan], "cached": False},
        "decode_result": {"sentences": ["Open Safari."]},
        "plans": {"list_id": wsproto.new_id(), "items": [plan, plan, {**plan, "id": "other",
                                                                           "label": "Something else",
                                                                           "kind": "other"}]},
        "task_status": {"task_id": task_id, "state": "running", "step": 0,
                         "max_steps": 15, "message": "Opening Safari…"},
        "choice_request": {"task_id": task_id, "question": "Choose a date",
                           "options": [{"id": "fri", "label": "Friday"},
                                       {"id": "sat", "label": "Saturday"}]},
        "confirm_request": {"task_id": task_id, "action": "send", "title": "Send message?",
                            "details": ["To: Mom"], "source": "rule", "demo_noop": False},
        "task_result": {"task_id": task_id, "ok": False, "summary": "Could not continue.",
                         "list_id": wsproto.new_id(), "recovery": [recovery]},
        "profile_result": {"profile": profile},
        "settings_result": {"settings": fake_agent.DEFAULT_SETTINGS},
        "error": {"code": "bad_message", "message": "Invalid request."},
    }


def test_every_fake_agent_outbound_message_type_validates() -> None:
    expected = {name for name, direction in wsproto.DIRECTIONS.items() if direction == "a2o"}
    payloads = outbound_payloads()
    assert set(payloads) == expected
    for message_type, payload in payloads.items():
        message = wsproto.make(message_type, payload, direction="a2o")
        assert wsproto.message_errors(message, "a2o") == []


def test_gaze_client_drops_messages_for_dead_task_and_keeps_latest_list() -> None:
    client = GazeClient(1234, "test-token")
    task_id = wsproto.new_id()
    client.active_task_id = task_id
    active = wsproto.make("task_status", {
        "task_id": task_id, "state": "running", "step": 1, "max_steps": 15, "message": "Working…",
    }, direction="a2o")
    assert client._accept(active)

    recovery_list_id = wsproto.new_id()
    result = wsproto.make("task_result", {
        "task_id": task_id, "ok": False, "summary": "Failed.", "list_id": recovery_list_id,
        "recovery": [{"id": "recovery:retry", "label": "Try again", "kind": "recovery", "risky": False}],
    }, direction="a2o")
    assert client._accept(result)
    assert client.active_task_id is None
    assert client.list_id == recovery_list_id

    late = wsproto.make("confirm_request", {
        "task_id": task_id, "action": "send", "title": "Send?", "details": [],
        "source": "rule", "demo_noop": False,
    }, direction="a2o")
    assert not client._accept(late)
    assert client.dropped == [late]


def test_hello_ack_resets_task_and_list_state() -> None:
    client = GazeClient(1234, "test-token")
    client.active_task_id = wsproto.new_id()
    client.list_id = wsproto.new_id()
    client.list_items = [{"id": "old", "label": "old"}]
    client._pending_select = wsproto.new_id()
    ack = wsproto.make("hello_ack", outbound_payloads()["hello_ack"], direction="a2o")

    assert client._accept(ack)
    assert client.active_task_id is None
    assert client.list_id is None
    assert client.list_items == []
    assert client._pending_select is None
