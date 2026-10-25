"""H5 demo matrix through the combined runtime: real server, Session composition,
default registry, TaskLoop, safety gate and the published H2/H3 providers.

Only the edges are fake: the model (``llm.complete``), the planner, the desktop,
the launcher's process spawn and Mail's send transport. A temporary private
config is selected; no default profile, .env, history or real account is read.
Scenario ids (S1-S13) match .plans/hackathon-demo-runbook.md.
"""
import asyncio
import copy
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from gaze_agent import demo_config, llm, server
from gaze_agent.contracts import LLMResponse, ToolCall
from gaze_agent.protocol import Plan
from gaze_agent.tools import mail
from gaze_agent.tools.scripts.send_support import UncertainSend
from tests.runtime.support import INFO, SNAPSHOT, FakeDesktop, Watcher, connect, eventually, select
from tests.runtime.test_demo_config import FAKE_PERSONA, select_private

SENDER = FAKE_PERSONA["address"]["email"]
ALEX = FAKE_PERSONA["contacts"]["Alex"][0]
BODY = "Synthetic demo body"
SUBJECT = "Synthetic demo subject"


class FakeMailTransport:
    """Stands in for SendProcess: records argv, never spawns."""

    def __init__(self, behaviour="ack"):
        self.behaviour, self.calls = behaviour, []
        self.started, self.reaped = asyncio.Event(), asyncio.Event()

    async def run(self, argv):
        self.calls.append(tuple(argv))
        self.started.set()
        if self.behaviour == "unknown":
            raise UncertainSend("timeout_unknown")
        if self.behaviour == "hang":
            try:
                await asyncio.Future()
            finally:
                self.reaped.set()
        return SimpleNamespace(returncode=0, stdout=b"GAZE_MAIL_ACK\n")


class Demo:
    def __init__(self, monkeypatch, tmp_path, mail_behaviour="ack"):
        self.mail = FakeMailTransport(mail_behaviour)
        self.spawns, self.desktops, self.scripts = [], [], {}
        persona = copy.deepcopy(FAKE_PERSONA)
        self.config = select_private(monkeypatch, tmp_path, persona=persona,
                                     approved_recipients=persona["contacts"])
        # Default registry composes real providers; only their transports are fake.
        monkeypatch.setattr(mail, "SendProcess", lambda: self.mail)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", self.spawn)
        monkeypatch.setattr(asyncio, "create_subprocess_shell", self.no_shell)
        monkeypatch.setattr(llm, "complete", self.complete)
        monkeypatch.setattr(server.planner, "make_plans", self.make_plans)
        monkeypatch.setenv("GAZE_AGENT_MODE", "live")
        monkeypatch.setenv("REPLAY", "off")
        monkeypatch.setenv("GAZE_AUTO_AMBIENT", "0")

    async def spawn(self, *argv, **kwargs):
        assert argv[0] == "/usr/bin/open", "only the launcher may spawn in this suite"
        self.spawns.append(argv)
        return SimpleNamespace(wait=self._exit0, terminate=lambda: None, kill=lambda: None)

    @staticmethod
    async def _exit0():
        return 0

    async def no_shell(self, *args, **kwargs):
        raise AssertionError("Shell spawning is never allowed")

    async def make_plans(self, text, profile, snapshot):
        return [Plan(id="p1", label=text, kind="task", risky=False),
                Plan(id="p2", label="Search instead", kind="task", risky=False),
                Plan(id="other", label="Something else", kind="other", risky=False)]

    async def complete(self, prompt, model, variables, **kwargs):
        assert prompt == "task_system"
        script = self.scripts[variables["plan_label"]]
        offset = sum(item["type"] == "function_call_output" for item in kwargs["input_items"])
        if offset < len(script):
            name, args = script[offset]
            return LLMResponse(None, [ToolCall(f"c{offset}", name, copy.deepcopy(args))], None, False)
        return LLMResponse(None, [ToolCall("done", "finish", {"ok": True, "summary": "Model says done"})],
                           None, False)

    def desktop(self, profile):
        value = FakeDesktop(profile)
        self.desktops.append(value)
        return value

    @asynccontextmanager
    async def server(self):
        sessions = []

        def session(ws, **kwargs):
            value = server.Session(ws, **kwargs)
            sessions.append(value)
            return value

        # loop_factory stays the real TaskLoop so Session wires registry/approvals/claims.
        app = server.AgentServer("test-token", session_factory=session,
            screen=lambda: copy.deepcopy(SNAPSHOT), info=lambda: INFO,
            look=self.no_look, desktop_factory=self.desktop, watcher_factory=Watcher)
        async with app.listen(0) as listener:
            yield listener.sockets[0].getsockname()[1], sessions

    @staticmethod
    async def no_look(question):
        raise AssertionError("Structured actions must not look at the screen")

    def no_native_actions(self):
        return all(not desktop.calls for desktop in self.desktops)


