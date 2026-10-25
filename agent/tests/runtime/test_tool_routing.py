"""Structured routing uses injected providers, never the desktop or an account."""
import asyncio
import copy
import json
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from gaze_agent.contracts import LLMResponse, ToolCall
from gaze_agent.loop import TaskLoop
from gaze_agent.tasklog import TaskLog
from gaze_agent.tools.contracts import ActionRequest, ActionResult, PreparedAction
from gaze_agent.tools.registry import ActionRegistry, default_registry
from tests.runtime.support import FakeDesktop, SNAPSHOT, look, plan, profile


class Provider:
    def __init__(self, status="completed"):
        self.prepared, self.sent = [], []
        self.status = status
        self.account = "fixture-account"
        self.name = "fixture-provider"
        self.error = None
        self.mutate = None

    async def prepare(self, request):
        self.prepared.append(request)
        payload = dict(request.arguments)
        if request.operation.endswith(".send"):
            payload["account"] = self.account
        if self.mutate:
            self.mutate(payload)
        return PreparedAction(request.request_id, request.operation, self.name, payload)

    async def execute(self, action):
        self.sent.append(action)
        if self.error:
            raise self.error
        return ActionResult(self.status, "fixture-private-provider-code", "fixture-private-receipt")


def make_task(tmp_path, *, provider=None, tool="mail_send", emit=None, complete=None, **kwargs):
    async def quiet(*args, **kwargs):
        pass

    def no_native():
        raise AssertionError("Explicit structured action must not read the native screen")

    operation = {"mail_send": "mail.send", "messages_send": "messages.send",
                 "app_open": "app.open", "web_open": "web.open"}[tool]
    task = TaskLoop(task_id="fixture-task", plan=plan(), profile=profile(),
                    emit=emit or quiet, desktop=FakeDesktop(), get_screen=no_native,
                    look_at_screen=look, log=TaskLog(tmp_path),
                    demo_contacts=copy.deepcopy(profile()["contacts"]),
                    action_registry=ActionRegistry({operation: provider} if provider else {}),
                    complete=complete, **kwargs)
    task._started = task.clock()
    return task


def send_call(call_id="send", tool="mail_send"):
    args = {"recipient_alias": "Mom", "body": "Synthetic fixture message"}
    if tool == "mail_send":
        args["subject"] = "Fixture subject"
    return ToolCall(call_id, tool, args)


def test_contracts_copy_freeze_and_hide_sensitive_fields():
    original = {"nested": [{"body": "fixture-private-body"}]}
    request = ActionRequest("id", "mail.send", original)
    action = PreparedAction("id", "mail.send", "mail", original)
    original["nested"][0]["body"] = "mutated"
    assert request.arguments["nested"][0]["body"] == "fixture-private-body"
    with pytest.raises(TypeError):
        action.payload["nested"][0]["body"] = "mutated"
    with pytest.raises(FrozenInstanceError):
        action.operation = "changed"
    assert "fixture-private-body" not in repr(request) + repr(action)
    assert "fixture-private-receipt" not in repr(ActionResult("completed", "accepted", "fixture-private-receipt"))


@pytest.mark.parametrize("tool,args,operation", [
    ("app_open", {"name": "Music"}, "app.open"),
    ("web_open", {"url": "https://example.org/"}, "web.open"),
])
def test_open_routing_without_native_snapshot(tmp_path, tool, args, operation):
    async def run():
        provider = Provider()
        task = make_task(tmp_path, provider=provider, tool=tool)
        result = await task.execute(ToolCall("open", tool, args))
        assert result["ok"] and result["status"] == "completed"
        assert provider.sent[0].operation == operation
        assert dict(provider.sent[0].payload) == args
        assert task.snapshot is None and not task.desktop.calls
        assert "not observed" in result["summary"]
        capabilities = await task.execute(ToolCall("caps", "action_capabilities", {}))
        assert capabilities == {"available": [operation]}
    asyncio.run(run())


def test_missing_provider_is_setup_failure_without_native_fallback(tmp_path):
    async def run():
        task = make_task(tmp_path)
        result = await task.execute(send_call())
        assert result["status"] == "failed" and "setup" in result["summary"]
        assert not task.desktop.calls
    asyncio.run(run())


@pytest.mark.parametrize("status", ["completed", "failed", "unknown", "cancelled"])
def test_loop_generates_honest_redacted_summary_without_native_reads(tmp_path, status):
    async def run():
        provider, events = Provider(status), []
        task = None
        async def emit(kind, payload, **kwargs):
            events.append((kind, payload))
            if kind == "confirm_request":
                task.respond("confirm_response", task.task_id, kwargs["message_id"], {"confirmed": True})
        async def complete(prompt, model, variables, **kwargs):
            assert variables["screen"] == ""
            call = (ToolCall("finish", "finish", {"ok": True, "summary": "Delivered to recipient!"})
                    if kwargs["input_items"] else send_call())
            return LLMResponse(None, [call], None, False)
        task = make_task(tmp_path, provider=provider, emit=emit, complete=complete)
        outcome = await task.run()
        assert outcome.ok is (status == "completed")
        assert "Delivered" not in outcome.summary
        if status == "completed":
            assert "delivery is not verified" in outcome.summary
        assert "fixture-private" not in json.dumps(task.history)
        assert not task.desktop.calls and task.snapshot is None
        logs = "".join(p.read_text() for p in tmp_path.glob("*.jsonl"))
        assert "fixture-private" not in logs and "Synthetic fixture message" not in logs
    asyncio.run(run())


