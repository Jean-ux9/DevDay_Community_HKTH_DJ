import asyncio
import copy
import json
import uuid
from dataclasses import replace

import pytest

from gaze_agent.contracts import GateDecision, LLMResponse, ToolCall
from gaze_agent.loop import TaskLoop
from gaze_agent.tasklog import TaskLog
from tests.runtime.support import (SNAPSHOT, FakeDesktop, complete, connect, eventually, gate,
                                   look, plan, profile, running_server, select)


def test_sixteenth_tool_call_fails_with_recovery(tmp_path, monkeypatch):
    async def forever(*args, **kwargs):
        return LLMResponse(None, [ToolCall(str(uuid.uuid4()), "open_app", {"name": "Music"})], None, False)
    async def run():
        async with running_server(tmp_path, monkeypatch, completion=forever) as (port, sessions):
            async with await connect(port) as client:
                await select(client, "play focus")
                desktop = sessions[0].active.desktop
                result = await client.next("task_result")
                assert not result["payload"]["ok"] and "15" in result["payload"]["summary"]
                assert len(desktop.calls) == 15
                assert [p["id"] for p in result["payload"]["recovery"]] == [
                    "recovery:retry", "recovery:show_screen", "recovery:cancel"]
    asyncio.run(run())


def test_waiting_user_time_is_excluded(tmp_path, monkeypatch):
    async def run():
        async with running_server(tmp_path, monkeypatch, max_seconds=0.15) as (port, sessions):
            async with await connect(port) as client:
                task_id = await select(client)
                request = await client.next("confirm_request")
                await asyncio.sleep(0.25)
                assert sessions[0].active is not None
                await client.send("confirm_response", {"task_id": task_id, "confirmed": True}, re=request["id"])
                assert (await client.next("task_result"))["payload"]["ok"]
    asyncio.run(run())


def test_active_time_limit_cancels_llm(tmp_path, monkeypatch):
    cancelled = []
    async def slow(*args, **kwargs):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.append(True)
    async def run():
        async with running_server(tmp_path, monkeypatch, completion=slow, max_seconds=0.03) as (port, _):
            async with await connect(port) as client:
                await select(client)
                result = await client.next("task_result")
                assert not result["payload"]["ok"] and "limit" in result["payload"]["summary"]
                assert cancelled == [True]
    asyncio.run(run())


def test_stale_snapshot_error_returns_current_screen(tmp_path, monkeypatch):
    histories = []
    async def scripted(prompt, model, vars, **kwargs):
        histories.append(kwargs["input_items"])
        if not histories[-1]:
            call = ToolCall("stale", "click_element", {"id": "e1", "snapshot_id": "old"})
        else:
            call = ToolCall("finish", "finish", {"ok": False, "summary": "Stopped after stale snapshot"})
        return LLMResponse(None, [call], None, False)
    async def run():
        async with running_server(tmp_path, monkeypatch, completion=scripted) as (port, sessions):
            async with await connect(port) as client:
                await select(client)
                result = await client.next("task_result")
                output = json.loads(histories[-1][-1]["output"])
                assert "stale_snapshot" in output["error"] and "snapshot fixture-snapshot" in output["screen"]
                assert not result["payload"]["ok"]
                assert not any(m["type"] == "confirm_request" for m in client.inbox)
    asyncio.run(run())


def test_tool_errors_allow_only_two_retries(tmp_path, monkeypatch):
    attempts = []
    async def repeated(*args, **kwargs):
        attempts.append(True)
        return LLMResponse(None, [ToolCall(str(uuid.uuid4()), "click_element", {"id": "e1", "snapshot_id": "old"})], None, False)
    async def run():
        async with running_server(tmp_path, monkeypatch, completion=repeated) as (port, _):
            async with await connect(port) as client:
                await select(client)
                result = await client.next("task_result")
                assert not result["payload"]["ok"] and "two retries" in result["payload"]["summary"]
                assert len(attempts) == 3
    asyncio.run(run())


def test_ambiguous_contacts_resolved_before_model_sees_profile(tmp_path, monkeypatch):
    seen = []
    async def scripted(prompt, model, vars, **kwargs):
        seen.append(json.loads(vars["profile_summary"])["contacts"])
        return LLMResponse(None, [ToolCall("done", "finish", {"ok": True, "summary": "Resolved"})], None, False)
    async def run():
        async with running_server(tmp_path, monkeypatch, completion=scripted) as (port, sessions):
            async with await connect(port) as client:
                sessions[0].store.update_profile({"contacts": {"Mom": ["+1 555 0100", "+1 555 0101"]}})
                task_id = await select(client)
                request = await client.next("choice_request")
                assert not seen
                bad = await client.send("choice_response", {"task_id": task_id, "choice_id": "invalid"}, re=request["id"])
                assert (await client.next("error", re=bad["id"]))["payload"]["code"] == "no_task"
                await client.send("choice_response", {"task_id": task_id, "choice_id": "1"}, re=request["id"])
                assert (await client.next("task_result"))["payload"]["ok"]
                assert seen == [{"Mom": ["+1 555 0101"]}]
    asyncio.run(run())


