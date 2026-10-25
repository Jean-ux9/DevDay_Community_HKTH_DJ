"""Deterministic Send gate, immutable approval and exactly one attempted dispatch."""
import asyncio
import copy
import json
from types import SimpleNamespace

import pytest
from jsonschema import ValidationError

from gaze_agent.contracts import ToolCall
from gaze_agent.contracts import LLMResponse
from gaze_agent.tools.registry import ActionRegistry
from gaze_agent.tools.contracts import ActionResult
from tests.runtime.support import connect, eventually, profile, running_server, select
from tests.runtime.test_tool_routing import Provider, make_task, send_call


@pytest.mark.parametrize("tool", ["mail_send", "messages_send"])
@pytest.mark.parametrize("confirmed", [True, False])
def test_exact_confirmation_always_required_and_cancel_zero_send(tmp_path, tool, confirmed):
    async def run():
        provider, confirmations = Provider(), []
        task = None
        async def emit(kind, payload, **kwargs):
            if kind == "confirm_request":
                assert not provider.sent
                confirmations.append(payload)
                assert task.respond("confirm_response", task.task_id, kwargs["message_id"], {"confirmed": confirmed})
        task = make_task(tmp_path, provider=provider, tool=tool, emit=emit)
        result = await task.execute(send_call(tool=tool))
        assert result["status"] == ("completed" if confirmed else "cancelled")
        assert len(provider.sent) == int(confirmed)
        details = confirmations[0]["details"]
        assert confirmations[0]["action"] == "send" and confirmations[0]["source"] == "rule"
        assert "Recipient: +1 555 0100" in details
        assert "Account: fixture-account" in details
        assert "Exact content: Synthetic fixture message" in details
        if tool == "mail_send":
            assert "Subject: Fixture subject" in details
        if not confirmed:
            assert not (await task.execute(ToolCall("native", "open_app", {"name": "Mail"})))["ok"]
            assert not (await task.execute(send_call("new-call", tool)))["ok"]
        assert not task.desktop.calls
    asyncio.run(run())


@pytest.mark.parametrize("change", ["unapproved", "ambiguous", "model_handle", "provider", "cc", "flag"])
def test_unapproved_or_model_override_never_prepares_or_sends(tmp_path, change):
    async def run():
        provider = Provider()
        task = make_task(tmp_path, provider=provider)
        call = send_call()
        if change == "unapproved":
            task.demo_contacts = {}
        elif change == "ambiguous":
            task.profile["contacts"]["Mom"].append("+1 555 0101")
        else:
            key = {"model_handle": "recipient", "provider": "provider", "cc": "cc", "flag": "requires_confirmation"}[change]
            call.args[key] = False if change == "flag" else "unapproved"
        if change in {"unapproved", "ambiguous"}:
            result = await task.execute(call)
            assert not result["ok"]
        else:
            with pytest.raises(ValidationError):
                await task.execute(call)
        assert not provider.prepared and not provider.sent
    asyncio.run(run())


@pytest.mark.parametrize("change", ["body", "subject", "recipient", "approval", "profile_source",
                                     "account", "provider_name", "registry", "prepared_body"])
def test_mutation_during_wait_revokes_confirmation(tmp_path, change):
    async def run():
        provider, replacement = Provider(), Provider()
        task, call = None, send_call()
        current_profile = copy.deepcopy(profile())
        async def emit(kind, payload, **kwargs):
            if kind != "confirm_request":
                return
            if change in {"body", "subject"}:
                call.args[change] = "Changed fixture content"
            elif change == "recipient":
                task.profile["contacts"]["Mom"] = ["+1 555 0101"]
                task.demo_contacts["Mom"].append("+1 555 0101")
            elif change == "approval":
                task.demo_contacts = {}
            elif change == "profile_source":
                current_profile["contacts"] = {}
            elif change == "account":
                provider.account = "changed-account"
            elif change == "provider_name":
                provider.name = "changed-provider"
            elif change == "registry":
                task.action_registry.providers["mail.send"] = replacement
            else:
                provider.mutate = lambda payload: payload.update(body="changed-content")
            task.respond("confirm_response", task.task_id, kwargs["message_id"], {"confirmed": True})
        task = make_task(tmp_path, provider=provider, emit=emit, profile_source=lambda: current_profile)
        result = await task.execute(call)
        assert not result["ok"] and result["status"] == "failed"
        assert not provider.sent and not replacement.sent
    asyncio.run(run())