def mail_call(alias="Alex", **extra):
    return ("mail_send", {"recipient_alias": alias, "subject": SUBJECT, "body": BODY, **extra})


async def run_task(client, label):
    try:
        return await select(client, label)
    except TimeoutError:
        raise AssertionError([m["payload"] for m in client.inbox if m["type"] == "error"]) from None


@pytest.fixture(autouse=True)
def synthetic_configuration_only(monkeypatch, tmp_path):
    monkeypatch.delenv(demo_config.SELECTOR_ENV, raising=False)
    monkeypatch.setattr(demo_config, "USER_DATA_DIR", tmp_path / "unused-user-data")


def assert_no_private_leak(demo, *messages):
    text = json.dumps([m["payload"] for m in messages])
    for path in demo.config.data_dir.rglob("*.jsonl"):
        text += path.read_text()
    assert ALEX not in text and BODY not in text and SENDER not in text


# S1/S2: approved app and https link reach the launcher with an exact argv.
@pytest.mark.parametrize("call,argv", [
    (("app_open", {"name": "textedit"}), ("/usr/bin/open", "-b", "com.apple.TextEdit")),
    (("web_open", {"url": "https://example.org/demo"}), ("/usr/bin/open", "https://example.org/demo")),
])
def test_s1_s2_approved_app_and_link_launch_once_without_confirmation(tmp_path, monkeypatch, call, argv):
    demo = Demo(monkeypatch, tmp_path)
    demo.scripts["open it"] = [call]
    async def run():
        async with demo.server() as (port, _):
            async with await connect(port) as client:
                task_id = await run_task(client, "open it")
                result = await client.next("task_result", task_id=task_id)
                assert result["payload"]["ok"] is True
                assert "not observed" in result["payload"]["summary"]
                assert not [m for m in client.inbox if m["type"] == "confirm_request"]
        assert demo.spawns == [argv] and not demo.mail.calls and demo.no_native_actions()
    asyncio.run(run())


# S3: rejected targets never spawn anything.
@pytest.mark.parametrize("call", [
    ("web_open", {"url": "file:///etc/hosts"}),
    ("web_open", {"url": "javascript:alert(1)"}),
    ("web_open", {"url": "https://user:pw@example.org/"}),
    ("web_open", {"url": "-a Calculator"}),
    ("web_open", {"url": "https://example.org/\x07"}),
    ("app_open", {"name": "Terminal"}),
    ("app_open", {"name": "/bin/sh"}),
])
def test_s3_rejected_link_or_app_spawns_nothing(tmp_path, monkeypatch, call):
    demo = Demo(monkeypatch, tmp_path)
    demo.scripts["open it"] = [call]
    async def run():
        async with demo.server() as (port, _):
            async with await connect(port) as client:
                task_id = await run_task(client, "open it")
                result = await client.next("task_result", task_id=task_id)
                assert result["payload"]["ok"] is False
        assert not demo.spawns and demo.no_native_actions()
    asyncio.run(run())


