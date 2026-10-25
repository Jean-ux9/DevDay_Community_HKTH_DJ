"""Fake-only H3 checks. H1 contracts may be loaded before pytest for integration.

The CURRENT lane agreement permits test doubles while the H1 commit is absent.
This fallback is test-local; production always imports H1's published contracts.
"""
import asyncio
from dataclasses import dataclass, field
import importlib.util
from pathlib import Path
import signal
import sys
from types import MappingProxyType, ModuleType

import pytest


if "gaze_agent.tools.contracts" not in sys.modules and importlib.util.find_spec("gaze_agent.tools.contracts") is None:
    @dataclass(frozen=True)
    class ActionRequest:
        request_id: str
        operation: str
        arguments: object = field(repr=False)

        def __post_init__(self):
            object.__setattr__(self, "arguments", MappingProxyType(dict(self.arguments)))

    @dataclass(frozen=True)
    class PreparedAction:
        request_id: str
        operation: str
        provider: str
        payload: object = field(repr=False)

        def __post_init__(self):
            object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

    @dataclass(frozen=True)
    class ActionResult:
        status: str
        code: str
        receipt: str | None = field(default=None, repr=False)

    contract_double = ModuleType("gaze_agent.tools.contracts")
    for value in (ActionRequest, PreparedAction, ActionResult):
        setattr(contract_double, value.__name__, value)
    sys.modules[contract_double.__name__] = contract_double

from gaze_agent.tools.contracts import ActionRequest, PreparedAction
from gaze_agent.tools.mail import MailProvider
from gaze_agent.tools.scripts.send_support import ProcessReply, SendProcess, UncertainSend


class FakeTransport:
    def __init__(self, reply=None, error=None):
        self.calls = []
        self.reply = reply or ProcessReply(0, b"GAZE_MAIL_ACK\n")
        self.error = error

    async def run(self, argv):
        self.calls.append(argv)
        if self.error:
            raise self.error
        return self.reply


def request(**overrides):
    return ActionRequest("demo-request", "mail.send", {
        "recipient": "teammail@example.com", "subject": "Demo subject",
        "body": "Demo body", **overrides,
    })


def mail(transport):
    return MailProvider(sender="demo-sender@example.com", transport=transport)


def test_prepare_is_immutable_private_and_has_no_process_or_draft_side_effect():
    async def scenario():
        transport = FakeTransport()
        values = {"recipient": "teammail@example.com", "subject": "Subject", "body": "Body"}
        action = await mail(transport).prepare(ActionRequest("r", "mail.send", values))
        values["body"] = "MUTATED"
        assert action.payload["body"] == "Body"
        assert action.payload["sender"] == "demo-sender@example.com"
        with pytest.raises(TypeError):
            action.payload["body"] = "changed"
        assert "teammail" not in repr(action)
        assert "demo-sender" not in repr(action)
        assert transport.calls == []
    asyncio.run(scenario())


def test_exact_utf8_content_is_data_not_script():
    async def scenario():
        transport = FakeTransport()
        provider = mail(transport)
        body = '--file=/tmp/nope\n" & do shell script "nope"\r\n$(nope) `nope` \\ 🐈 e\u0301\n\n'
        subject = '  "Quoted" — café  '
        action = await provider.prepare(request(subject=subject, body=body))
        result = await provider.execute(action)
        assert (result.status, result.code, result.receipt) == ("completed", "provider_acknowledged", None)
        argv, = transport.calls
        assert argv[0] == "/usr/bin/osascript"
        assert argv[1].endswith("/scripts/mail_send.applescript")
        assert argv[2:] == ("teammail@example.com", subject, body, "demo-sender@example.com")
        assert argv[4].encode("utf-8") == body.encode("utf-8")
        assert body not in repr(result)
    asyncio.run(scenario())