def test_recovery_screen_only_and_retry_uses_new_task_id(tmp_path, monkeypatch):
    invocations = []
    async def scripted(*args, **kwargs):
        invocations.append(True)
        return LLMResponse(None, [ToolCall("done", "finish", {"ok": len(invocations) > 1, "summary": "Fixture result"})], None, False)
    async def run():
        async with running_server(tmp_path, monkeypatch, completion=scripted) as (port, _):
            async with await connect(port) as client:
                first_id = await select(client)
                assert not (await client.next("task_result"))["payload"]["ok"]
                request = await client.select(1)
                screen_id = (await client.next("task_status", re=request["id"]))["payload"]["task_id"]
                screen_result = (await client.next("task_result"))["payload"]
                assert screen_result["ok"] and "Fake Messages" in screen_result["summary"]
                assert len(invocations) == 1  # show_screen never runs the model's action loop
                assert [p["id"] for p in screen_result["recovery"]] == ["recovery:retry", "recovery:cancel"]
                retry = await client.select(0)
                retry_id = (await client.next("task_status", re=retry["id"]))["payload"]["task_id"]
                assert (await client.next("task_result"))["payload"]["ok"]
                assert len({first_id, screen_id, retry_id}) == 3
    asyncio.run(run())


def test_demo_buy_is_a_noop_and_cancel_blocks_actions(tmp_path):
    async def run(confirmed):
        desktop, events = FakeDesktop(), []
        task = None
        async def emit(kind, payload, **kwargs):
            events.append((kind, payload))
            if kind == "confirm_request":
                assert payload["demo_noop"]
                task.respond("confirm_response", task.task_id, kwargs["message_id"], {"confirmed": confirmed})
        async def scripted(*args, **kwargs):
            if kwargs["input_items"]:
                return LLMResponse(None, [ToolCall("f", "finish", {"ok": True, "summary": "Finished"})], None, False)
            return LLMResponse(None, [ToolCall("c", "click_element", {"id": "e1", "snapshot_id": SNAPSHOT.snapshot_id})], None, False)
        task = TaskLoop(task_id=str(uuid.uuid4()), plan=plan(), profile=profile(), emit=emit,
            desktop=desktop, get_screen=lambda: copy.deepcopy(SNAPSHOT), look_at_screen=look,
            log=TaskLog(tmp_path), demo=True, complete=scripted,
            gate=lambda a, s: GateDecision(True, "buy", "Buy tickets?", ["Price: $10"], "rule"))
        assert (await task.run()).ok
        assert desktop.calls == []
        assert task.user_cancelled is (not confirmed)
    asyncio.run(run(True))
    asyncio.run(run(False))


@pytest.mark.parametrize("change", ["app", "window", "focus", "text", "bounds", "disabled"])
@pytest.mark.parametrize("tool", ["click_element", "press_keys", "type_text"])
def test_confirmation_rejects_changed_context_before_desktop(tmp_path, change, tool):
    async def run():
        current = copy.deepcopy(SNAPSHOT)
        desktop = FakeDesktop()
        task = None
        async def emit(kind, payload, **kwargs):
            nonlocal current
            if kind != "confirm_request":
                return
            if change == "app":
                current = replace(current, app="Mail", bundle_id="com.apple.mail")
            elif change == "window":
                current = replace(current, window_title="Different conversation")
            elif change == "focus":
                current = replace(current, focused=None)
            else:
                target = replace(current.elements[0], **{
                    "text": {"label": "Different draft"},
                    "bounds": {"bbox": (200, 200, 80, 30)},
                    "disabled": {"enabled": False},
                }[change])
                current = replace(current, elements=[target], focused=target)
            task.respond("confirm_response", task.task_id, kwargs["message_id"], {"confirmed": True})
        args = {"click_element": {"id": "e1", "snapshot_id": SNAPSHOT.snapshot_id},
                "press_keys": {"keys": ["cmd", "enter"]},
                "type_text": {"text": "Demo text", "submit": True}}[tool]
        async def scripted(*args_, **kwargs):
            call = ToolCall("finish", "finish", {"ok": True, "summary": "Done"}) if kwargs["input_items"] else ToolCall("send", tool, args)
            return LLMResponse(None, [call], None, False)
        task = TaskLoop(task_id=str(uuid.uuid4()), plan=plan(), profile=profile(), emit=emit,
            desktop=desktop, get_screen=lambda: copy.deepcopy(current), look_at_screen=look,
            log=TaskLog(tmp_path), complete=scripted)
        result = await task.run()
        assert not result.ok and "confirmation" in result.summary.lower()
        assert desktop.calls == []
    asyncio.run(run())


