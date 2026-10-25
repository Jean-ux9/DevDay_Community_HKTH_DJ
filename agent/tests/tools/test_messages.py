import asyncio

import pytest

# Test-local bootstrap/doubles only when the separate H1 dependency is absent.
from test_mail import FakeProcess, FakeSpawn, FakeTransport
from gaze_agent.tools.contracts import ActionRequest, PreparedAction
from gaze_agent.tools.messages import MessagesProvider
from gaze_agent.tools.scripts.send_support import ProcessReply, SendProcess


def request(**overrides):
    return ActionRequest("demo-request", "messages.send", {
        "recipient": "+14155550123", "body": "Demo message", **overrides,
    })


def test_prepare_no_send_and_exact_single_destination():
    async def scenario():
        transport = FakeTransport(ProcessReply(0, b'{"status":"sent"}\n'))
        provider = MessagesProvider(transport=transport)
        body = '--file=nope\n$(nope) "hello" \\ 🐈 e\u0301\r\n\n'
        action = await provider.prepare(request(body=body))
        assert transport.calls == []
        assert action.payload == {"recipient": "+14155550123", "body": body}
        with pytest.raises(TypeError):
            action.payload["body"] = "changed"
        assert body not in repr(action)
        result = await provider.execute(action)
        argv, = transport.calls
        assert argv == ("imsg", "send", "--db=/dev/null/gaze-no-history", "--service=imessage",
                        "--no-sms-fallback", "--json", "--to=+14155550123", "--text=" + body)
        assert argv[-1].removeprefix("--text=").encode() == body.encode()
        assert result.status == "completed"
        assert result.code == "provider_acknowledged"
        assert result.receipt is None
    asyncio.run(scenario())


@pytest.mark.parametrize("recipient", ["TeamMessage", "Jane Appleseed", "415-555-0123",
    "a@example.com,b@example.com", "+14155550123;+14155550124", "--chat-id=42",
    "imessage:+14155550123", "a@example.com\n--file=nope", ["+14155550123"],
    "chat1234", "sms;+;chat123", "$(nope)"])
def test_rejects_names_groups_multiple_recipients_and_options(recipient):
    async def scenario():
        transport = FakeTransport()
        with pytest.raises(ValueError):
            await MessagesProvider(transport=transport).prepare(request(recipient=recipient))
        assert transport.calls == []
    asyncio.run(scenario())


@pytest.mark.parametrize("overrides", [{"body": ""}, {"body": "bad\0"},
    {"body": "\ud800"}, {"file": "nope"}, {"chat_id": 42}, {"service": "auto"},
    {"recipient_alias": "TeamMessage"}, {"body": "a" * 32769}])
def test_rejects_invalid_or_extra_arguments(overrides):
    async def scenario():
        transport = FakeTransport()
        with pytest.raises(ValueError):
            await MessagesProvider(transport=transport).prepare(request(**overrides))
        assert transport.calls == []
    asyncio.run(scenario())


def test_email_recipient_is_passed_without_normalization():
    async def scenario():
        transport = FakeTransport(ProcessReply(0, b'{"status":"sent"}'))
        provider = MessagesProvider(transport=transport)
        await provider.execute(await provider.prepare(request(recipient="TeamMessage+demo@example.com")))
        assert "--to=TeamMessage+demo@example.com" in transport.calls[0]
    asyncio.run(scenario())


@pytest.mark.parametrize("output,returncode", [
    (b'{"status":"sent"}', 1), (b'Permission denied PRIVATE', 1),
    (b'No account PRIVATE', 1), (b'{"status":"delivered"}', 0),
    (b'{"status":"sent", "guid":"PRIVATE"}', 0), (b'sent', 0),
    (b'{"status":"sent"}\nPRIVATE', 0), (b'\xff', 0),
])
def test_ambiguous_failures_are_unknown_and_never_retried(output, returncode):
    async def scenario():
        transport = FakeTransport(ProcessReply(returncode, output))
        provider = MessagesProvider(transport=transport)
        result = await provider.execute(await provider.prepare(request()))
        assert (result.status, result.code) == ("unknown", "submission_unknown")
        assert "PRIVATE" not in repr(result)
        assert result.receipt is None
        assert len(transport.calls) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("error,status,code", [
    (FileNotFoundError("PRIVATE"), "failed", "missing_tool"),
    (PermissionError("PRIVATE"), "failed", "tool_permission_denied"),
    (RuntimeError("PRIVATE"), "unknown", "transport_unknown"),
])
def test_missing_tool_and_error_sanitization(error, status, code):
    async def scenario():
        transport = FakeTransport(error=error)
        provider = MessagesProvider(transport=transport)
        result = await provider.execute(await provider.prepare(request()))
        assert (result.status, result.code) == (status, code)
        assert "PRIVATE" not in repr(result)
    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["cancel", "timeout"])
def test_imsg_child_session_cleanup_and_unknown(mode):
    async def scenario():
        process = FakeProcess(data=b"", block=True, running=True)
        spawn = FakeSpawn(process)
        provider = MessagesProvider(transport=SendProcess(
            spawn=spawn, signal_group=spawn.signal, timeout=0.01))
        task = asyncio.create_task(provider.execute(await provider.prepare(request())))
        await spawn.called.wait()
        if mode == "cancel":
            task.cancel()
        result = await asyncio.wait_for(task, 2)
        assert result.status == "unknown"
        assert result.code == ("cancelled_unknown" if mode == "cancel" else "timeout_unknown")
        assert process.reaped >= 1
        assert len(spawn.calls) == 1
        assert len(spawn.signals) == 2
    asyncio.run(scenario())


def test_invalid_prepared_provider_fails_before_dispatch():
    async def scenario():
        transport = FakeTransport()
        provider = MessagesProvider(transport=transport)
        action = await provider.prepare(request())
        invalid = PreparedAction(action.request_id, action.operation, "other", action.payload)
        assert (await provider.execute(invalid)).code == "invalid_action"
        assert transport.calls == []
    asyncio.run(scenario())