@pytest.mark.parametrize("recipient", [
    "TeamMail", "a@example.com,b@example.com", "a@example.com;b@example.com",
    "Name <a@example.com>", "--to=a@example.com", "a@example.com\r\nBcc:b@example.com",
    ["a@example.com"], "$(nope)@example.com", "a@bad..example", "a@-bad.example",
])
def test_rejects_alias_list_header_or_argument_injection(recipient):
    async def scenario():
        transport = FakeTransport()
        with pytest.raises(ValueError):
            await mail(transport).prepare(request(recipient=recipient))
        assert transport.calls == []
    asyncio.run(scenario())


@pytest.mark.parametrize("overrides", [
    {"cc": "other@example.com"}, {"bcc": "other@example.com"}, {"attachments": []},
    {"provider": "other"}, {"subject": "bad\nheader"}, {"body": "nul\0"},
    {"body": "\ud800"}, {"body": "a" * 32769},
])
def test_invalid_payload_has_zero_process_calls(overrides):
    async def scenario():
        transport = FakeTransport()
        with pytest.raises(ValueError):
            await mail(transport).prepare(request(**overrides))
        assert transport.calls == []
    asyncio.run(scenario())


@pytest.mark.parametrize("stdout,returncode,status,code", [
    (b"GAZE_MAIL_NO_ACCOUNT\n", 0, "failed", "missing_account"),
    (b"GAZE_MAIL_PERMISSION\n", 0, "failed", "automation_permission_denied"),
    (b"GAZE_MAIL_PRE_SEND_FAILED\n", 0, "failed", "prepare_failed"),
    (b"GAZE_MAIL_UNKNOWN\n", 0, "unknown", "submission_unknown"),
    (b"GAZE_MAIL_ACK\n", 1, "unknown", "submission_unknown"),
    (b"teammail@example.com PRIVATE BODY", 1, "unknown", "submission_unknown"),
    (b"GAZE_MAIL_ACK\nPRIVATE", 0, "unknown", "submission_unknown"),
])
def test_only_static_phase_markers_establish_outcome(stdout, returncode, status, code):
    async def scenario():
        transport = FakeTransport(ProcessReply(returncode, stdout))
        provider = mail(transport)
        result = await provider.execute(await provider.prepare(request()))
        assert (result.status, result.code) == (status, code)
        assert result.receipt is None
        assert "PRIVATE" not in repr(result)
        assert len(transport.calls) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("error,status,code", [
    (FileNotFoundError("PRIVATE"), "failed", "missing_tool"),
    (PermissionError("PRIVATE"), "failed", "tool_permission_denied"),
    (RuntimeError("PRIVATE"), "unknown", "transport_unknown"),
    (UncertainSend("PRIVATE"), "unknown", "transport_unknown"),
])
def test_transport_failures_are_sanitized_without_retry(error, status, code):
    async def scenario():
        transport = FakeTransport(error=error)
        provider = mail(transport)
        result = await provider.execute(await provider.prepare(request()))
        assert (result.status, result.code) == (status, code)
        assert "PRIVATE" not in repr(result)
        assert len(transport.calls) == 1
    asyncio.run(scenario())


def test_sender_and_provider_changes_fail_before_dispatch():
    async def scenario():
        transport = FakeTransport()
        provider = mail(transport)
        action = await provider.prepare(request())
        for changed in (
            PreparedAction(action.request_id, action.operation, "other", action.payload),
            PreparedAction(action.request_id, action.operation, action.provider,
                           {**action.payload, "sender": "other@example.com"}),
        ):
            assert (await provider.execute(changed)).code == "invalid_action"
        assert transport.calls == []
    asyncio.run(scenario())


def test_static_script_sends_only_the_new_object_and_never_emits_error_text():
    # Static safety inspection; this does not claim AppleScript/native validation.
    script = Path(__file__).parents[2] / "gaze_agent/tools/scripts/mail_send.applescript"
    source = script.read_text()
    assert "set newDraft to make new outgoing message" in source
    assert source.count("send newDraft") == 1
    assert "set dispatchStarted to true" in source
    assert "send newDraft" in source.split("set dispatchStarted to true", 1)[1]
    for forbidden in ("front window", "first outgoing message", "System Events", "activate", "do shell script", "return errorText"):
        assert forbidden not in source