# S4 + S6: confirmation shows the exact frozen payload; Cancel sends zero, Yes sends it once.
@pytest.mark.parametrize("confirmed", [False, True])
def test_s4_s6_mail_confirmation_cancel_zero_and_confirm_exact_once(tmp_path, monkeypatch, confirmed):
    demo = Demo(monkeypatch, tmp_path)
    demo.scripts["email Alex"] = [mail_call()]
    async def run():
        async with demo.server() as (port, _):
            async with await connect(port) as client:
                task_id = await run_task(client, "email Alex")
                confirm = await client.next("confirm_request", task_id=task_id)
                details = confirm["payload"]["details"]
                assert confirm["payload"]["action"] == "send" and confirm["payload"]["source"] == "rule"
                for line in (f"Recipient: {ALEX}", f"Account: {SENDER}",
                             f"Subject: {SUBJECT}", f"Exact content: {BODY}"):
                    assert line in details
                assert not demo.mail.calls  # nothing dispatched while waiting
                await client.send("confirm_response", {"task_id": task_id, "confirmed": confirmed},
                                  re=confirm["id"])
                result = await client.next("task_result", task_id=task_id)
                assert result["payload"]["ok"] is confirmed
                if confirmed:
                    assert "delivery is not verified" in result["payload"]["summary"]
                assert_no_private_leak(demo, result)
        if confirmed:
            assert len(demo.mail.calls) == 1
            assert demo.mail.calls[0][0] == "/usr/bin/osascript"
            assert demo.mail.calls[0][-4:] == (ALEX, SUBJECT, BODY, SENDER)
        else:
            assert not demo.mail.calls
        assert not demo.spawns and demo.no_native_actions()
    asyncio.run(run())


# S5: aliases outside the selected config, or model-supplied handles/extra fields, never confirm or send.
@pytest.mark.parametrize("call", [
    mail_call(alias="Outside"),
    mail_call(alias="Mom"),  # approved only as a phone number; Mail rejects it before any send
    mail_call(recipient="other@example.invalid"),
    mail_call(cc="other@example.invalid"),
])
def test_s5_unapproved_destination_zero_dispatch(tmp_path, monkeypatch, call):
    demo = Demo(monkeypatch, tmp_path)
    demo.scripts["email someone"] = [call]
    async def run():
        async with demo.server() as (port, _):
            async with await connect(port) as client:
                task_id = await run_task(client, "email someone")
                result = await client.next("task_result", task_id=task_id)
                assert result["payload"]["ok"] is False
                assert not [m for m in client.inbox if m["type"] == "confirm_request"]
        assert not demo.mail.calls and demo.no_native_actions()
    asyncio.run(run())


# S7: the selected destination changes while the confirmation is shown -> old approval revoked.
def test_s7_post_confirm_destination_change_revokes_approval(tmp_path, monkeypatch):
    demo = Demo(monkeypatch, tmp_path)
    demo.scripts["email Alex"] = [mail_call()]
    async def run():
        async with demo.server() as (port, sessions):
            async with await connect(port) as client:
                task_id = await run_task(client, "email Alex")
                confirm = await client.next("confirm_request", task_id=task_id)
                profile_path = demo.config.data_dir / "profile.json"
                stored = json.loads(profile_path.read_text())
                stored["contacts"]["Alex"] = ["changed.rehearsal@example.invalid"]
                profile_path.write_text(json.dumps(stored))
                await client.send("confirm_response", {"task_id": task_id, "confirmed": True}, re=confirm["id"])
                result = await client.next("task_result", task_id=task_id)
                assert result["payload"]["ok"] is False
        assert not demo.mail.calls
    asyncio.run(run())


# S8/S9: STOP or disconnect while the confirmation is pending -> zero dispatch; late Yes is refused.
@pytest.mark.parametrize("how", ["stop", "disconnect"])
def test_s8_s9_stop_or_disconnect_during_confirmation(tmp_path, monkeypatch, how):
    demo = Demo(monkeypatch, tmp_path)
    demo.scripts["email Alex"] = [mail_call()]
    async def run():
        async with demo.server() as (port, sessions):
            async with await connect(port) as client:
                task_id = await run_task(client, "email Alex")
                confirm = await client.next("confirm_request", task_id=task_id)
                if how == "disconnect":
                    await client.close()
                    await eventually(lambda: sessions[0].active is None)
                else:
                    await client.send("stop", {"reason": "user"})
                    assert (await client.next("task_result", task_id=task_id))["payload"]["ok"] is False
                    late = await client.send("confirm_response", {"task_id": task_id, "confirmed": True},
                                             re=confirm["id"])
                    await eventually(lambda: any(m["type"] == "error" and m["re"] == late["id"]
                                                 for m in client.dropped))
                await asyncio.sleep(0.05)
        assert not demo.mail.calls and demo.no_native_actions()
    asyncio.run(run())


