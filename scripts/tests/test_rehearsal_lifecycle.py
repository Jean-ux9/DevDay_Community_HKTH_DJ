"""Preserve rehearsal's real-risk policy using in-memory task/CLI fakes only."""
import asyncio
from collections import deque
import sys

import pytest

import rehearse


class TaskClient:
    def __init__(self, events):
        self.events = deque([("task_status", {"state": "running", "step": 0}), *events])
        self.active_task_id = None
        self.invalid, self.sent = [], []
        self.serial = 0

    async def select(self, index):
        self.active_task_id = "synthetic-task"
        return await self.send("plan_select", {"index": index})

    async def send(self, kind, payload, **kwargs):
        self.serial += 1
        message = {"id": str(self.serial), "type": kind, "payload": payload, **kwargs}
        self.sent.append(message)
        return message

    async def next(self, *args, **kwargs):
        event = self.events.popleft()
        if isinstance(event, BaseException):
            raise event
        kind, payload = event
        self.serial += 1
        if kind == "task_result":
            self.active_task_id = None
        return {"id": str(self.serial), "type": kind,
                "payload": {"task_id": "synthetic-task", **payload}}


def gate(action, *, demo_noop=False):
    return "confirm_request", {"action": action, "demo_noop": demo_noop}


def terminal(state="done", *, ok=True):
    return [("task_status", {"state": state}), ("task_result", {"ok": ok, "summary": "Synthetic completion"})]


@pytest.mark.parametrize("name", ["D1", "D2"])
def test_send_is_still_automatically_confirmed_for_each_gate(name):
    client = TaskClient([gate("send"), gate("send"), *terminal()])
    detail = asyncio.run(rehearse.run_selected(client, 0, rehearse.DEMOS[name]))
    confirmations = [m for m in client.sent if m["type"] == "confirm_response"]
    assert "2 Send gates" in detail
    assert len(confirmations) == 2 and len({m["re"] for m in confirmations}) == 2
    assert all(m["payload"] == {"task_id": "synthetic-task", "confirmed": True} for m in confirmations)
    assert not any(m["type"] == "stop" for m in client.sent)


def test_buy_requires_demo_noop_and_stops_without_confirmation():
    client = TaskClient([
        ("choice_request", {"options": [{"id": "date-one"}, {"id": "date-two"}]}),
        gate("buy", demo_noop=True), *terminal("stopped", ok=False),
    ])
    detail = asyncio.run(rehearse.run_selected(client, 0, rehearse.DEMOS["D4"]))
    assert "reached BUY and stopped without purchase" in detail
    assert [m["type"] for m in client.sent] == ["plan_select", "choice_response", "stop"]
    assert client.sent[1]["payload"]["choice_id"] == "date-one"
    assert client.sent[1]["re"]


@pytest.mark.parametrize("name,action", [("D1", "delete"), ("D1", "buy"), ("D2", "submit"),
                                         ("D2", "post"), ("D3", "send"), ("D4", "send"), ("D1", "other")])
def test_unexpected_risky_actions_are_never_confirmed_and_active_work_stops(name, action):
    client = TaskClient([gate(action)])
    with pytest.raises(RuntimeError, match="Unexpected"):
        asyncio.run(rehearse.run_selected(client, 0, rehearse.DEMOS[name]))
    assert [m["type"] for m in client.sent] == ["plan_select", "stop"]


def test_buy_without_demo_noop_fails_closed():
    client = TaskClient([gate("buy")])
    with pytest.raises(RuntimeError, match="no-purchase flag"):
        asyncio.run(rehearse.run_selected(client, 0, rehearse.DEMOS["D4"]))
    assert [m["type"] for m in client.sent] == ["plan_select", "stop"]


@pytest.mark.parametrize("error", [TimeoutError(), asyncio.CancelledError()])
def test_timeout_and_cancellation_request_stop_for_active_task(error):
    client = TaskClient([error])
    with pytest.raises(type(error)):
        asyncio.run(rehearse.run_selected(client, 0, rehearse.DEMOS["D3"]))
    assert [m["type"] for m in client.sent] == ["plan_select", "stop"]


def test_cancellation_during_choice_requests_stop():
    client = TaskClient([("choice_request", {"options": [{"id": "one"}, {"id": "two"}]})])
    async def cancelled(request):
        raise asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(rehearse.run_selected(client, 0, rehearse.DEMOS["D3"], choose=cancelled))
    assert [m["type"] for m in client.sent] == ["plan_select", "stop"]


def test_task_budget_is_cumulative_and_excludes_user_waits():
    now = [0.0]
    budget = rehearse.TaskBudget(10, clock=lambda: now[0])
    now[0] = 6
    budget.status("waiting_user")
    now[0] = 100
    assert budget.remaining() is None
    budget.status("running")
    assert budget.remaining() == 4
    now[0] = 103
    budget.status("running")
    assert budget.remaining() == 1


@pytest.mark.parametrize("arguments,target", [([], "real"), (["--target", "real"], "real"),
                                             (["--target", "fake"], "fake")])
def test_cli_defaults_and_real_send_disclosure_with_fake_runner(monkeypatch, capsys, arguments, target):
    calls = []
    async def fake_run(actual_target, delay):
        calls.append((actual_target, delay))
        return True
    monkeypatch.setattr(sys, "argv", ["rehearse.py", *arguments])
    monkeypatch.setattr(rehearse, "rehearse", fake_run)
    assert asyncio.run(rehearse.main()) == 0
    assert calls == [(target, 0.03)]
    output = capsys.readouterr().out
    if target == "real":
        assert "automatically confirms SEND in D1/D2" in output
        assert "D4 stops at BUY" in output
        assert "REPLAY=replay fails on cache misses without calling OpenAI" in output
    else:
        assert output == ""