class FakeOutput:
    def __init__(self, data=b"", block=False):
        self.data = data
        self.block = block

    async def read(self, count):
        if self.block:
            await asyncio.Event().wait()
        part, self.data = self.data[:count], self.data[count:]
        return part


class FakeProcess:
    pid = 424242  # Never signalled on the OS; FakeSpawn.signal owns this value.

    def __init__(self, data=b"GAZE_MAIL_ACK\n", block=False, running=False):
        self.stdout = FakeOutput(data, block)
        self.exited = asyncio.Event()
        self.reaped = 0
        if not running:
            self.exited.set()

    async def wait(self):
        await self.exited.wait()
        self.reaped += 1
        return 0


class FakeSpawn:
    def __init__(self, process):
        self.process = process
        self.called = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.calls = []
        self.signals = []

    async def __call__(self, *argv, **kwargs):
        self.calls.append((argv, kwargs))
        self.called.set()
        await self.release.wait()
        return self.process

    def signal(self, pid, sig):
        assert pid == self.process.pid
        self.signals.append(sig)
        if sig == signal.SIGKILL:
            self.process.exited.set()


@pytest.mark.parametrize("mode", ["timeout", "cancel", "overflow", "spawn_cancel"])
def test_owned_child_group_is_killed_and_reaped_on_uncertain_dispatch(mode):
    async def scenario():
        process = FakeProcess(data=b"x" * 1025 if mode == "overflow" else b"",
                              block=mode != "overflow", running=True)
        spawn = FakeSpawn(process)
        if mode == "spawn_cancel":
            spawn.release.clear()
        transport = SendProcess(spawn=spawn, signal_group=spawn.signal, timeout=0.01)
        provider = mail(transport)
        action = await provider.prepare(request())
        task = asyncio.create_task(provider.execute(action))
        await spawn.called.wait()
        if mode in {"cancel", "spawn_cancel"}:
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()  # repeated STOP/disconnect cannot abandon the child
            spawn.release.set()
        result = await asyncio.wait_for(task, 2)
        assert result.status == "unknown"
        assert result.code == {"timeout": "timeout_unknown", "cancel": "cancelled_unknown",
                               "overflow": "output_unknown", "spawn_cancel": "cancelled_unknown"}[mode]
        assert spawn.signals == [signal.SIGTERM, signal.SIGKILL]
        assert process.reaped >= 1
        assert len(spawn.calls) == 1
        _, kwargs = spawn.calls[0]
        assert kwargs["start_new_session"] is True
        assert kwargs["stderr"] == asyncio.subprocess.DEVNULL
        assert kwargs["stdin"] == asyncio.subprocess.DEVNULL
        assert "shell" not in kwargs
    asyncio.run(scenario())


def test_cancel_before_dispatch_creates_no_process():
    async def scenario():
        transport = FakeTransport()
        provider = mail(transport)
        action = await provider.prepare(request())
        task = asyncio.create_task(provider.execute(action))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert transport.calls == []
    asyncio.run(scenario())


def test_runner_success_reaps_without_signalling():
    async def scenario():
        process = FakeProcess()
        spawn = FakeSpawn(process)
        provider = mail(SendProcess(spawn=spawn, signal_group=spawn.signal))
        assert (await provider.execute(await provider.prepare(request()))).status == "completed"
        assert process.reaped == 1
        assert spawn.signals == []
    asyncio.run(scenario())


def test_startup_timeout_does_not_abandon_late_child():
    async def scenario():
        process = FakeProcess(block=True, running=True)
        spawn = FakeSpawn(process)
        spawn.release.clear()
        provider = mail(SendProcess(spawn=spawn, signal_group=spawn.signal, timeout=0.01))
        task = asyncio.create_task(provider.execute(await provider.prepare(request())))
        await spawn.called.wait()
        await asyncio.sleep(0.03)
        spawn.release.set()
        result = await asyncio.wait_for(task, 2)
        assert (result.status, result.code) == ("unknown", "timeout_unknown")
        assert process.reaped >= 1
        assert spawn.signals == [signal.SIGTERM, signal.SIGKILL]
    asyncio.run(scenario())
