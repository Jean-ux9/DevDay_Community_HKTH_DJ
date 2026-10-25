"""Every explicit auto_refresh gets an answer: suggestions or an error with re = its id (fakes only)."""
import asyncio
import json
from dataclasses import replace

from gaze_agent import auto, llm
from gaze_agent.contracts import LLMError, LLMResponse
from tests.runtime.support import INFO, SNAPSHOT, connect, running_server

PLANS = json.dumps({"plans": [{"label": f"Open item {i}", "risky": False} for i in range(3)]})


def watcher(emit, *, info=lambda: INFO, now=lambda: 0.0):
    return auto.AutoWatcher(emit, info, lambda: SNAPSHOT, lambda: {"name": "Sam", "style": {}, "favorites": {},
                            "contacts": {}, "address": ""}, clock=now, ambient=False)


def test_refresh_reports_whether_it_was_accepted():
    clock = [0.0]
    w = watcher(None, now=lambda: clock[0])
    assert w.refresh() is True
    assert w.refresh() is False  # one already pending
    w._refresh, w._last_refresh = False, 0.0
    clock[0] = 2.9
    assert w.refresh() is False  # inside the 3 s gap
    clock[0] = 3.0
    assert w.refresh() is True


def test_a_consumed_refresh_without_suggestions_is_reported(monkeypatch):
    async def scenario(complete, info=lambda: INFO):
        emitted, failures = [], []
        async def emit(*args):
            emitted.append(args)
        async def failed(exc):
            failures.append(exc)
        monkeypatch.setattr(llm, "complete", complete)
        w = watcher(emit, info=info)
        w.on_refresh_failed = failed
        w.refresh()
        task = asyncio.create_task(w.run())
        await asyncio.sleep(0.2)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return emitted, failures

    async def failing(*args, **kwargs):
        raise LLMError("synthetic")
    emitted, failures = asyncio.run(scenario(failing))
    assert emitted == [] and len(failures) == 1 and isinstance(failures[0], LLMError)

    async def answering(*args, **kwargs):
        return LLMResponse(PLANS, [], "r1", False)
    emitted, failures = asyncio.run(scenario(answering))
    assert len(emitted) == 1 and failures == []

    # The window changed while the model ran: the stale result is dropped and reported.
    calls = []
    def moving():
        calls.append(1)
        return INFO if len(calls) == 1 else replace(INFO, window_title="Other", window_key="x|Other",
                                                    element_sigs=["AXButton|Other"])
    emitted, failures = asyncio.run(scenario(answering, moving))
    assert emitted == [] and failures == [None]


def test_server_answers_failed_and_too_soon_refreshes(tmp_path, monkeypatch):
    async def failing(*args, **kwargs):
        raise LLMError("synthetic provider detail")
    monkeypatch.setattr(llm, "complete", failing)

    async def run():
        async with running_server(tmp_path, monkeypatch) as (port, sessions):
            async with await connect(port) as client:
                first = await client.send("auto_refresh", {})
                error = await client.next("error", re=first["id"], timeout=5)
                assert error["payload"]["code"] == "llm_failed"
                assert "provider" not in json.dumps(error)
                second = await client.send("auto_refresh", {})  # within the 3 s gap
                error = await client.next("error", re=second["id"])
                assert error["payload"]["code"] == "internal" and "too soon" in error["payload"]["message"]
                assert sessions[0].refresh_request is None
    asyncio.run(run())


def test_server_answers_a_refresh_dropped_for_a_changed_window(tmp_path, monkeypatch):
    async def run():
        async with running_server(tmp_path, monkeypatch) as (port, sessions):
            async with await connect(port) as client:
                session = sessions[0]
                session.watcher.refresh = lambda: True  # keep the real watcher from also answering
                message = await client.send("auto_refresh", {})
                await asyncio.sleep(0.05)
                assert session.refresh_request == message["id"]
                await session.suggestions("other.app|Elsewhere", "Other", [], False)
                error = await client.next("error", re=message["id"])
                assert error["payload"]["code"] == "internal"
                assert session.list_id is None and session.refresh_request is None
    asyncio.run(run())


def test_fake_agent_answers_a_too_soon_refresh_like_the_real_one(monkeypatch):
    import fake_agent
    import wsproto
    from types import SimpleNamespace
    now, messages = [0.0], []
    monkeypatch.setattr(fake_agent, "time", SimpleNamespace(monotonic=lambda: now[0]))
    class Socket:
        async def send(self, raw):
            messages.append(json.loads(raw))
    async def scenario():
        session = fake_agent.Session(Socket(), delay=0, demo_mode=True, quiet=True)
        await session.on_hello({}, wsproto.new_id())
        now[0] = 10
        await session.on_auto_refresh({}, wsproto.new_id())
        too_soon = wsproto.new_id()
        now[0] = 11
        await session.on_auto_refresh({}, too_soon)
        error = [m for m in messages if m["type"] == "error"][-1]
        assert error["re"] == too_soon and error["payload"]["code"] == "internal"
    asyncio.run(scenario())