def test_native_element_path_still_requires_screen_and_desktop(tmp_path):
    async def run():
        task = make_task(tmp_path)
        reads = []
        def screen():
            reads.append(True)
            return copy.deepcopy(SNAPSHOT)
        task.get_screen = screen
        result = await task.execute(ToolCall("text", "type_text", {"text": "fixture"}))
        assert result["ok"] and reads == [True]
        assert task.desktop.calls == [("type_text", {"text": "fixture"})]
    asyncio.run(run())


def test_default_composition_is_explicit_and_missing_modules_are_unavailable(monkeypatch):
    import gaze_agent.tools.registry as registry
    def missing(name):
        raise ModuleNotFoundError(name)
    monkeypatch.setattr(registry, "import_module", missing)
    assert default_registry().capabilities() == ()


def test_later_failure_cannot_be_hidden_by_earlier_provider_acknowledgement(tmp_path):
    async def run():
        task = make_task(tmp_path, provider=Provider(), tool="app_open")
        await task.execute(ToolCall("open", "app_open", {"name": "Music"}))
        outcome = await task.execute(ToolCall("finish", "finish", {"ok": False, "summary": "Later step failed"}))
        assert not outcome.ok and "earlier provider request" in outcome.summary
    asyncio.run(run())


def test_native_screen_can_supply_observed_ids_after_structured_open(tmp_path):
    async def run():
        task = make_task(tmp_path, provider=Provider(), tool="app_open")
        task.snapshot = copy.deepcopy(SNAPSHOT)
        await task.execute(ToolCall("open", "app_open", {"name": "Music"}))
        assert task.snapshot is None
        task.get_screen = lambda: copy.deepcopy(SNAPSHOT)
        result = await task.execute(ToolCall("observe", "native_screen", {}))
        assert SNAPSHOT.snapshot_id in result["screen"]
        assert (await task.execute(ToolCall("text", "type_text", {
            "text": "fixture", "id": SNAPSHOT.focused.id, "snapshot_id": SNAPSHOT.snapshot_id})))["ok"]
    asyncio.run(run())


def test_structured_setup_failures_keep_existing_retry_limit(tmp_path):
    async def run():
        async def complete(*args, **kwargs):
            return LLMResponse(None, [send_call()], None, False)
        task = make_task(tmp_path, complete=complete)
        outcome = await task.run()
        assert not outcome.ok and "two retries" in outcome.summary
        assert task.step == 3 and not task.desktop.calls
    asyncio.run(run())


@pytest.mark.parametrize("mode,replay", [("preview", "off"), ("live", "replay"),
                                         ("live", "record"), (None, "off")])
def test_default_transport_requires_explicit_live_mode_and_replay_off(tmp_path, monkeypatch, mode, replay):
    async def run():
        provider = Provider()
        task = make_task(tmp_path, provider=provider, tool="app_open")
        task.action_registry.external = True
        if mode is None:
            monkeypatch.delenv("GAZE_AGENT_MODE", raising=False)
        else:
            monkeypatch.setenv("GAZE_AGENT_MODE", mode)
        monkeypatch.setenv("REPLAY", replay)
        assert not (await task.execute(ToolCall("open", "app_open", {"name": "TextEdit"})))["ok"]
        assert not provider.prepared and not provider.sent
    asyncio.run(run())


def test_composition_requires_trusted_sender_and_pins_messages_to_imessage(monkeypatch):
    import gaze_agent.tools.registry as registry
    constructed = []
    class FakeProvider:
        def __init__(self, **kwargs):
            constructed.append(kwargs)
    monkeypatch.setattr(registry, "import_module", lambda name: SimpleNamespace(
        LaunchProvider=FakeProvider, MailProvider=FakeProvider, MessagesScriptProvider=FakeProvider))
    missing = default_registry()
    assert missing.capabilities() == ("app.open", "messages.send", "web.open")
    assert missing.unavailable["mail.send"] == "trusted_sender_required"
    ready = default_registry(trusted_sender="sam.rivera@example.com")
    assert "mail.send" in ready.capabilities()
    assert ready.accounts == {"mail.send": "sam.rivera@example.com"}
    assert "messages.send" in ready.capabilities() and "messages.send" not in ready.unavailable
    assert {"sender": "sam.rivera@example.com"} in constructed


def test_session_gets_sender_from_selected_persona_without_using_editable_profile(tmp_path, monkeypatch):
    from gaze_agent import server
    captured = []
    class Store:
        demo_config = SimpleNamespace(persona=lambda: {"address": {"email": "sam.rivera@example.com"}})
        def load_profile(self):
            raise AssertionError("Sender must not come from the editable active profile")
    def compose(**kwargs):
        captured.append(kwargs)
        return ActionRegistry()
    monkeypatch.setattr(server, "default_registry", compose)
    server.Session(SimpleNamespace(), store=Store(), log=TaskLog(tmp_path))
    assert captured == [{"trusted_sender": "sam.rivera@example.com"}]


def test_published_h2_provider_routes_through_loop_with_fake_process(tmp_path):
    module = pytest.importorskip("gaze_agent.tools.launch")
    async def run():
        calls = []
        class Process:
            async def wait(self):
                return 0
            def terminate(self):
                raise AssertionError("Successful fixture needs no cleanup")
            kill = terminate
        async def spawn(*argv, **kwargs):
            calls.append(argv)
            return Process()
        provider = module.LaunchProvider(process_transport=spawn)
        task = make_task(tmp_path, provider=provider, tool="app_open")
        result = await task.execute(ToolCall("open", "app_open", {"name": "tExTeDiT"}))
        assert result["ok"] and calls == [("/usr/bin/open", "-b", "com.apple.TextEdit")]
        assert "not observed" in result["summary"] and not task.desktop.calls
    asyncio.run(run())
