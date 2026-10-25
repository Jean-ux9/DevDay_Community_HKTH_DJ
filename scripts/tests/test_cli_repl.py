"""Issue #7 regressions: the REPL command handler and client with in-memory sockets or fake_agent."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import fake_overlay
import pytest
import wsproto
from gaze_client import Closed, GazeClient
from websockets.exceptions import ConnectionClosed, ConnectionClosedError

# Explicit transport injection for the per-instance client below. The shared
# GazeClient.connect prohibition stays installed for every other test/client.
FAKE_AGENT_CONNECT = GazeClient.connect

ITEMS = [{"id": f"p{i}", "label": f"Plan {i}", "kind": "task", "risky": False} for i in (1, 2, 3)] + [
    {"id": "other", "label": "Something else", "kind": "other", "risky": False}]


def a2o(kind: str, payload: dict[str, Any], re: str | None = None) -> dict[str, Any]:
    return wsproto.make(kind, payload, re=re, direction="a2o")


def choice_request(task_id: str) -> dict[str, Any]:
    return a2o("choice_request", {"task_id": task_id, "question": "Which date?",
                                  "options": [{"id": "fri", "label": "Friday"}, {"id": "sat", "label": "Saturday"}]})


def confirm_request(task_id: str) -> dict[str, Any]:
    return a2o("confirm_request", {"task_id": task_id, "action": "send", "title": "Send message?",
                                   "details": ["To: Mom"], "source": "rule", "demo_noop": False})


def status(task_id: str, state: str) -> dict[str, Any]:
    return a2o("task_status", {"task_id": task_id, "state": state, "step": 1, "max_steps": 15, "message": state})


def deliver(client: GazeClient, msg: dict[str, Any]) -> None:
    """What GazeClient._read does with a valid frame, minus the inbox."""
    if client._accept(msg) and client.on_message:
        client.on_message(msg)


def repl_client(on_send=None):
    """A client wired to fake_overlay.show like repl(); its socket yields on every send."""
    state: dict[str, Any] = {}
    client = GazeClient(1234, "test-token", on_message=lambda m: fake_overlay.show(m, state))
    frames: list[dict[str, Any]] = []

    class Socket:
        async def send(self, frame):
            await asyncio.sleep(0)
            msg = json.loads(frame)
            if on_send:
                await on_send(client, msg)
            frames.append(msg)

        async def close(self):
            pass
    client.ws = Socket()
    return client, state, frames


async def fail_send(client, msg):
    raise ConnectionClosedError(None, None)


# ---- in-memory socket ----------------------------------------------------------------------

@pytest.mark.parametrize("answer,first,arriving", [
    ("choose 1", "choice", "choice"), ("choose 1", "choice", "confirm"),
    ("confirm yes", "confirm", "confirm"), ("confirm yes", "confirm", "choice")])
def test_wait_arriving_while_answer_send_yields_is_kept(answer, first, arriving):
    task_id = wsproto.new_id()
    make = {"choice": choice_request, "confirm": confirm_request}
    old, new = make[first](task_id), make[arriving](task_id)

    async def agent_answers_during_send(client, msg):
        deliver(client, status(task_id, "running"))
        deliver(client, status(task_id, "waiting_user"))
        deliver(client, new)
    client, state, frames = repl_client(agent_answers_during_send)
    client.active_task_id = task_id
    deliver(client, old)
    asyncio.run(fake_overlay.command(client, state, answer))
    assert frames[0]["re"] == old["id"]
    assert state[arriving] is new
    assert set(state) == {arriving}


@pytest.mark.parametrize("line,key", [("choose 1", "choice"), ("choose cancel", "choice"),
                                      ("confirm yes", "confirm"), ("confirm no", "confirm")])
def test_failed_answer_send_keeps_the_pending_request(line, key):
    task_id = wsproto.new_id()
    request = choice_request(task_id) if key == "choice" else confirm_request(task_id)
    client, state, frames = repl_client(fail_send)
    client.active_task_id = task_id
    deliver(client, request)
    with pytest.raises(ConnectionClosed):
        asyncio.run(fake_overlay.command(client, state, line))
    assert state[key] is request and frames == []


def test_stop_clears_waits_even_if_its_send_fails():
    task_id = wsproto.new_id()
    client, state, _ = repl_client(fail_send)
    client.active_task_id = task_id
    deliver(client, confirm_request(task_id))
    with pytest.raises(ConnectionClosed):
        asyncio.run(fake_overlay.command(client, state, "stop"))
    assert "confirm" not in state
    with pytest.raises(RuntimeError, match="No pending confirm"):
        asyncio.run(fake_overlay.command(client, state, "confirm yes"))


def test_failed_plan_select_keeps_the_list_and_allows_a_retry():
    client, state, frames = repl_client(fail_send)
    deliver(client, a2o("plans", {"list_id": wsproto.new_id(), "items": ITEMS}))
    with pytest.raises(ConnectionClosed):
        asyncio.run(fake_overlay.command(client, state, "select 1"))
    assert client._pending_select is None and client.list_items == ITEMS and frames == []
    working, _, frames = repl_client()
    client.ws = working.ws
    asyncio.run(fake_overlay.command(client, state, "select 1"))
    assert frames[0]["type"] == "plan_select" and frames[0]["payload"]["plan_id"] == "p1"


@pytest.mark.parametrize("line", ["choose 1", "choose cancel", "confirm yes", "confirm no"])
def test_answer_at_a_plan_list_points_to_select_without_sending(line):
    client, state, frames = repl_client()
    deliver(client, a2o("plans", {"list_id": wsproto.new_id(), "items": ITEMS}))
    with pytest.raises(RuntimeError, match="use select N for plan/recovery cards"):
        asyncio.run(fake_overlay.command(client, state, line))
    assert frames == [] and client.list_items == ITEMS and client._pending_select is None


def test_answer_while_a_task_is_starting_says_to_wait():
    client, state, frames = repl_client()
    deliver(client, a2o("plans", {"list_id": wsproto.new_id(), "items": ITEMS}))
    asyncio.run(fake_overlay.command(client, state, "select 1"))
    with pytest.raises(RuntimeError, match="wait for a request"):
        asyncio.run(fake_overlay.command(client, state, "choose 1"))
    assert len(frames) == 1


def test_answer_for_a_dead_task_is_discarded_without_sending():
    old_task, new_task = wsproto.new_id(), wsproto.new_id()
    client, state, frames = repl_client()
    client.active_task_id = new_task
    state["choice"] = choice_request(old_task)
    with pytest.raises(RuntimeError, match="No pending choice"):
        asyncio.run(fake_overlay.command(client, state, "choose 1"))
    assert "choice" not in state and frames == []


# ---- repl() loop ---------------------------------------------------------------------------

def run_repl(monkeypatch, lines: list[str], *, send=None, closed: bool = False):
    task_id = wsproto.new_id()
    created: list[GazeClient] = []

    class InMemoryClient(GazeClient):
        async def connect(self, hello: bool = True):
            created.append(self)
            fake, _, self.frames = repl_client(send)
            self.ws = fake.ws
            self.active_task_id = task_id
            deliver(self, confirm_request(task_id))
            if closed:
                self.closed = Closed(1006, "")

        async def close(self):
            self.closed_by_repl = True

    feed = iter(lines)
    monkeypatch.setattr(fake_overlay, "GazeClient", InMemoryClient)
    monkeypatch.setattr(fake_overlay, "input", lambda prompt="": next(feed), raising=False)
    asyncio.run(fake_overlay.repl(1234, "test-token"))
    return created[0], created[0].frames


def test_repl_send_failure_exits_cleanly(monkeypatch, capsys):
    client, frames = run_repl(monkeypatch, ["confirm yes", "quit"], send=fail_send)
    assert frames == [] and client.closed_by_repl
    assert "! send failed, connection closed" in capsys.readouterr().out


def test_repl_disconnect_exits_before_sending_a_stale_answer(monkeypatch, capsys):
    client, frames = run_repl(monkeypatch, ["confirm yes", "quit"], closed=True)
    assert frames == [] and client.closed_by_repl
    assert "! connection closed" in capsys.readouterr().out


def test_repl_never_answers_a_confirm_by_itself(monkeypatch):
    _, frames = run_repl(monkeypatch, ["help", "1", "select 1", "quit"])
    assert frames == []


# ---- fake_agent end to end -----------------------------------------------------------------

async def until(predicate, timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


def with_fake_agent(scenario) -> None:
    async def run():
        async with fake_overlay.spawned_agent(delay=0.02) as (port, token):
            expected_url = f"ws://127.0.0.1:{port}/?token={token}"
            active = True

            class SpawnedFakeClient(GazeClient):
                async def connect(self, hello=True):
                    if not active or self.url != expected_url:
                        raise AssertionError("CLI tests may connect only to their active spawned fake agent")
                    return await FAKE_AGENT_CONNECT(self, hello=hello)

            state: dict[str, Any] = {}
            client = SpawnedFakeClient(port, token, on_message=lambda m: fake_overlay.show(m, state))
            try:
                await client.connect()
                await scenario(client, state)
            finally:
                active = False
                await client.close()
    asyncio.run(run())


async def attempt(client: GazeClient, state: dict[str, Any], line: str) -> str | None:
    """Run one REPL line; returns the error message the REPL would print, or None."""
    try:
        await fake_overlay.command(client, state, line)
    except (IndexError, ValueError, RuntimeError) as e:
        return str(e)
    return None


async def show_plans(client: GazeClient, state: dict[str, Any], text: str) -> None:
    assert await attempt(client, state, f"intent {text}") is None
    await client.next("plans", re=client.sent[-1]["id"])


async def start(client: GazeClient, state: dict[str, Any], line: str = "select 1") -> str:
    assert await attempt(client, state, line) is None
    return (await client.next("task_status", re=client.sent[-1]["id"], state="running"))["payload"]["task_id"]


def errors(client: GazeClient) -> list[str]:
    return [m["payload"]["code"] for m in client.inbox + client.dropped if m["type"] == "error"]


def test_fake_agent_recovery_cancel_and_something_else_stay_local():
    async def scenario(c, state):
        await show_plans(c, state, "fail on purpose")
        await c.next("task_result", task_id=await start(c, state), timeout=10)
        assert [i["id"] for i in c.list_items][-1] == "recovery:cancel"
        sent = len(c.sent)
        assert await attempt(c, state, f"select {len(c.list_items)}") is None
        await show_plans(c, state, "play my focus playlist")
        assert c.list_items[-1]["id"] == "other"
        assert await attempt(c, state, f"select {len(c.list_items)}") is None
        await asyncio.sleep(0.2)
        assert [m["type"] for m in c.sent[sent:]] == ["intent_submit"]
        assert c.list_id is None and state == {"intent": "play my focus playlist"}
        assert errors(c) == []
    with_fake_agent(scenario)


def test_fake_agent_invalid_answers_keep_waits_and_stop_wins_at_buy():
    async def scenario(c, state):
        await show_plans(c, state, "tickets for my favorite artist")
        task_id = await start(c, state)
        await until(lambda: "choice" in state)
        choice, sent = state["choice"], len(c.sent)
        for line in ["choose 0", "choose -1", "choose 99", "choose x", "choose", "select 1", "confirm yes"]:
            assert await attempt(c, state, line), line
            assert state["choice"] is choice, line
        assert len(c.sent) == sent
        assert await attempt(c, state, "choose 2") is None
        await until(lambda: "confirm" in state)
        confirm, sent = state["confirm"], len(c.sent)
        assert confirm["payload"]["action"] == "buy"
        for line in ["confirm maybe", "confirm", "confirm YES", "confirm y", "choose 1", "select 1"]:
            assert await attempt(c, state, line), line
            assert state["confirm"] is confirm, line
        assert len(c.sent) == sent
        await attempt(c, state, "stop")
        assert "confirm" not in state
        await c.next("task_result", task_id=task_id)
        assert not any(m["type"] == "confirm_response" for m in c.sent)
        terminal = [m["payload"]["state"] for m in c.inbox if m["type"] == "task_status"
                    and m["payload"]["task_id"] == task_id and m["payload"]["state"] in {"done", "failed", "stopped"}]
        assert terminal == ["stopped"] and errors(c) == []
    with_fake_agent(scenario)


def test_fake_agent_choose_cancel_and_confirm_no_end_the_task():
    async def scenario(c, state):
        await show_plans(c, state, "tickets for my favorite artist")
        task_id = await start(c, state)
        await until(lambda: "choice" in state)
        assert await attempt(c, state, "choose cancel") is None
        assert not (await c.next("task_result", task_id=task_id))["payload"]["ok"]
        await show_plans(c, state, "tell mom I'll be late")
        task_id = await start(c, state)
        await until(lambda: "confirm" in state)
        assert await attempt(c, state, "confirm no") is None
        assert not (await c.next("task_result", task_id=task_id))["payload"]["ok"]
        assert [m["payload"]["confirmed"] for m in c.sent if m["type"] == "confirm_response"] == [False]
        assert state == {"intent": "tell mom I'll be late"} and errors(c) == []
    with_fake_agent(scenario)


def test_fake_agent_server_errors_stay_visible_and_low_level_select_still_sends(capsys):
    async def scenario(c, state):
        await show_plans(c, state, "fail on purpose")
        await c.next("task_result", task_id=await start(c, state), timeout=10)
        raw = await c.select(len(c.list_items) - 1)  # raw negative test: the server must reject Cancel
        assert (await c.next("error", re=raw["id"]))["payload"]["code"] == "unknown_plan"
        assert c._pending_select is None
        await c.next("task_result", task_id=await start(c, state, "select 2"), timeout=10)  # Show me the screen

        await show_plans(c, state, "tickets for my favorite artist")
        task_id = await start(c, state)
        await until(lambda: "choice" in state)
        busy = await c.select(1)
        assert (await c.next("error", re=busy["id"]))["payload"]["code"] == "task_busy"
        stray = await c.send("confirm_response", {"task_id": task_id, "confirmed": True}, re=state["choice"]["id"])
        assert (await c.next("error", re=stray["id"]))["payload"]["code"] == "no_task"
        assert "choice" in state
        await attempt(c, state, "stop")
        await c.next("task_result", task_id=task_id)
    with_fake_agent(scenario)
    out = capsys.readouterr().out
    assert all(code in out for code in ("unknown_plan", "task_busy", "no_task"))


def test_fake_agent_disconnect_then_reconnect_resets_to_idle():
    async def scenario(c, state):
        await show_plans(c, state, "tell mom I'll be late")
        await start(c, state)
        await until(lambda: "confirm" in state)
        await c.ws.close()
        await until(lambda: c.closed is not None)
        assert c.active_task_id is c.list_id is c._pending_select is None and c.list_items == []
        await c.connect()
        assert state == {"intent": "tell mom I'll be late"}
        assert await attempt(c, state, "confirm yes") is not None
        assert not any(m["type"] == "confirm_response" for m in c.sent)
    with_fake_agent(scenario)


def test_fake_agent_connection_injection_preserves_guard_and_rejects_other_targets(monkeypatch):
    retained = []
    async def scenario(client, state):
        retained.append(client)
        def network_tripwire(*args, **kwargs):
            pytest.fail("Rejected connections must never reach the network")
        monkeypatch.setattr("gaze_client.connect", network_tripwire)
        # The suite guard still applies to ordinary clients, including loopback.
        with pytest.raises(AssertionError, match="inject fake"):
            await GazeClient(1, "synthetic-token").connect()
        original = client.url
        try:
            for url in ("ws://external.invalid:1/", "ws://127.0.0.1:1/?token=synthetic-token",
                        original + "-different-token"):
                client.url = url
                with pytest.raises(AssertionError, match="active spawned fake agent"):
                    await client.connect()
        finally:
            client.url = original
    with_fake_agent(scenario)
    # An escaped client loses its connection capability after helper cleanup.
    with pytest.raises(AssertionError, match="active spawned fake agent"):
        asyncio.run(retained[0].connect())