# S10: the model repeats the identical send (same or new call id) -> one dispatch only.
def test_s10_repeated_send_dispatches_once(tmp_path, monkeypatch):
    demo = Demo(monkeypatch, tmp_path)
    demo.scripts["email Alex"] = [mail_call(), mail_call(), mail_call()]
    async def run():
        async with demo.server() as (port, _):
            async with await connect(port) as client:
                task_id = await run_task(client, "email Alex")
                confirm = await client.next("confirm_request", task_id=task_id)
                await client.send("confirm_response", {"task_id": task_id, "confirmed": True}, re=confirm["id"])
                result = await client.next("task_result", task_id=task_id)
                assert result["payload"]["ok"] is True
                assert len([m for m in client.inbox if m["type"] == "confirm_request"]) == 0
        assert len(demo.mail.calls) == 1
    asyncio.run(run())


# S11: uncertain submission is reported as unknown and never retried, even if the model retries.
def test_s11_unknown_send_is_not_retried(tmp_path, monkeypatch):
    demo = Demo(monkeypatch, tmp_path, mail_behaviour="unknown")
    altered = mail_call()
    altered[1]["body"] = "Retry with other words"
    demo.scripts["email Alex"] = [mail_call(), mail_call(), altered, ("app_open", {"name": "Mail"})]
    async def run():
        async with demo.server() as (port, _):
            async with await connect(port) as client:
                task_id = await run_task(client, "email Alex")
                confirm = await client.next("confirm_request", task_id=task_id)
                await client.send("confirm_response", {"task_id": task_id, "confirmed": True}, re=confirm["id"])
                result = await client.next("task_result", task_id=task_id)
                assert result["payload"]["ok"] is False
                assert "unknown" in result["payload"]["summary"]
                assert not result["payload"].get("recovery")
                assert_no_private_leak(demo, result)
        assert len(demo.mail.calls) == 1 and not demo.spawns
    asyncio.run(run())


# S11b: STOP after the send was handed to the transport -> unknown, transport cancelled, no retry.
def test_s11b_stop_after_dispatch_reports_unknown(tmp_path, monkeypatch):
    demo = Demo(monkeypatch, tmp_path, mail_behaviour="hang")
    demo.scripts["email Alex"] = [mail_call()]
    async def run():
        async with demo.server() as (port, _):
            async with await connect(port) as client:
                task_id = await run_task(client, "email Alex")
                confirm = await client.next("confirm_request", task_id=task_id)
                await client.send("confirm_response", {"task_id": task_id, "confirmed": True}, re=confirm["id"])
                await asyncio.wait_for(demo.mail.started.wait(), 2)
                await client.send("stop", {"reason": "user"})
                result = await client.next("task_result", task_id=task_id)
                assert result["payload"]["ok"] is False and "unknown" in result["payload"]["summary"]
                await asyncio.wait_for(demo.mail.reaped.wait(), 2)
        assert len(demo.mail.calls) == 1
    asyncio.run(run())


# S12: Messages cannot pin an outgoing account in this MVP -> honest failure, no confirm, no spawn.
def test_s12_messages_send_is_unavailable_and_dispatches_nothing(tmp_path, monkeypatch):
    demo = Demo(monkeypatch, tmp_path)
    demo.scripts["text Mom"] = [("messages_send", {"recipient_alias": "Mom", "body": BODY})]
    async def run():
        async with demo.server() as (port, _):
            async with await connect(port) as client:
                task_id = await run_task(client, "text Mom")
                result = await client.next("task_result", task_id=task_id)
                assert result["payload"]["ok"] is False
                assert not [m for m in client.inbox if m["type"] == "confirm_request"]
        assert not demo.spawns and not demo.mail.calls
    asyncio.run(run())


# S13 (setup): replay or a non-live launcher never dispatches the real providers.
@pytest.mark.parametrize("env", [{"REPLAY": "replay"}, {"GAZE_AGENT_MODE": "preview"}])
def test_s13_non_live_or_replay_mode_dispatches_nothing(tmp_path, monkeypatch, env):
    demo = Demo(monkeypatch, tmp_path)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    demo.scripts["open it"] = [("app_open", {"name": "TextEdit"})]
    async def run():
        async with demo.server() as (port, _):
            async with await connect(port) as client:
                task_id = await run_task(client, "open it")
                assert (await client.next("task_result", task_id=task_id))["payload"]["ok"] is False
        assert not demo.spawns
    asyncio.run(run())
