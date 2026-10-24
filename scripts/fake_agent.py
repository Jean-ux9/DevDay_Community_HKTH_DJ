# /// script
# requires-python = ">=3.12"
# dependencies = ["websockets>=14", "jsonschema>=4.23"]
# ///
"""Mock agent: a scripted WebSocket server that speaks the real protocol (spec §4, §4.4)
and answers with fake suggestions, plans, choices and confirms for demos D1-D4.

No OpenAI, no macOS access. Every message in and out is validated against
protocol/messages.schema.json.

    GAZE_TOKEN=dev-token GAZE_PORT=8765 uv run scripts/fake_agent.py [--delay 0.6] [--quiet]
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import copy
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlsplit

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

import wsproto
from wsproto import ProtocolError

APP_VERSION = "0.1.0-fake"
MAX_STEPS = 15

DEMO_PROFILE: dict[str, Any] = {
    "name": "Sam Rivera",
    "favorites": {"artist": "Taylor Swift", "playlist": "Deep Focus", "sites": ["ticketmaster.com"]},
    "contacts": {"Mom": ["+1 555 0100"], "Alex": ["alex@example.com"]},
    "style": {"tone": "casual", "signature": "– Sam", "phrases": ["on my way", "sounds good", "running late"]},
    "address": {"full_name": "Sam Rivera", "city": "Springfield", "email": "sam@example.com"},
}
DEFAULT_SETTINGS: dict[str, Any] = {
    "dwellMs": 800, "blinkSelect": False, "density": "large", "gazeSource": "webgazer", "calibrationMode": "gaze",
}


# ---- scripted plans -------------------------------------------------------------------------

@dataclass(frozen=True)
class Step:
    kind: str  # status | choice | confirm | done | fail | look
    text: str = ""
    action: str = ""            # confirm: send | buy | ...
    details: tuple[str, ...] = ()
    options: tuple[tuple[str, str], ...] = ()  # choice: (id, label)


@dataclass(frozen=True)
class FakePlan:
    key: str
    label: str
    risky: bool
    steps: tuple[Step, ...]
    detail: str | None = None
    retry_key: str | None = None  # plan to run on recovery:retry (defaults to itself)

    def to_wire(self, plan_id: str) -> dict[str, Any]:
        wire = {"id": plan_id, "label": self.label, "kind": "task", "risky": self.risky}
        if self.detail:
            wire["detail"] = self.detail
        return wire


S = Step
CATALOG: dict[str, FakePlan] = {p.key: p for p in [
    FakePlan("d1_text_mom", "Text Mom: I'll be late", True, detail="Messages → Mom (+1 555 0100)", steps=(
        S("status", "Opening Messages…"), S("status", "Finding Mom…"), S("status", "Typing your message…"),
        S("confirm", "Send message to Mom?", "send", ("To: Mom (+1 555 0100)", "Text: I'll be late, sorry!")),
        S("status", "Sending…"), S("done", "Sent to Mom: “I'll be late, sorry!”"))),
    FakePlan("d1_call_mom", "FaceTime Mom", False, steps=(
        S("status", "Opening FaceTime…"), S("status", "Calling Mom…"), S("done", "Calling Mom on FaceTime."))),
    FakePlan("d2_reply_good", "Reply: sounds good", True, detail="Mail → Alex, “Lunch Friday?”", steps=(
        S("status", "Opening the latest email…"), S("status", "Writing the reply…"),
        S("confirm", "Send reply to Alex?", "send", ("To: alex@example.com", "Subject: Re: Lunch Friday?",
                                                     "Text: Sounds good! – Sam")),
        S("status", "Sending…"), S("done", "Replied to Alex: “Sounds good!”"))),
    FakePlan("d2_archive", "Archive this email", False, steps=(
        S("status", "Archiving…"), S("done", "Archived “Lunch Friday?”."))),
    FakePlan("d2_remind", "Remind me about this tomorrow", False, steps=(
        S("status", "Opening Reminders…"), S("status", "Adding reminder…"), S("done", "Reminder set for tomorrow 9:00."))),
    FakePlan("d3_playlist", "Play Deep Focus in Music", False, steps=(
        S("status", "Opening Music…"), S("status", "Finding “Deep Focus”…"), S("status", "Starting playback…"),
        S("done", "Playing Deep Focus."))),
    FakePlan("d3_youtube", "Search YouTube for focus music", False, steps=(
        S("status", "Opening Safari…"), S("status", "Searching YouTube…"), S("done", "YouTube results are open."))),
    FakePlan("d4_tickets", "Get Taylor Swift tickets on Ticketmaster", True, detail="Safari → ticketmaster.com",
             steps=(
        S("status", "Opening Safari…"), S("status", "Searching Ticketmaster…"), S("status", "Reading event dates…"),
        S("choice", "Which date?", options=(("nov13", "Fri, Nov 13"), ("nov14", "Sat, Nov 14"),
                                            ("nov15", "Sun, Nov 15"))),
        S("status", "Selecting 2 tickets…"), S("status", "Going to checkout…"),
        S("confirm", "Buy 2 tickets for Taylor Swift?", "buy",
          ("Event: Taylor Swift – The Eras Tour", "Quantity: 2", "Total: $398.00")),
        S("done", "Order ready at checkout."))),
    FakePlan("d4_dates", "Show Taylor Swift tour dates", False, steps=(
        S("status", "Opening Safari…"), S("status", "Searching tour dates…"), S("done", "Tour dates are open."))),
    FakePlan("x_fail", "Fail on purpose (test recovery)", False, retry_key="x_fail_fixed", steps=(
        S("status", "Opening Mail…"), S("status", "Looking for the Send button…"),
        S("fail", "I couldn't find the Send button."))),
    FakePlan("x_fail_fixed", "Fail on purpose (test recovery)", False, steps=(
        S("status", "Trying again…"), S("done", "Worked on the second try."))),
    FakePlan("recovery_look", "Show me the screen", False, steps=(
        S("status", "Looking at the screen…"),
        S("look", "Mail is open with a draft to Alex. A “Save changes?” dialog is covering the Send button."))),
]}

# intent keyword -> plan keys (first match wins); D1-D4 from the spec plus a recovery test
INTENT_ROUTES: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("fail",), ("x_fail", "d3_youtube")),
    (("mom", "late"), ("d1_text_mom", "d1_call_mom")),
    (("reply", "email", "mail"), ("d2_reply_good", "d2_archive")),
    (("play", "music", "playlist", "youtube", "focus"), ("d3_playlist", "d3_youtube")),
    (("ticket", "concert", "artist"), ("d4_tickets", "d4_dates")),
]

# fake frontmost windows for Auto mode; ↻ Refresh cycles through them
FAKE_WINDOWS: list[tuple[str, str, tuple[str, ...]]] = [
    ("com.apple.mail|Inbox – Lunch Friday?", "Mail", ("d2_reply_good", "d2_archive", "d2_remind")),
    ("com.apple.MobileSMS|Messages – Mom", "Messages", ("d1_text_mom", "d1_call_mom", "d3_playlist")),
    ("com.apple.Safari|Taylor Swift – Wikipedia", "Safari", ("d4_tickets", "d4_dates", "d3_youtube")),
]

OTHER_PLAN = {"id": "other", "label": "Something else", "kind": "other", "risky": False}
RECOVERY_CARDS = {
    "recovery:retry": {"id": "recovery:retry", "label": "Try again", "kind": "recovery", "risky": False},
    "recovery:show_screen": {"id": "recovery:show_screen", "label": "Show me the screen", "kind": "recovery",
                             "risky": False},
    "recovery:cancel": {"id": "recovery:cancel", "label": "Cancel", "kind": "recovery", "risky": False},
}


def generic_plan(text: str) -> FakePlan:
    label = f"Search the web: {text}"
    if len(label) > 40:
        label = label[:39] + "…"
    return FakePlan("generic_search", label, False, steps=(
        S("status", "Opening Safari…"), S("status", "Searching…"), S("done", f"Search results for “{text}”.")))


FAKE_LEXICON = ("late", "soon", "home", "good", "mom", "tell", "be", "on", "my", "way", "sounds", "play", "tickets")


def guess_word(keys: list[str]) -> str:
    """Resolve one unfinished word's key groups (e.g. ["JKL","ABC","TUV","DEF"]) against a tiny lexicon."""
    for word in FAKE_LEXICON:
        if len(word) == len(keys) and all(ch.upper() in group for ch, group in zip(word, keys)):
            return word
    return "".join(group[0].lower() for group in keys)


