import asyncio
import json
import os
import sys
import time
from functools import partial
from types import SimpleNamespace

import pytest
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed

from gaze_agent import server
from gaze_agent.contracts import LLMError, LLMResponse, ToolCall
from gaze_agent.protocol import Plan
from tests.runtime.support import (ROOT, INFO, FakeDesktop, complete, connect, eventually,
                                   DemoHarness, running_server, select)

import rehearse

# The test below invokes this only with Cocoa and subprocess entirely replaced.
ACTIVATE_APP = rehearse.activate_app

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


@pytest.mark.parametrize("name", ["D1", "D2", "D3", "D4"])
def test_rehearsal_demos_through_real_server_and_loop(tmp_path, monkeypatch, name):
    """Real WS/Session/TaskLoop/planner/Auto/gate; only model and desktop are fake."""
    async def run():
        harness = DemoHarness()
        async with harness.server(tmp_path, monkeypatch) as (port, sessions):
            detail = await rehearse.run_demo(partial(harness.connect, port), name, prepare=harness.prepare)
            assert harness.prepared == [rehearse.DEMOS[name].app]
            await eventually(lambda: sessions[0].active is None)
            client = harness.clients[0]
            assert not client.invalid and not client.dropped
            assert harness.actions  # The actual loop dispatched to the fake desktop.
            requests = [m for m in client.sent if m["type"] in {"choice_response", "confirm_response"}]
            assert len({m["re"] for m in requests}) == len(requests)
            if name in {"D1", "D2"}:
                confirms = [m for m in requests if m["type"] == "confirm_response"]
                assert confirms and all(m["payload"]["confirmed"] for m in confirms)
                if name == "D1":
                    assert "sentence_decode" in harness.prompts
                    assert any(tool == "click_element" and args["id"] == "send" for tool, args in harness.actions)
                else:
                    assert "auto_suggest" in harness.prompts
                    assert any(tool == "press_keys" for tool, _ in harness.actions)
            elif name == "D3":
                assert any(m["type"] == "choice_response" for m in requests)  # Choices are valid for D3 too.
                assert not any(m["type"] == "confirm_response" for m in requests)
                assert any(tool == "click_element" and args["id"] == "play" for tool, args in harness.actions)
            else:
                assert sum(m["type"] == "choice_response" for m in requests) == 2
                assert not any(m["type"] == "confirm_response" for m in requests)
                assert not any(tool == "click_element" and args["id"] == "buy" for tool, args in harness.actions)
                assert any(m["type"] == "stop" for m in client.sent)
                assert "stopped without purchase" in detail
            task_rows = [json.loads(line) for line in (tmp_path / "tasklog.jsonl").read_text().splitlines()]
            assert sum(row["tool"] == "task" for row in task_rows) == 1
            assert harness.desktops[0].cancelled and harness.desktops[0].released
    asyncio.run(run())


def test_rehearsal_excludes_multiple_slow_user_choices(tmp_path, monkeypatch):
    async def choose(request):
        await asyncio.sleep(0.2)  # Exceeds the active budget, twice, without doing any desktop work.
        return request["payload"]["options"][0]["id"]

    async def run():
        harness = DemoHarness()
        async with harness.server(tmp_path, monkeypatch, max_seconds=0.15) as (port, _):
            detail = await rehearse.run_demo(partial(harness.connect, port), "D4", prepare=harness.prepare,
                                             choose=choose, task_timeout=0.15)
            assert "2 choices" in detail
    asyncio.run(run())


def test_rehearsal_app_preparation_failure_does_not_submit_or_select(tmp_path, monkeypatch):
    async def failed(app):
        raise RuntimeError("Mail could not become frontmost")

    async def run():
        harness = DemoHarness()
        async with harness.server(tmp_path, monkeypatch) as (port, _):
            with pytest.raises(RuntimeError, match="frontmost"):
                await rehearse.run_demo(partial(harness.connect, port), "D2", prepare=failed)
            assert [m["type"] for m in harness.clients[0].sent] == ["hello", "mode_set"]
            assert not harness.actions
    asyncio.run(run())


def test_rehearsal_refuses_non_demo_profile_before_preparing_apps(tmp_path, monkeypatch):
    async def run():
        async with running_server(tmp_path, monkeypatch) as (port, _):
            prepared = []
            async def prepare(app):
                prepared.append(app)
            with pytest.raises(RuntimeError, match="exact fixtures"):
                await rehearse.run_demo(partial(connect, port), "D1", prepare=prepare)
            assert prepared == []
    asyncio.run(run())