@pytest.mark.parametrize("phase", ["prepare", "confirm", "reprepare"])
def test_stop_at_each_pre_dispatch_boundary_sends_zero(tmp_path, phase):
    async def run():
        provider, task = Provider(), None
        original = provider.prepare
        async def prepare(request):
            action = await original(request)
            if phase == "prepare" or (phase == "reprepare" and len(provider.prepared) == 2):
                task.cancel()
            return action
        provider.prepare = prepare
        async def emit(kind, payload, **kwargs):
            if kind == "confirm_request":
                if phase == "confirm":
                    task.cancel()
                assert task.respond("confirm_response", task.task_id, kwargs["message_id"], {"confirmed": True}) is (phase != "confirm")
        task = make_task(tmp_path, provider=provider, emit=emit)
        with pytest.raises(asyncio.CancelledError):
            await task.execute(send_call())
        assert not provider.sent
    asyncio.run(run())


@pytest.mark.parametrize("status", ["completed", "unknown", "failed", "cancelled", "exception"])
def test_repeated_calls_and_uncertain_results_never_duplicate_send(tmp_path, status):
    async def run():
        provider = Provider(status if status != "exception" else "completed")
        provider.error = RuntimeError("fixture-private-error-stdout") if status == "exception" else None
        task = None
        async def emit(kind, payload, **kwargs):
            if kind == "confirm_request":
                task.respond("confirm_response", task.task_id, kwargs["message_id"], {"confirmed": True})
        task = make_task(tmp_path, provider=provider, emit=emit)
        first = await task.execute(send_call())
        for call in (send_call(), send_call("new-call")):
            assert not (await task.execute(call))["ok"]
        if status in {"unknown", "exception"}:
            altered = send_call("changed-payload")
            altered.args["body"] = "different fixture content"
            assert not (await task.execute(altered))["ok"]
            assert not (await task.execute(ToolCall("native", "open_app", {"name": "Mail"})))["ok"]
            assert "unknown" in task.structured_outcome.summary
            assert first["status"] == "unknown"
        assert len(provider.sent) == 1 and "fixture-private" not in json.dumps(first)
    asyncio.run(run())


def test_cancel_after_dispatch_is_unknown_and_provider_is_cancelled(tmp_path):
    async def run():
        started, reaped = asyncio.Event(), asyncio.Event()
        provider, task = Provider(), None
        async def execute(action):
            provider.sent.append(action)
            started.set()
            try:
                await asyncio.Future()
            finally:
                reaped.set()
        provider.execute = execute
        async def emit(kind, payload, **kwargs):
            if kind == "confirm_request":
                task.respond("confirm_response", task.task_id, kwargs["message_id"], {"confirmed": True})
        task = make_task(tmp_path, provider=provider, emit=emit)
        running = asyncio.create_task(task.execute(send_call()))
        await started.wait()
        task.cancel()
        assert task.send_uncertain  # synchronous STOP reporting, before task resumes
        with pytest.raises(asyncio.CancelledError):
            await running
        assert reaped.is_set() and len(provider.sent) == 1
        assert not task.structured_outcome.ok and "unknown" in task.structured_outcome.summary
    asyncio.run(run())


@pytest.mark.parametrize("disconnected", [False, True])
def test_socket_stop_or_disconnect_during_confirmation_dispatches_zero(tmp_path, monkeypatch, disconnected):
    async def run():
        provider = Provider()
        async def complete(*args, **kwargs):
            return LLMResponse(None, [send_call()], None, False)
        async with running_server(tmp_path, monkeypatch, completion=complete, demo=True,
                                  action_registry=ActionRegistry({"mail.send": provider})) as (port, sessions):
            async with await connect(port) as client:
                task_id = await select(client)
                confirmation = await client.next("confirm_request")
                task = sessions[0].active
                if disconnected:
                    await client.close()
                    await eventually(lambda: sessions[0].active is None)
                else:
                    await client.send("stop", {"reason": "user"})
                    assert not (await client.next("task_result"))["payload"]["ok"]
                    late = await client.send("confirm_response", {"task_id": task_id, "confirmed": True}, re=confirmation["id"])
                    await eventually(lambda: any(m["type"] == "error" and m["re"] == late["id"]
                        and m["payload"]["code"] == "no_task" for m in client.dropped))
                assert not provider.sent and not task.alive and not task.desktop.calls
                assert sessions[0].watcher.task_running is False
    asyncio.run(run())


def test_concurrent_duplicate_call_is_reserved_before_confirmation(tmp_path):
    async def run():
        provider, task = Provider(), None
        confirming = asyncio.Event()
        async def emit(kind, payload, **kwargs):
            if kind == "confirm_request":
                confirming.set()
        task = make_task(tmp_path, provider=provider, emit=emit)
        first = asyncio.create_task(task.execute(send_call()))
        await confirming.wait()
        duplicate = await task.execute(send_call("new-id"))
        assert duplicate["code"] == "duplicate_request" and not provider.sent
        task.respond("confirm_response", task.task_id, task.pending[1], {"confirmed": True})
        assert (await first)["ok"] and len(provider.sent) == 1
    asyncio.run(run())


