from __future__ import annotations

import json
import asyncio
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import fake_agent
import fake_overlay
import pytest
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


def repl_client():
    client = GazeClient(1234, "test-token")
    frames = []
    class Socket:
        async def send(self, frame):
            frames.append(json.loads(frame))
    client.ws = Socket()
    return client, frames


@pytest.mark.parametrize("local_id", ["other", "recovery:cancel"])
def test_repl_local_cards_do_not_send_and_keep_intent(local_id, capsys):
    client, frames = repl_client()
    client.list_id = wsproto.new_id()
    client.list_items = [{"id": local_id}]
    state = {"intent": "Open a blank document", "choice": {}, "confirm": {}}
    asyncio.run(fake_overlay.command(client, state, "select 1"))
    assert frames == []
    assert client.list_id is None and client.list_items == []
    assert state == {"intent": "Open a blank document"}
    assert "intent <text>" in capsys.readouterr().out


@pytest.mark.parametrize("line", ["choose 0", "choose -1", "choose 99", "choose nope"])
def test_repl_invalid_choice_preserves_pending_request(line):
    client, frames = repl_client()
    request = wsproto.make("choice_request", outbound_payloads()["choice_request"], direction="a2o")
    client.active_task_id = request["payload"]["task_id"]
    state = {"choice": request}
    with pytest.raises((ValueError, IndexError)):
        asyncio.run(fake_overlay.command(client, state, line))
    assert state["choice"] is request and frames == []
    asyncio.run(fake_overlay.command(client, state, "choose 1"))
    assert "choice" not in state
    assert frames[0]["re"] == request["id"]
    assert frames[0]["payload"]["choice_id"] == request["payload"]["options"][0]["id"]


def test_repl_invalid_confirmation_preserves_request():
    client, frames = repl_client()
    request = wsproto.make("confirm_request", outbound_payloads()["confirm_request"], direction="a2o")
    client.active_task_id = request["payload"]["task_id"]
    state = {"confirm": request}
    with pytest.raises(ValueError, match="confirm yes|no"):
        asyncio.run(fake_overlay.command(client, state, "confirm maybe"))
    assert state["confirm"] is request and frames == []
    asyncio.run(fake_overlay.command(client, state, "confirm no"))
    assert frames[0]["payload"]["confirmed"] is False
    assert "confirm" not in state


@pytest.mark.parametrize("line", ["select 0", "select -1", "select 99"])
def test_repl_plan_numbers_are_positive_and_bounded(line):
    client, frames = repl_client()
    client.list_id = wsproto.new_id()
    client.list_items = [{"id": "p1"}]
    with pytest.raises((ValueError, IndexError)):
        asyncio.run(fake_overlay.command(client, {}, line))
    assert frames == []


def test_repl_select_during_choice_explains_choose_without_sending():
    client, frames = repl_client()
    client.active_task_id = wsproto.new_id()
    with pytest.raises(RuntimeError, match="choose"):
        asyncio.run(fake_overlay.command(client, {"choice": {}}, "select 1"))
    assert frames == []


@pytest.mark.parametrize("kind", ["task_status", "task_result", "hello_ack"])
def test_repl_terminal_and_reconnect_clear_displayed_waits(kind, capsys):
    payload = outbound_payloads()[kind]
    if kind == "task_status":
        payload = {**payload, "state": "stopped"}
    state = {"choice": {}, "confirm": {}, "intent": "Preserved text"}
    fake_overlay.show(wsproto.make(kind, payload, direction="a2o"), state)
    assert "choice" not in state and "confirm" not in state
    assert state["intent"] == "Preserved text"


@pytest.mark.parametrize("kind,hint", [("plans", "select 1"), ("task_result", "select 1"),
                                      ("choice_request", "choose 1"), ("confirm_request", "confirm no")])
def test_repl_displays_actionable_commands(kind, hint, capsys):
    fake_overlay.show(wsproto.make(kind, outbound_payloads()[kind], direction="a2o"), {})
    assert hint in capsys.readouterr().out


def test_low_level_select_still_supports_server_negative_tests():
    client, frames = repl_client()
    client.list_id = wsproto.new_id()
    client.list_items = [{"id": "recovery:cancel"}]
    asyncio.run(client.select(0))
    assert frames[0]["type"] == "plan_select"


def test_repl_selection_error_allows_a_corrected_selection():
    client, frames = repl_client()
    client.list_id = wsproto.new_id()
    client.list_items = [{"id": "p1"}]
    asyncio.run(fake_overlay.command(client, {}, "select 1"))
    assert client._pending_select == frames[0]["id"]
    assert client._accept(wsproto.make("error", {"code": "stale_list", "message": "Replaced"},
                                      re=frames[0]["id"], direction="a2o"))
    asyncio.run(fake_overlay.command(client, {}, "select 1"))
    assert len(frames) == 2


def test_send_failure_clears_pending_selection():
    client = GazeClient(1234, "test-token")
    with pytest.raises(AssertionError):
        asyncio.run(client.send("plan_select", {"list_id": wsproto.new_id(), "plan_id": "p1"}))
    assert client._pending_select is None


def test_disconnect_resets_client_state():
    async def run():
        client, _ = repl_client()
        client.active_task_id = client.list_id = client._pending_select = wsproto.new_id()
        client.list_items = [{"id": "p1"}]
        class Socket:
            close_code, close_reason = 1000, ""
            def __aiter__(self):
                return self
            async def __anext__(self):
                raise StopAsyncIteration
        client.ws = Socket()
        await client._read()
        assert client.closed is not None
        assert client.active_task_id is client.list_id is client._pending_select is None
        assert client.list_items == []
    asyncio.run(run())
