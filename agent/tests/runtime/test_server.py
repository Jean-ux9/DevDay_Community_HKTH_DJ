import asyncio
import json
import os
import time

import pytest
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed

from gaze_agent.contracts import LLMError, LLMResponse, ToolCall
from gaze_agent.protocol import Plan
from tests.runtime.support import (ROOT, INFO, FakeDesktop, complete, connect, eventually,
                                   running_server, select)


def test_real_agent_with_task_d_flows(tmp_path, monkeypatch):
    async def run():
        async with running_server(tmp_path, monkeypatch) as (port, sessions):
            proc = await asyncio.create_subprocess_exec("uv", "run", str(ROOT / "scripts/fake_overlay.py"),
                "demo", "stop_during_confirm", "task_busy", "stale_list", "settings", "bad_input",
                cwd=ROOT, env={**os.environ, "GAZE_TOKEN": "test-token", "GAZE_PORT": str(port)},
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            output, _ = await asyncio.wait_for(proc.communicate(), 40)
            print("\n" + output.decode())
            assert proc.returncode == 0, output.decode()
            assert output.decode().count("PASS ") == 5
            assert all(not s.active for s in sessions)
    asyncio.run(run())


@pytest.mark.parametrize("query", ["", "?token=wrong"])
def test_missing_or_wrong_token_closes_4401(tmp_path, monkeypatch, query):
    async def run():
        async with running_server(tmp_path, monkeypatch) as (port, _):
            async with ws_connect(f"ws://127.0.0.1:{port}/{query}") as ws:
                with pytest.raises(ConnectionClosed) as error:
                    await ws.recv()
                assert error.value.rcvd.code == 4401
    asyncio.run(run())


def test_validation_is_schema_strict_and_hello_required(tmp_path, monkeypatch):
    async def run():
        async with running_server(tmp_path, monkeypatch) as (port, _):
            async with ws_connect(f"ws://127.0.0.1:{port}/?token=test-token") as ws:
                import wsproto
                request = wsproto.make("permissions_check", {})
                await ws.send(json.dumps(request))
                assert json.loads(await ws.recv())["payload"]["code"] == "bad_message"
                hello = wsproto.make("hello", {"client": "overlay", "version": "anything"})
                await ws.send(json.dumps(hello))
                assert json.loads(await ws.recv())["re"] == hello["id"]
                for raw in ["[]", "{not json", json.dumps(wsproto.make("mode_set", {"mode": "auto"}) | {"extra": 3}),
                            json.dumps(wsproto.make("stop", {"reason": "user"}) | {"payload": {"reason": 5}})]:
                    await ws.send(raw)
                    assert json.loads(await ws.recv())["payload"]["code"] == "bad_message"
    asyncio.run(run())


def test_stop_ten_second_tool_in_under_200ms(tmp_path, monkeypatch):
    desktops = []
    def factory(profile):
        desktop = FakeDesktop()
        desktop.slow = True
        desktops.append(desktop)
        return desktop
    async def run():
        async with running_server(tmp_path, monkeypatch, desktop_factory=factory) as (port, sessions):
            async with await connect(port) as client:
                task_id = await select(client, "play focus")
                await asyncio.wait_for(desktops[0].started.wait(), 2)
                started = time.monotonic()
                await client.send("stop", {"reason": "gaze"})
                await client.next("task_status", task_id=task_id, state="stopped")
                elapsed = time.monotonic() - started
                print(f"\nSTOP during 10s tool: {elapsed * 1000:.1f}ms")
                assert elapsed < 0.2
                await client.next("task_result", task_id=task_id)
                assert desktops[0].cancelled and desktops[0].released and not desktops[0].calls
                assert sessions[0].watcher.states[:2] == [True, False]
    asyncio.run(run())


def test_stop_at_confirm_rejects_late_yes(tmp_path, monkeypatch):
    async def run():
        async with running_server(tmp_path, monkeypatch) as (port, sessions):
            async with await connect(port) as client:
                task_id = await select(client)
                request = await client.next("confirm_request", task_id=task_id)
                desktop = sessions[0].active.desktop
                await client.send("stop", {"reason": "hotkey"})
                await client.next("task_result", task_id=task_id)
                late = await client.send("confirm_response", {"task_id": task_id, "confirmed": True}, re=request["id"])
                await client.expect_nothing("error", 0.1, re=late["id"])
                assert any(m["type"] == "error" and m["re"] == late["id"] and
                           m["payload"]["code"] == "no_task" for m in client.dropped), client.dropped
                assert desktop.calls == []
    asyncio.run(run())


def test_confirmation_requires_task_and_request_correlation(tmp_path, monkeypatch):
    async def run():
        async with running_server(tmp_path, monkeypatch) as (port, sessions):
            async with await connect(port) as client:
                import uuid
                task_id = await select(client)
                request = await client.next("confirm_request")
                foreign = await client.send("confirm_response", {"task_id": str(uuid.uuid4()), "confirmed": True},
                                            re=request["id"])
                await client.expect_nothing("error", 0.1, re=foreign["id"])
                assert any(m["type"] == "error" and m["re"] == foreign["id"] and
                           m["payload"]["code"] == "no_task" for m in client.dropped), client.dropped
                bad = await client.send("confirm_response", {"task_id": task_id, "confirmed": True}, re=str(uuid.uuid4()))
                assert (await client.next("error", re=bad["id"]))["payload"]["code"] == "no_task"
                desktop = sessions[0].active.desktop
                await client.send("confirm_response", {"task_id": task_id, "confirmed": True}, re=request["id"])
                assert (await client.next("task_result"))["payload"]["ok"]
                assert len(desktop.calls) == 1
                terminals = [m for m in client.inbox if m["type"] == "task_status" and m["payload"]["state"] == "done"]
                assert len(terminals) == 1 and terminals[0]["re"] is None
    asyncio.run(run())


def test_disconnect_cancels_model_and_resets_watcher(tmp_path, monkeypatch):
    started, cancelled = None, None
    async def slow(*args, **kwargs):
        started.set()
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()
    async def run():
        nonlocal started, cancelled
        started, cancelled = asyncio.Event(), asyncio.Event()
        async with running_server(tmp_path, monkeypatch, completion=slow) as (port, sessions):
            client = await connect(port)
            await select(client)
            await started.wait()
            await client.close()
            await asyncio.wait_for(cancelled.wait(), 1)
            await eventually(lambda: not sessions[0].active)
            assert sessions[0].watcher.states[0] is True
            assert sessions[0].watcher.states[-1] is False
            async with await connect(port) as fresh:
                assert fresh.active_task_id is None
    asyncio.run(run())


def test_unknown_plan_idle_stop_and_modes(tmp_path, monkeypatch):
    async def run():
        async with running_server(tmp_path, monkeypatch) as (port, sessions):
            async with await connect(port) as client:
                await client.send("stop", {"reason": "user"})
                await client.send("mode_set", {"mode": "type"})
                await eventually(lambda: sessions[0].watcher.mode == "type")
                request = await client.send("intent_submit", {"text": "play focus"})
                plans = await client.next("plans", re=request["id"])
                bad = await client.send("plan_select", {"list_id": plans["payload"]["list_id"], "plan_id": "missing"})
                assert (await client.next("error", re=bad["id"]))["payload"]["code"] == "unknown_plan"
                assert not sessions[0].active
    asyncio.run(run())


def test_suggestions_dropped_after_mode_or_window_change(tmp_path, monkeypatch):
    async def run():
        async with running_server(tmp_path, monkeypatch) as (port, sessions):
            async with await connect(port) as client:
                session = sessions[0]
                items = [Plan(id=str(i), label="Suggestion", kind="task", risky=False) for i in range(3)]
                await session.suggestions("old-window", "Messages", items, False)
                assert session.list_id is None
                await session.suggestions(INFO.window_key, "Messages", items, True)
                message = await client.next("suggestions")
                assert message["payload"]["cached"]
                old_list = session.list_id
                session.mode = "type"
                await session.suggestions(INFO.window_key, "Messages", items, False)
                assert session.list_id == old_list
    asyncio.run(run())


def test_llm_failure_produces_one_terminal_and_recovery(tmp_path, monkeypatch):
    async def failed(*args, **kwargs):
        raise LLMError("fake failure containing private provider details")
    async def run():
        async with running_server(tmp_path, monkeypatch, completion=failed) as (port, sessions):
            async with await connect(port) as client:
                await select(client)
                result = await client.next("task_result")
                assert not result["payload"]["ok"] and len(result["payload"]["recovery"]) == 3
                assert "private provider" not in json.dumps(result)
                assert sessions[0].watcher.states[:2] == [True, False]
    asyncio.run(run())
