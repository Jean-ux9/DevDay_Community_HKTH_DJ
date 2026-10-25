from __future__ import annotations

import asyncio
import copy
import json
import re
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from gaze_agent import llm, server
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
                         desktop_factory=FakeDesktop, plans_fn=make_plans, demo=False,
                         initial_profile=None, screen=None, info=None, **loop_options):
    if plans_fn is not None:
        monkeypatch.setattr(server.planner, "make_plans", plans_fn)
    store = ProfileStore(tmp_path, demo=demo)
    store.update_profile(initial_profile or profile())
    sessions = []

    def loop_factory(**kwargs):
        return TaskLoop(**kwargs, complete=completion, gate=gate_fn, **loop_options)

    def session_factory(ws, **kwargs):
        session = server.Session(ws, **kwargs)
        sessions.append(session)
        return session

    app = server.AgentServer("test-token", session_factory=session_factory, store=store,
        screen=screen or (lambda: copy.deepcopy(SNAPSHOT)), info=info or (lambda: INFO), look=look,
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


class DemoHarness:
    """D1-D4 desktop/model fixtures; the real planner, Auto, gate and loop run unchanged."""

    APPS = {"Messages": ("com.apple.MobileSMS", "Mom"), "Mail": ("com.apple.mail", "Alex — Lunch"),
            "Music": ("com.apple.Music", "Deep Focus"), "Safari": ("com.apple.Safari", "Taylor Swift tickets")}
    LABELS = {"D1": "Notify Mom of the delay", "D2": "Send a short answer",
              "D3": "Start Deep Focus", "D4": "Find Taylor Swift on Ticketmaster"}

    def __init__(self):
        self.app = "Safari"
        self.revision = 0
        self.prepared, self.actions, self.clients, self.prompts = [], [], [], []
        self.desktops = []
        self.demo_profile = json.loads((ROOT / "fixtures/demo_profile.json").read_text())

    async def prepare(self, app):
        self.prepared.append(app)
        self.app = app
        self.revision += 1

    def snapshot(self):
        bundle, title = self.APPS[self.app]
        field = Element("draft", "AXTextArea", "Compose", "Demo draft", True, (0, 0, 100, 50), "ax")
        labels = {"Messages": [("send", "Send")], "Mail": [("reply", "Reply"), ("send", "Send")],
                  "Music": [("play", "Play")], "Safari": [("buy", "Buy tickets — $20")]}
        elements = [field] + [Element(id, "AXButton", label, "", True, (0, 60, 100, 30), "ax")
                              for id, label in labels[self.app]]
        return Snapshot(f"demo-{self.revision}", self.app, bundle, title, None, field, elements)

    def info(self):
        screen = self.snapshot()
        return WindowInfo(screen.bundle_id, screen.app, screen.window_title,
                          screen.bundle_id + "|" + screen.window_title,
                          [e.role + "|" + e.label for e in screen.elements])

    def desktop(self, profile):
        harness = self

        class Desktop(FakeDesktop):
            async def run(self, name, args, snapshot):
                result = await super().run(name, args, snapshot)
                harness.actions.append((name, copy.deepcopy(args)))
                if name == "open_app":
                    harness.app = args["name"]
                harness.revision += 1
                return result

        desktop = Desktop(profile)
        self.desktops.append(desktop)
        return desktop

    async def connect(self, port):
        client = await connect(port)
        self.clients.append(client)
        return client

    async def complete(self, prompt, model, vars, **kwargs):
        self.prompts.append(prompt)
        if prompt == "sentence_decode":
            return LLMResponse(json.dumps({"sentences": ["Tell Mom I'll be late"]}), [], None, False)
        if prompt == "plan_intent":
            name = "D1" if "mom" in vars["intent"].lower() else "D4" if "ticket" in vars["intent"].lower() else "D3"
            assert f"app {dict(D1='Messages', D3='Music', D4='Safari')[name]}" in vars["app_context"]
            # D4 labels must show the favorite artist and site; the planner no longer relabels them.
            other = "Search Ticketmaster for Taylor Swift" if name == "D4" else "Show other options"
            items = [{"label": self.LABELS[name]}, {"label": other}]
            return LLMResponse(json.dumps({"plans": items}), [], None, False)
        if prompt == "auto_suggest":
            assert vars["app"] == "Mail"
            return LLMResponse(json.dumps({"plans": [
                {"label": "Archive this email"},
                {"label": self.LABELS["D2"], "detail": "Respond to Alex with sounds good"},
                {"label": "Read this email"},
            ]}), [], None, False)
        assert prompt == "task_system"
        name = next(key for key, label in self.LABELS.items() if label == vars["plan_label"])
        snapshot_id = re.match(r"snapshot (\S+)", vars["screen"])[1]
        def click(id):
            return "click_element", {"id": id, "snapshot_id": snapshot_id}
        def text(value):
            return "type_text", {"text": value, "id": "draft", "snapshot_id": snapshot_id}
        def choice(question):
            return "ask_user", {"question": question, "options": [
                {"id": "first", "label": "Demo option one"}, {"id": "second", "label": "Demo option two"}]}
        scripts = {
            "D1": [("open_app", {"name": "Messages"}), text("I'll be late."),
                   choice("Which wording?"), click("send")],
            "D2": [click("reply"), text("Sounds good!"), choice("Which closing?"),
                   ("press_keys", {"keys": ["cmd", "shift", "d"]})],
            "D3": [("open_app", {"name": "Music"}), choice("Which playlist version?"), click("play")],
            "D4": [("open_url", {"url": "https://www.ticketmaster.com/search?q=Taylor%20Swift"}),
                   choice("Which date?"), choice("How many tickets?"), text("2"), click("buy")],
        }
        offset = sum(item["type"] == "function_call_output" for item in kwargs["input_items"])
        action, args = scripts[name][offset] if offset < len(scripts[name]) else (
            "finish", {"ok": True, "summary": f"{name} finished on fake desktop"})
        return LLMResponse(None, [ToolCall(f"{name}-{offset}", action, args)], None, False)

    @asynccontextmanager
    async def server(self, tmp_path, monkeypatch, **options):
        monkeypatch.setenv("GAZE_AUTO_AMBIENT", "0")
        monkeypatch.setattr(llm, "complete", self.complete)
        async with running_server(tmp_path, monkeypatch, completion=self.complete, gate_fn=None,
                                  desktop_factory=self.desktop, plans_fn=None, demo=True,
                                  initial_profile=self.demo_profile, screen=self.snapshot, info=self.info,
                                  **options) as result:
            yield result