def test_confirmation_rebinds_unchanged_target_to_fresh_snapshot(tmp_path):
    async def run():
        desktop = FakeDesktop()
        current = copy.deepcopy(SNAPSHOT)
        task = None
        async def emit(kind, payload, **kwargs):
            nonlocal current
            if kind == "confirm_request":
                target = replace(current.elements[0], id="fresh-element")
                current = replace(current, snapshot_id="fresh-snapshot", elements=[target], focused=target)
                task.respond("confirm_response", task.task_id, kwargs["message_id"], {"confirmed": True})
        task = TaskLoop(task_id=str(uuid.uuid4()), plan=plan(), profile=profile(), emit=emit,
            desktop=desktop, get_screen=lambda: copy.deepcopy(current), look_at_screen=look,
            log=TaskLog(tmp_path), complete=complete, gate=gate)
        assert (await task.run()).ok
        assert desktop.calls == [("click_element", {"id": "fresh-element", "snapshot_id": "fresh-snapshot"})]
    asyncio.run(run())


@pytest.mark.parametrize("title,label", [("Different recipient", "Mom"), ("Different recipient", "+1 555 0100"),
                                        ("Moments", "Send"), ("NotMom", "Send")])
def test_demo_send_rejects_incidental_or_partial_contact_text(tmp_path, title, label):
    task = TaskLoop(task_id=str(uuid.uuid4()), plan=plan(), profile=profile(), emit=None,
        desktop=FakeDesktop(), get_screen=None, look_at_screen=look, log=TaskLog(tmp_path),
        demo=True, demo_contacts=profile()["contacts"])
    task.snapshot = replace(SNAPSHOT, window_title=title, elements=[replace(SNAPSHOT.elements[0], label=label)])
    assert not task.demo_send_allowed()


@pytest.mark.parametrize("context_change", ["native_window", "native_focus", "read_failure", "stop"])
def test_confirmation_recheck_native_identity_errors_and_stop(tmp_path, monkeypatch, context_change):
    from gaze_agent.screen import ax
    async def run():
        desktop = FakeDesktop()
        task = None
        confirmed = False
        monkeypatch.setattr(ax, "snapshot_context", lambda _: (
            "new-window" if confirmed and context_change == "native_window" else "window",
            "new-focus" if confirmed and context_change == "native_focus" else "focus"))
        def screen():
            if confirmed and context_change == "read_failure":
                raise RuntimeError("Synthetic unavailable screen")
            if confirmed and context_change == "stop":
                task.cancel()
            return copy.deepcopy(SNAPSHOT)
        async def emit(kind, payload, **kwargs):
            nonlocal confirmed
            if kind == "confirm_request":
                confirmed = True
                task.respond("confirm_response", task.task_id, kwargs["message_id"], {"confirmed": True})
        task = TaskLoop(task_id=str(uuid.uuid4()), plan=plan(), profile=profile(), emit=emit,
            desktop=desktop, get_screen=screen, look_at_screen=look, log=TaskLog(tmp_path),
            complete=complete, gate=gate)
        if context_change == "stop":
            with pytest.raises(asyncio.CancelledError):
                await task.run()
        else:
            result = await task.run()
            assert not result.ok and "confirmation" in result.summary.lower()
        assert desktop.calls == []
    asyncio.run(run())


@pytest.mark.parametrize("title", ["Mom", "To: Mom", "Mom — Demo conversation", "+1 555 0100"])
def test_demo_send_accepts_complete_allowed_recipient_title(tmp_path, title):
    task = TaskLoop(task_id=str(uuid.uuid4()), plan=plan(), profile=profile(), emit=None,
        desktop=FakeDesktop(), get_screen=None, look_at_screen=look, log=TaskLog(tmp_path),
        demo=True, demo_contacts=profile()["contacts"])
    task.snapshot = replace(SNAPSHOT, window_title=title)
    assert task.demo_send_allowed()
