from __future__ import annotations

import asyncio
import copy
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from gaze_agent import server
from gaze_agent.auto import AutoWatcher
from gaze_agent.contracts import Element, GateDecision, LLMResponse, LookResult, Snapshot, ToolCall, WindowInfo
from gaze_agent.loop import TaskLoop
from gaze_agent.profile import DEFAULT_PROFILE, ProfileStore
from gaze_agent.protocol import Plan

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from gaze_client import GazeClient

SEND = Element("e1", "AXButton", "Send", "", True, (10, 20, 80, 30), "ax")
SNAPSHOT = Snapshot("fixture-snapshot", "Messages", "com.apple.MobileSMS", "Mom", None, SEND, [SEND])
INFO = WindowInfo(SNAPSHOT.bundle_id, SNAPSHOT.app, SNAPSHOT.window_title,
                  SNAPSHOT.bundle_id + "|Mom", ["AXButton|Send"])


def profile():
    value = copy.deepcopy(DEFAULT_PROFILE)
    value.update(name="Sam Rivera", contacts={"Mom": ["+1 555 0100"]})
    value["favorites"].update(artist="Taylor Swift", playlist="Deep Focus")
    return value


def plan(label="Tell Mom I'll be late"):
    return Plan(id="p1", label=label, detail="Demo fixture only", kind="task", risky=False)


async def make_plans(text, profile, snapshot):
    label = "Tell Mom I'll be late" if "mom" in text.lower() else "Play focus playlist"
    return [plan(label), Plan(id="p2", label="Search instead", kind="task", risky=False),
            Plan(id="other", label="Something else", kind="other", risky=False)]


class FakeDesktop:
    def __init__(self, profile=None):
        self.calls = []
        self.cancelled = False
        self.released = False
        self.started = asyncio.Event()
        self.slow = False

    async def run(self, name, args, snapshot):
        self.started.set()
        if self.slow:
            await asyncio.sleep(10)
        assert not self.cancelled
        self.calls.append((name, args))
        return {"ok": True}

    def cancel(self):
        self.cancelled = True

    def release_keys(self):
        self.released = True


class Watcher(AutoWatcher):
    def __init__(self, *args):
        super().__init__(*args)
        self.states = []

    def set_task_running(self, running):
        self.states.append(running)
        super().set_task_running(running)


async def complete(prompt, model, vars, **kwargs):
    await asyncio.sleep(0.04)
    if not kwargs.get("input_items"):
        if "Mom" in vars["plan_label"]:
            calls = [ToolCall("c1", "click_element", {"id": SEND.id, "snapshot_id": SNAPSHOT.snapshot_id})]
        else:
            calls = [ToolCall("c1", "open_app", {"name": "Music"})]
    else:
        calls = [ToolCall("c2", "finish", {"ok": True, "summary": "Completed with fake desktop"})]
    return LLMResponse(None, calls, "fake-response", False)


def gate(action, snapshot):
    required = action.tool == "click_element" or action.model_flag
    return GateDecision(required, "send", "Send to Mom?", ["App: Messages", "Recipient: Mom"], "rule")


async def look(question):
    return LookResult("Fake Messages window showing a draft")


@asynccontextmanager
async def running_server(tmp_path, monkeypatch, *, completion=complete, gate_fn=gate,
                         desktop_factory=FakeDesktop, **loop_options):
    monkeypatch.setattr(server.planner, "make_plans", make_plans)
    store = ProfileStore(tmp_path, demo=False)
    store.update_profile(profile())
    sessions = []

    def loop_factory(**kwargs):
        return TaskLoop(**kwargs, complete=completion, gate=gate_fn, **loop_options)

    def session_factory(ws, **kwargs):
        session = server.Session(ws, **kwargs)
        sessions.append(session)
        return session

    app = server.AgentServer("test-token", session_factory=session_factory, store=store,
        screen=lambda: copy.deepcopy(SNAPSHOT), info=lambda: INFO, look=look,
        desktop_factory=desktop_factory, watcher_factory=Watcher, loop_factory=loop_factory)
    async with app.listen(0) as listener:
        port = listener.sockets[0].getsockname()[1]
        yield port, sessions


async def connect(port):
    client = GazeClient(port, "test-token")
    await client.connect()
    return client


async def select(client, text="tell mom I'll be late"):
    message = await client.send("intent_submit", {"text": text})
    await client.next("plans", re=message["id"])
    selection = await client.select(0)
    first = await client.next("task_status", re=selection["id"])
    return first["payload"]["task_id"]


async def eventually(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.005)