def fake_decode(words: list[str], raw_keys: list[list[str]], phrases: list[str]) -> list[str]:
    guesses = [guess_word(keys) for keys in raw_keys]
    text = " ".join(words + guesses).strip() or "hello"
    base = text[0].upper() + text[1:]
    candidates = [f"{base}.", f"{base}, sorry!", f"{base} – {phrases[0]}." if phrases else f"{base}!"]
    return list(dict.fromkeys(candidates))[:3]


# ---- per-connection session -----------------------------------------------------------------

@dataclass
class Waiter:
    kind: str  # choice | confirm
    task_id: str
    request_id: str
    future: asyncio.Future
    option_ids: frozenset[str] = frozenset()


@dataclass
class Session:
    ws: ServerConnection
    delay: float
    demo_mode: bool
    quiet: bool
    profile: dict[str, Any] = field(default_factory=lambda: copy.deepcopy(DEMO_PROFILE))
    settings: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_SETTINGS))
    greeted: bool = False
    mode: str = "auto"
    window_idx: int = 0
    seen_windows: set[str] = field(default_factory=set)
    list_id: str | None = None
    list_plans: dict[str, Any] = field(default_factory=dict)  # plan_id -> FakePlan | recovery id str
    task: asyncio.Task | None = None
    task_id: str | None = None
    task_step: int = 0
    retry_plan: FakePlan | None = None  # last real (non-recovery) plan, for recovery:retry
    waiter: Waiter | None = None
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # -- io --
    def log(self, arrow: str, msg: dict[str, Any]) -> None:
        if not self.quiet:
            print(f"{arrow} {wsproto.brief(msg)}", file=sys.stderr, flush=True)

    async def send(self, mtype: str, payload: dict[str, Any], re: str | None = None) -> dict[str, Any]:
        msg = wsproto.make(mtype, payload, re)
        async with self.send_lock:
            await self.ws.send(json.dumps(msg, ensure_ascii=False))
        self.log("→", msg)
        return msg

    async def error(self, code: str, message: str, re: str | None, task_id: str | None = None) -> None:
        payload: dict[str, Any] = {"code": code, "message": message}
        if task_id:
            payload["task_id"] = task_id
        await self.send("error", payload, re)

    def new_list(self, plans: dict[str, Any]) -> str:
        """A new list invalidates every older one (§4.4)."""
        self.list_id = wsproto.new_id()
        self.list_plans = plans
        return self.list_id

    # -- main loop --
    async def run(self) -> None:
        try:
            async for raw in self.ws:
                try:
                    msg = wsproto.parse(raw, "o2a")
                except ProtocolError as e:
                    await self.error(e.code, e.message, e.msg_id)
                    if e.code == "version_mismatch":
                        await self.ws.close(4400, "version mismatch")
                        return
                    continue
                self.log("←", msg)
                await self.handle(msg)
        except ConnectionClosed:
            pass
        finally:
            await self.cancel_task()  # disconnect = stop (§4.4)

    async def handle(self, msg: dict[str, Any]) -> None:
        mtype, p, mid = msg["type"], msg["payload"], msg["id"]
        if not self.greeted and mtype != "hello":
            await self.error("bad_message", "first message must be hello", mid)
            return
        handler = getattr(self, f"on_{mtype}")
        await handler(p, mid)

    # -- handlers (one per o2a type) --
    async def on_hello(self, p: dict[str, Any], mid: str) -> None:
        self.greeted = True
        await self.send("hello_ack", {"version": APP_VERSION, "demo_mode": self.demo_mode, "profile": self.profile,
                                      "settings": self.settings, "permissions": self.permissions()}, mid)
        if self.mode == "auto":
            await self.send_suggestions(advance=False)

    async def on_mode_set(self, p: dict[str, Any], mid: str) -> None:
        self.mode = p["mode"]
        if self.mode == "auto" and self.task is None:
            await self.send_suggestions(advance=False)

    async def on_gaze_context(self, p: dict[str, Any], mid: str) -> None:
        pass  # the real agent uses this as an Auto trigger (§7); the fake ignores it

    async def on_auto_refresh(self, p: dict[str, Any], mid: str) -> None:
        if self.mode == "auto" and self.task is None:
            await self.send_suggestions(advance=True)

    async def on_decode_request(self, p: dict[str, Any], mid: str) -> None:
        await asyncio.sleep(self.delay)
        sentences = fake_decode(p["words"], p["raw_keys"], self.profile["style"]["phrases"])
        await self.send("decode_result", {"sentences": sentences}, mid)

    async def on_intent_submit(self, p: dict[str, Any], mid: str) -> None:
        text = p["text"]
        lowered = text.lower()
        keys = next((keys for words, keys in INTENT_ROUTES if any(w in lowered for w in words)), None)
        fakes = [CATALOG[k] for k in keys] if keys else [generic_plan(text)]
        await asyncio.sleep(self.delay)
        plans = {f"p{i + 1}": fp for i, fp in enumerate(fakes)}
        list_id = self.new_list(plans | {"other": "other"})
        items = [fp.to_wire(pid) for pid, fp in plans.items()] + [OTHER_PLAN]
        await self.send("plans", {"list_id": list_id, "items": items}, mid)

    async def on_plan_select(self, p: dict[str, Any], mid: str) -> None:
        if self.task is not None:
            await self.error("task_busy", "a task is already running", mid, self.task_id)
            return
        if p["list_id"] != self.list_id:
            await self.error("stale_list", "that list is no longer current", mid)
            return
        target = self.list_plans.get(p["plan_id"])
        if target is None or target in ("other", "recovery:cancel"):
            await self.error("unknown_plan", f"plan {p['plan_id']!r} is not selectable here", mid)
            return
        if target == "recovery:retry":
            failed = self.retry_plan
            plan = CATALOG[failed.retry_key] if failed and failed.retry_key else failed
        elif target == "recovery:show_screen":
            plan = CATALOG["recovery_look"]
        else:
            plan = target
        if plan is None:
            await self.error("unknown_plan", "nothing to retry", mid)
            return
        await self.start_task(plan, mid)

    async def on_choice_response(self, p: dict[str, Any], mid: str) -> None:
        w = self.waiter
        if not w or w.kind != "choice" or w.task_id != p["task_id"] or w.future.done():
            await self.error("no_task", "no choice is pending for that task", mid, p["task_id"])
            return
        if p["choice_id"] is not None and p["choice_id"] not in w.option_ids:
            await self.error("bad_message", f"unknown choice_id {p['choice_id']!r}", mid, p["task_id"])
            return
        w.future.set_result(p["choice_id"])

    async def on_confirm_response(self, p: dict[str, Any], mid: str) -> None:
        w = self.waiter
        if not w or w.kind != "confirm" or w.task_id != p["task_id"] or w.future.done():
            await self.error("no_task", "no confirm is pending for that task", mid, p["task_id"])
            return
        w.future.set_result(p["confirmed"])

    async def on_stop(self, p: dict[str, Any], mid: str) -> None:
        if self.task is None:
            return  # no-op when idle (§4.2)
        task_id, step = self.task_id, self.task_step
        await self.cancel_task()
        await self.finish(task_id, step, "stopped", ok=False, summary="Stopped.")

    async def on_profile_get(self, p: dict[str, Any], mid: str) -> None:
        await self.send("profile_result", {"profile": self.profile}, mid)

    async def on_profile_update(self, p: dict[str, Any], mid: str) -> None:
        patched = wsproto.merge_patch(self.profile, p["patch"])
        errors = wsproto.def_errors("Profile", patched)
        if errors:
            await self.error("bad_message", "invalid profile patch: " + "; ".join(errors[:3]), mid)
            return
        self.profile = patched
        await self.send("profile_result", {"profile": self.profile}, mid)

    async def on_settings_update(self, p: dict[str, Any], mid: str) -> None:
        patched = wsproto.merge_patch(self.settings, p["patch"])
        errors = wsproto.def_errors("Settings", patched)
        if errors:
            await self.error("bad_message", "invalid settings patch: " + "; ".join(errors[:3]), mid)
            return
        self.settings = patched
        await self.send("settings_result", {"settings": self.settings}, mid)

    async def on_permissions_check(self, p: dict[str, Any], mid: str) -> None:
        await self.send("permissions_status", self.permissions(), mid)

    async def on_open_settings_pane(self, p: dict[str, Any], mid: str) -> None:
        if not self.quiet:
            print(f"  (fake) would open System Settings → {p['pane']}", file=sys.stderr, flush=True)

    # -- helpers --
    @staticmethod
    def permissions() -> dict[str, Any]:
        return {"accessibility": True, "screen_recording": True, "camera": "unknown"}

    async def send_suggestions(self, advance: bool) -> None:
        if advance:
            self.window_idx = (self.window_idx + 1) % len(FAKE_WINDOWS)
        window_key, app, keys = FAKE_WINDOWS[self.window_idx]
        cached = window_key in self.seen_windows
        self.seen_windows.add(window_key)
        plans = {f"s{i + 1}": CATALOG[k] for i, k in enumerate(keys)}
        list_id = self.new_list(plans)
        items = [fp.to_wire(pid) for pid, fp in plans.items()]
        await self.send("suggestions", {"list_id": list_id, "window_key": window_key, "app": app,
                                        "items": items, "cached": cached})

    async def start_task(self, plan: FakePlan, select_id: str) -> None:
        self.task_id, self.task_step = wsproto.new_id(), 0
        if plan.key != "recovery_look":
            self.retry_plan = plan
        # first reply to plan_select: running, step 0, re = plan_select id (§4.4)
        await self.status("running", f"Starting: {plan.label}", re=select_id)
        self.task = asyncio.create_task(self.run_task(plan, self.task_id))

    async def status(self, state: str, message: str, re: str | None = None) -> None:
        await self.send("task_status", {"task_id": self.task_id, "state": state, "step": self.task_step,
                                        "max_steps": MAX_STEPS, "message": message}, re)

    async def wait_user(self, kind: str, request: dict[str, Any], option_ids: frozenset[str] = frozenset()) -> Any:
        fut = asyncio.get_running_loop().create_future()
        self.waiter = Waiter(kind, self.task_id, request["id"], fut, option_ids)
        try:
            return await fut
        finally:
            self.waiter = None

    async def run_task(self, plan: FakePlan, task_id: str) -> None:
        try:
            for step in plan.steps:
                if step.kind == "status":
                    await asyncio.sleep(self.delay)
                    self.task_step = min(self.task_step + 1, MAX_STEPS)
                    await self.status("running", step.text)
                elif step.kind == "choice":
                    await self.status("waiting_user", step.text)
                    req = await self.send("choice_request", {
                        "task_id": task_id, "question": step.text,
                        "options": [{"id": oid, "label": label} for oid, label in step.options]})
                    choice = await self.wait_user("choice", req, frozenset(oid for oid, _ in step.options))
                    if choice is None:
                        await self.finish(task_id, self.task_step, "stopped", ok=False, summary="Cancelled.")
                        return
                elif step.kind == "confirm":
                    noop = self.demo_mode and step.action == "buy"
                    await self.status("waiting_user", "Waiting for your confirmation…")
                    req = await self.send("confirm_request", {
                        "task_id": task_id, "action": step.action, "title": step.text,
                        "details": list(step.details), "source": "rule", "demo_noop": noop})
                    confirmed = await self.wait_user("confirm", req)
                    if not confirmed:
                        await self.finish(task_id, self.task_step, "stopped", ok=False,
                                          summary="Cancelled. Nothing was done.")
                        return
                    if noop:
                        await self.finish(task_id, self.task_step, "done", ok=True,
                                          summary="DEMO: purchase skipped. " + plan.steps[-1].text)
                        return
                elif step.kind in ("done", "look"):
                    await asyncio.sleep(self.delay)
                    recovery = ["recovery:retry", "recovery:cancel"] if step.kind == "look" else None
                    await self.finish(task_id, self.task_step, "done", ok=True, summary=step.text, recovery=recovery)
                    return
                elif step.kind == "fail":
                    await asyncio.sleep(self.delay)
                    await self.finish(task_id, self.task_step, "failed", ok=False, summary=step.text,
                                      recovery=["recovery:retry", "recovery:show_screen", "recovery:cancel"])
                    return
        finally:
            if self.task is asyncio.current_task():
                self.task = None

    async def finish(self, task_id: str, step: int, state: str, ok: bool, summary: str,
                     recovery: list[str] | None = None) -> None:
        """Exactly one terminal task_status, then task_result (§4.4)."""
        await self.send("task_status", {"task_id": task_id, "state": state, "step": step,
                                        "max_steps": MAX_STEPS, "message": summary})
        result: dict[str, Any] = {"task_id": task_id, "ok": ok, "summary": summary}
        if recovery:
            result["list_id"] = self.new_list({rid: rid for rid in recovery})
            result["recovery"] = [RECOVERY_CARDS[rid] for rid in recovery]
        if self.task is asyncio.current_task():
            self.task = None  # the task is dead before the result goes out, so a fast plan_select isn't busy
        await self.send("task_result", result)

    async def cancel_task(self) -> None:
        task = self.task
        if task is None or task.done():
            self.task = None
            return
        task.cancel()  # stop wins: any pending choice/confirm wait dies with the task
        with contextlib.suppress(asyncio.CancelledError):
            await task
        self.task = None
        self.waiter = None


# ---- server ---------------------------------------------------------------------------------

async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--delay", type=float, default=float(os.environ.get("FAKE_AGENT_DELAY", "0.6")),
                    help="seconds between fake task steps (default 0.6)")
    ap.add_argument("--quiet", action="store_true", help="don't log messages to stderr")
    args = ap.parse_args()

    token = os.environ.get("GAZE_TOKEN") or "dev-token"
    port = int(os.environ.get("GAZE_PORT", "8765"))
    demo_mode = os.environ.get("DEMO_MODE", "1") == "1"

    async def handler(ws: ServerConnection) -> None:
        query = parse_qs(urlsplit(ws.request.path).query)
        if query.get("token", [None])[0] != token:
            await ws.close(4401, "unauthorized")
            return
        await Session(ws, delay=args.delay, demo_mode=demo_mode, quiet=args.quiet).run()

    async with serve(handler, "127.0.0.1", port) as server:
        print(f"fake_agent listening on ws://127.0.0.1:{port}/?token=… (demo_mode={demo_mode})",
              file=sys.stderr, flush=True)
        await server.serve_forever()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