def test_rehearsal_timeout_stops_real_loop_with_fake_slow_model(tmp_path, monkeypatch):
    async def run():
        harness = DemoHarness()
        scripted = harness.complete
        cancelled = asyncio.Event()
        async def slow(prompt, *args, **kwargs):
            if prompt != "task_system":
                return await scripted(prompt, *args, **kwargs)
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.set()
        harness.complete = slow
        async with harness.server(tmp_path, monkeypatch) as (port, sessions):
            with pytest.raises(TimeoutError):
                await rehearse.run_demo(partial(harness.connect, port), "D3", prepare=harness.prepare,
                                        task_timeout=0.03)
            await asyncio.wait_for(cancelled.wait(), 1)
            await eventually(lambda: sessions[0].active is None)
            assert harness.desktops[0].cancelled
            assert any(m["type"] == "stop" for m in harness.clients[0].sent)
    asyncio.run(run())


def test_rehearsal_task_clock_is_cumulative_and_pauses_user_waits():
    now = [0.0]
    budget = rehearse.TaskBudget(100, clock=lambda: now[0])
    now[0] = 80
    budget.status("running")
    assert budget.remaining() == 20
    budget.status("waiting_user")
    now[0] = 1080  # Choices have no timeout; this wait cannot spend active time.
    assert budget.remaining() is None
    budget.status("running")
    assert budget.remaining() == 20
    now[0] = 1095
    budget.status("running")
    assert budget.remaining() == 5
    now[0] = 1101
    assert budget.remaining() == 0


def test_rehearsal_refuses_suggestions_from_wrong_app(tmp_path, monkeypatch):
    original = server.Session.suggestions
    async def wrong_app(self, window_key, app, items, cached):
        await original(self, window_key, "Safari", items, cached)
    monkeypatch.setattr(server.Session, "suggestions", wrong_app)

    async def run():
        harness = DemoHarness()
        async with harness.server(tmp_path, monkeypatch) as (port, _):
            with pytest.raises(RuntimeError, match="not from Mail"):
                await rehearse.run_demo(partial(harness.connect, port), "D2", prepare=harness.prepare)
            assert not harness.actions
            assert not any(m["type"] == "plan_select" for m in harness.clients[0].sent)
    asyncio.run(run())


def test_rehearsal_never_confirms_an_unexpected_risky_action(tmp_path, monkeypatch):
    async def run():
        harness = DemoHarness()
        scripted = harness.complete
        async def delete_instead(prompt, model, vars, **kwargs):
            result = await scripted(prompt, model, vars, **kwargs)
            if result.tool_calls and result.tool_calls[0].name == "click_element":
                return LLMResponse(None, [ToolCall("delete", "press_keys", {"keys": ["cmd", "backspace"]})], None, False)
            return result
        harness.complete = delete_instead
        async with harness.server(tmp_path, monkeypatch) as (port, sessions):
            with pytest.raises(RuntimeError, match="Unexpected DELETE"):
                await rehearse.run_demo(partial(harness.connect, port), "D1", prepare=harness.prepare)
            await eventually(lambda: sessions[0].active is None)
            assert not any(tool == "press_keys" for tool, _ in harness.actions)
            assert not any(m["type"] == "confirm_response" for m in harness.clients[0].sent)
    asyncio.run(run())


def test_rehearsal_accepts_multiple_send_gates_without_exact_mock_counts(tmp_path, monkeypatch):
    async def run():
        harness = DemoHarness()
        scripted = harness.complete
        async def two_sends(prompt, model, vars, **kwargs):
            result = await scripted(prompt, model, vars, **kwargs)
            if prompt == "task_system" and len(kwargs["input_items"]) == 8:
                return LLMResponse(None, [ToolCall("second-send", "press_keys", {"keys": ["cmd", "enter"]})], None, False)
            return result
        harness.complete = two_sends
        async with harness.server(tmp_path, monkeypatch) as (port, _):
            detail = await rehearse.run_demo(partial(harness.connect, port), "D1", prepare=harness.prepare)
            assert "2 Send gates" in detail
            assert sum(m["type"] == "confirm_response" for m in harness.clients[0].sent) == 2
    asyncio.run(run())


@pytest.mark.parametrize("front_bundle", ["com.apple.mail", "com.apple.Safari"])
def test_native_app_preparation_checks_frontmost_bundle_with_cocoa_fake(monkeypatch, front_bundle):
    calls = []
    async def launch(*args):
        calls.append(args)
        async def wait():
            return 0
        return SimpleNamespace(wait=wait)
    front = SimpleNamespace(bundleIdentifier=lambda: front_bundle)
    workspace = SimpleNamespace(frontmostApplication=lambda: front)
    monkeypatch.setitem(sys.modules, "AppKit", SimpleNamespace(
        NSWorkspace=SimpleNamespace(sharedWorkspace=lambda: workspace)))
    monkeypatch.setattr(rehearse.asyncio, "create_subprocess_exec", launch)
    timeout = asyncio.timeout
    monkeypatch.setattr(rehearse.asyncio, "timeout", lambda _: timeout(0.01))
    if front_bundle == "com.apple.mail":
        asyncio.run(ACTIVATE_APP("Mail"))
    else:
        with pytest.raises(TimeoutError):
            asyncio.run(ACTIVATE_APP("Mail"))
    assert calls == [("/usr/bin/open", "-a", "Mail")]