@pytest.mark.parametrize("change", ["recipient", "body", "subject", "extra_recipient", "missing_account"])
def test_provider_cannot_rewrite_or_expand_send_payload(tmp_path, change):
    async def run():
        provider = Provider()
        def mutate(payload):
            if change == "missing_account":
                payload.pop("account")
            elif change == "extra_recipient":
                payload["cc"] = "fixture-other"
            else:
                payload[change] = "fixture-other"
        provider.mutate = mutate
        task = make_task(tmp_path, provider=provider)
        assert (await task.execute(send_call()))["status"] == "failed"
        assert not provider.sent
    asyncio.run(run())


def test_demo_structured_checkout_keeps_buy_noop(tmp_path):
    async def run():
        provider, task = Provider(), None
        async def emit(kind, payload, **kwargs):
            if kind == "confirm_request":
                assert payload["action"] == "buy" and payload["demo_noop"]
                task.respond("confirm_response", task.task_id, kwargs["message_id"], {"confirmed": True})
        task = make_task(tmp_path, provider=provider, tool="web_open", emit=emit, demo=True)
        result = await task.execute(ToolCall("checkout", "web_open", {"url": "https://example.org/checkout"}))
        assert result == {"ok": True, "demo_noop": True} and not provider.sent
    asyncio.run(run())


def test_send_timeout_is_unknown_and_has_no_retry_recovery(tmp_path):
    async def run():
        provider, task = Provider(), None
        async def execute(action):
            provider.sent.append(action)
            await asyncio.Future()
        provider.execute = execute
        async def emit(kind, payload, **kwargs):
            if kind == "confirm_request":
                task.respond("confirm_response", task.task_id, kwargs["message_id"], {"confirmed": True})
        async def complete(*args, **kwargs):
            return LLMResponse(None, [send_call()], None, False)
        task = make_task(tmp_path, provider=provider, emit=emit, complete=complete, max_seconds=0.05)
        outcome = await task.run()
        assert not outcome.ok and "unknown" in outcome.summary and outcome.recovery is None
        assert len(provider.sent) == 1
    asyncio.run(run())


@pytest.mark.parametrize("scenario", ["confirmed", "cancelled", "unknown", "sender_changed", "replay_changed"])
def test_published_h3_mail_runs_under_h1_confirmation_with_fake_transport(tmp_path, monkeypatch, scenario):
    module = pytest.importorskip("gaze_agent.tools.mail")
    async def run():
        calls, proposals = [], []
        async def transport_run(argv):
            calls.append(argv)
            return SimpleNamespace(returncode=0, stdout=b"unknown" if scenario == "unknown" else b"GAZE_MAIL_ACK\n")
        sender = "sam.rivera@example.com"
        provider = module.MailProvider(sender=sender, transport=SimpleNamespace(run=transport_run))
        task = None
        async def emit(kind, payload, **kwargs):
            if kind == "confirm_request":
                proposals.append(payload)
                assert not calls and f"Account: {sender}" in payload["details"]
                if scenario == "sender_changed":
                    provider._sender = "other@example.com"
                if scenario == "replay_changed":
                    monkeypatch.setenv("REPLAY", "replay")
                task.respond("confirm_response", task.task_id, kwargs["message_id"],
                             {"confirmed": scenario != "cancelled"})
        monkeypatch.setenv("GAZE_AGENT_MODE", "live")
        task = make_task(tmp_path, provider=provider, emit=emit)
        task.action_registry.accounts["mail.send"] = sender
        task.action_registry.external = True
        task.profile["contacts"] = task.demo_contacts = {"Alex": ["alex.chen@example.com"]}
        call = send_call()
        call.args["recipient_alias"] = "Alex"
        result = await task.execute(call)
        assert proposals and not task.desktop.calls
        if scenario in {"confirmed", "unknown"}:
            assert len(calls) == 1
            assert calls[0][-4:] == ("alex.chen@example.com", "Fixture subject", "Synthetic fixture message", sender)
            assert result["status"] == ("completed" if scenario == "confirmed" else "unknown")
            assert not (await task.execute(call))["ok"] and len(calls) == 1
        else:
            assert not calls and not result["ok"]
    asyncio.run(run())


def test_published_h3_messages_cannot_send_without_a_pinned_account(tmp_path):
    module = pytest.importorskip("gaze_agent.tools.messages")
    async def run():
        calls = []
        async def transport_run(argv):
            calls.append(argv)
            raise AssertionError("Unpinned account must never reach transport")
        provider = module.MessagesProvider(transport=SimpleNamespace(run=transport_run))
        task = make_task(tmp_path, provider=provider, tool="messages_send")
        task.profile["contacts"] = task.demo_contacts = {"Mom": ["+14155550100"]}
        result = await task.execute(send_call(tool="messages_send"))
        assert not result["ok"] and not calls
    asyncio.run(run())
