"""Loopback WebSocket transport, validation and task lifecycle (spec §4.4)."""
from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import os
import re
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from jsonschema import Draft202012Validator
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from gaze_agent import auto, permissions, planner
from gaze_agent.actions import DesktopActions
from gaze_agent.contracts import LLMError
from gaze_agent.loop import Outcome, TaskLoop, recovery_plans
from gaze_agent.profile import ProfileStore
from gaze_agent.protocol import Plan
from gaze_agent.screen import get_screen
from gaze_agent.screen.ax import window_info
from gaze_agent.screen.shot import look_at_screen
from gaze_agent.tasklog import TaskLog

SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "protocol/messages.schema.json").read_text())
VALIDATORS = {name: Draft202012Validator({"$defs": SCHEMA["$defs"], "$ref": f"#/$defs/{name}"})
              for name in SCHEMA["$defs"]}
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class Session:
    def __init__(self, ws, *, store=None, screen=get_screen, info=window_info, look=look_at_screen,
                 desktop_factory=DesktopActions, watcher_factory=auto.AutoWatcher, loop_factory=TaskLoop,
                 log=None):
        self.ws = ws
        self.store = store or ProfileStore()
        self.screen, self.info, self.look = screen, info, look
        self.desktop_factory, self.loop_factory = desktop_factory, loop_factory
        self.log = log or TaskLog(self.store.directory)
        self.mode = "auto"
        self.ready, self.closed = False, False
        self.list_id, self.plans = None, {}
        self.previous_plan = None
        self.active, self.runner = None, None
        self.terminal = False
        self.background = set()
        self.watcher = watcher_factory(self.suggestions, info, screen, self.store.load_profile)
        self.watcher.set_mode(self.mode)

    async def emit(self, kind, payload, re=None, *, message_id=None):
        if self.closed:
            return None
        VALIDATORS[f"payload_{kind}"].validate(payload)
        message = {"v": 1, "type": kind, "id": message_id or str(uuid.uuid4()), "re": re,
                   "ts": int(time.time() * 1000), "payload": payload}
        await self.ws.send(json.dumps(message, ensure_ascii=False))
        return message["id"]

    async def error(self, code, message, re=None):
        await self.emit("error", {"code": code, "message": message}, re)

    def new_list(self, items):
        items = [p if isinstance(p, Plan) else Plan.model_validate(p, strict=True) for p in items]
        if len({p.id for p in items}) != len(items):
            raise ValueError("Duplicate plan ids")
        self.list_id, self.plans = str(uuid.uuid4()), {p.id: p for p in items}
        return self.list_id, [p.model_dump(mode="json") for p in items]

    async def suggestions(self, window_key, app, items, cached):
        if self.mode != "auto" or self.active or self.closed or not self.ready:
            return
        current = await asyncio.to_thread(self.info)
        if self.mode != "auto" or self.active or self.closed or current.window_key != window_key:
            return
        list_id, items = self.new_list(items)
        await self.emit("suggestions", {"list_id": list_id, "window_key": window_key, "app": app,
                                        "items": items, "cached": cached})

    def spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.background.add(task)
        task.add_done_callback(self.background.discard)
        return task

    async def request(self, message):
        kind, payload, request_id = message["type"], message["payload"], message["id"]
        try:
            if kind == "decode_request":
                sentences = await planner.decode(payload["words"], payload["raw_keys"], payload.get("context"),
                                                  self.store.load_profile())
                await self.emit("decode_result", {"sentences": sentences}, request_id)
            else:
                try:
                    snapshot = await asyncio.to_thread(self.screen)
                except Exception:
                    snapshot = None
                items = await planner.make_plans(payload["text"], self.store.load_profile(), snapshot)
                list_id, items = self.new_list(items)
                await self.emit("plans", {"list_id": list_id, "items": items}, request_id)
        except LLMError:
            await self.error("llm_failed", "The model request failed", request_id)
        except Exception:
            await self.error("internal", "Could not complete the request", request_id)

    async def start(self, payload, request_id):
        if self.active:
            return await self.error("task_busy", "A task is already running", request_id)
        if payload["list_id"] != self.list_id:
            return await self.error("stale_list", "This list has been replaced", request_id)
        plan = self.plans.get(payload["plan_id"])
        if not plan or plan.kind == "other" or plan.id == "recovery:cancel":
            return await self.error("unknown_plan", "This plan is not executable", request_id)
        show_screen = plan.id == "recovery:show_screen"
        if plan.kind == "recovery":
            if plan.id not in {"recovery:retry", "recovery:show_screen"} or self.previous_plan is None:
                return await self.error("unknown_plan", "No previous task to recover", request_id)
            plan = self.previous_plan
        else:
            self.previous_plan = plan
        profile = self.store.load_profile()
        demo_contacts = {}
        if self.store.demo and self.store.demo_profile.exists():
            demo_contacts = json.loads(self.store.demo_profile.read_text()).get("contacts", {})
        self.active = self.loop_factory(task_id=str(uuid.uuid4()), plan=plan, profile=profile, emit=self.emit,
            desktop=self.desktop_factory(profile), get_screen=self.screen, look_at_screen=self.look,
            log=self.log, demo=self.store.demo, demo_contacts=demo_contacts)
        self.terminal = False
        self.watcher.set_task_running(True)
        await self.emit("task_status", {"task_id": self.active.task_id, "state": "running", "step": 0,
                                       "max_steps": 15, "message": "Starting"}, request_id)
        self.runner = asyncio.create_task(self.run_task(self.active, show_screen))

    async def run_task(self, task, show_screen):
        try:
            outcome = await task.run(show_screen=show_screen)
            await self.finish(task, "done" if outcome.ok else "failed", outcome)
        except asyncio.CancelledError:
            # stop()/disconnect owns the terminal sequence.
            raise
        except LLMError:
            await self.error("llm_failed", "The model request failed")
            await self.finish(task, "failed", Outcome(False, "The model request failed", recovery_plans()))
        except Exception:
            await self.finish(task, "failed", Outcome(False, "The task could not finish", recovery_plans()))
        finally:
            task.desktop.release_keys()

    async def finish(self, task, state, outcome):
        if self.active is not task or self.terminal:
            return
        self.terminal = True
        task.cancel()
        self.watcher.set_task_running(False)
        self.log.event(task_id=task.task_id, plan_label=task.plan.label, tool="task", outcome=state)
        task.desktop.release_keys()
        payload = {"task_id": task.task_id, "ok": outcome.ok, "summary": outcome.summary}
        if outcome.recovery:
            payload["list_id"], payload["recovery"] = self.new_list(outcome.recovery)
        try:
            await self.emit("task_status", {"task_id": task.task_id, "state": state, "step": task.step,
                                           "max_steps": 15, "message": outcome.summary})
            await self.emit("task_result", payload)
        finally:
            self.active = None

    async def stop(self, *, disconnected=False):
        task = self.active
        if task is None:
            return
        task.cancel()  # synchronously invalidate pending confirm before any await
        if self.runner:
            self.runner.cancel()
        await self.finish(task, "stopped", Outcome(False, "Stopped", recovery_plans()))

    async def dispatch(self, message):
        kind, p, request_id = message["type"], message["payload"], message["id"]
        if not self.ready:
            if kind != "hello":
                return await self.error("bad_message", "The first message must be hello", request_id)
            await self.emit("hello_ack", {"version": "0.1.0", "demo_mode": self.store.demo,
                "profile": self.store.load_profile(), "settings": self.store.load_settings(),
                "permissions": permissions.check()}, request_id)
            self.ready = True
            self.watcher.set_mode(self.mode)
            self.spawn(self.watcher.run())
        elif kind == "hello":
            await self.error("bad_message", "hello was already received", request_id)
        elif kind == "mode_set":
            self.mode = p["mode"]
            self.watcher.set_mode(self.mode)
        elif kind == "gaze_context":
            self.watcher.on_gaze_context(p["dock_idle"], p["idle_ms"])
        elif kind == "auto_refresh":
            self.watcher.refresh()
        elif kind in {"decode_request", "intent_submit"}:
            self.spawn(self.request(message))
        elif kind == "plan_select":
            await self.start(p, request_id)
        elif kind in {"choice_response", "confirm_response"}:
            if not self.active or not self.active.respond(kind, p["task_id"], message["re"], p):
                await self.error("no_task", "No matching task wait", request_id)
        elif kind == "stop":
            await self.stop()
        elif kind == "profile_get":
            await self.emit("profile_result", {"profile": self.store.load_profile()}, request_id)
        elif kind in {"profile_update", "settings_update"}:
            noun = "profile" if kind == "profile_update" else "settings"
            try:
                saved = getattr(self.store, f"update_{noun}")(p["patch"])
            except ValueError:
                return await self.error("bad_message", "Invalid update; nothing was saved", request_id)
            await self.emit(noun + "_result", {noun: saved}, request_id)
        elif kind == "permissions_check":
            await self.emit("permissions_status", permissions.check(), request_id)
        elif kind == "open_settings_pane":
            await asyncio.to_thread(permissions.open_settings_pane, p["pane"])

    async def receive(self, raw):
        request_id = None
        try:
            message = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
            if isinstance(message, dict) and isinstance(message.get("id"), str) and UUID.fullmatch(message["id"]):
                request_id = message["id"]
            if isinstance(message, dict) and "v" in message and message["v"] != 1:
                await self.error("version_mismatch", "Expected protocol version 1", request_id)
                await self.ws.close(code=4400, reason="version_mismatch")
                return
            VALIDATORS["Envelope"].validate(message)
            if SCHEMA["x-messages"].get(message["type"]) != "o2a":
                raise ValueError("Wrong message direction or type")
            VALIDATORS["payload_" + message["type"]].validate(message["payload"])
        except Exception:
            return await self.error("bad_message", "Invalid protocol message", request_id)
        try:
            await self.dispatch(message)
        except ConnectionClosed:
            raise
        except Exception:
            await self.error("internal", "Could not handle the request", request_id)

    async def run(self):
        try:
            async for raw in self.ws:
                await self.receive(raw)
        except ConnectionClosed:
            pass
        finally:
            self.closed = True
            await self.stop(disconnected=True)
            self.watcher.set_task_running(False)
            for task in self.background:
                task.cancel()
            tasks = list(self.background) + ([self.runner] if self.runner else [])
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)


class AgentServer:
    def __init__(self, token: str, *, session_factory=Session, **session_options):
        if not token:
            raise ValueError("GAZE_TOKEN must be nonempty")
        self.token, self.session_factory, self.options = token, session_factory, session_options

    async def handler(self, ws):
        supplied = parse_qs(urlsplit(ws.request.path).query).get("token", [""])[0]
        if not hmac.compare_digest(supplied, self.token):
            await ws.close(code=4401, reason="unauthorized")
            return
        await self.session_factory(ws, **self.options).run()

    def listen(self, port=0):
        return serve(self.handler, "127.0.0.1", port, max_size=1024 * 1024)


async def run_server():
    token = os.environ.get("GAZE_TOKEN", "")
    port = int(os.environ.get("GAZE_PORT", "0"))
    server = AgentServer(token)
    async with server.listen(port) as listener:
        actual = listener.sockets[0].getsockname()[1]
        print(f"Gaze agent listening on 127.0.0.1:{actual}", flush=True)
        await asyncio.Event().wait()


def main() -> int:
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
