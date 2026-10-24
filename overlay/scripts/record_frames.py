# /// script
# requires-python = ">=3.12"
# dependencies = ["websockets>=14", "jsonschema>=4.23"]
# ///
"""Records raw WebSocket frames from scripts/fake_agent.py into overlay/src/renderer/ws/fixtures/*.json.

The overlay's ws tests replay these frames, so they exercise the real agent-side wire format.
Talks only to a locally spawned fake agent; it never touches the desktop.

    uv run overlay/scripts/record_frames.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import wsproto  # noqa: E402
from fake_overlay import spawned_agent  # noqa: E402
from websockets.asyncio.client import connect  # noqa: E402

OUT = ROOT / "overlay" / "src" / "renderer" / "ws" / "fixtures"


class Recorder:
    def __init__(self, ws: Any):
        self.ws = ws
        self.frames: list[dict[str, Any]] = []

    async def send(self, mtype: str, payload: dict[str, Any], re: str | None = None) -> dict[str, Any]:
        msg = wsproto.make(mtype, payload, re)
        self.frames.append({"dir": "out", "msg": msg})
        await self.ws.send(json.dumps(msg, ensure_ascii=False))
        return msg

    async def until(self, mtype: str | set[str], timeout: float = 10, **match: Any) -> dict[str, Any]:
        """Record incoming frames until one matches; returns it."""
        wanted = {mtype} if isinstance(mtype, str) else mtype
        while True:
            raw = await asyncio.wait_for(self.ws.recv(), timeout)
            msg = json.loads(raw)
            self.frames.append({"dir": "in", "msg": msg})
            if msg["type"] in wanted and all(msg["payload"].get(k) == v for k, v in match.items()):
                return msg

    async def settle(self, seconds: float = 0.3) -> None:
        """Record whatever else arrives for a moment."""
        try:
            while True:
                raw = await asyncio.wait_for(self.ws.recv(), seconds)
                self.frames.append({"dir": "in", "msg": json.loads(raw)})
        except TimeoutError:
            pass

    def save(self, name: str) -> None:
        out_ids = {f["msg"]["id"]: i for i, f in enumerate(self.frames) if f["dir"] == "out"}
        frames = []
        for f in self.frames:
            frame = dict(f)
            if f["dir"] == "in":
                frame["re_out"] = out_ids.get(f["msg"]["re"])  # which of our messages this answers
            frames.append(frame)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{name}.json").write_text(json.dumps({"flow": name, "frames": frames}, indent=1, ensure_ascii=False) + "\n")
        print(f"recorded {name}: {len(frames)} frames")


async def session(port: int, token: str, name: str, script) -> None:
    async with connect(f"ws://127.0.0.1:{port}/?token={token}") as ws:
        rec = Recorder(ws)
        await rec.send("hello", {"client": "overlay", "version": "0.1.0"})
        await rec.until("hello_ack")
        await script(rec)
        rec.save(name)


async def intent(rec: Recorder, text: str) -> dict[str, Any]:
    await rec.send("intent_submit", {"text": text})
    return await rec.until("plans")


async def run_task(rec: Recorder, plans: dict[str, Any], index: int, *, choose: int = 0, confirm: bool = True) -> dict[str, Any]:
    pl = plans["payload"]
    items = pl["items"] if "items" in pl else pl["recovery"]
    await rec.send("plan_select", {"list_id": pl["list_id"], "plan_id": items[index]["id"]})
    first = await rec.until("task_status", state="running")
    task_id = first["payload"]["task_id"]
    while True:
        m = await rec.until({"choice_request", "confirm_request", "task_result"}, task_id=task_id)
        if m["type"] == "task_result":
            return m
        if m["type"] == "choice_request":
            await rec.send("choice_response", {"task_id": task_id, "choice_id": m["payload"]["options"][choose]["id"]}, re=m["id"])
        else:
            await rec.send("confirm_response", {"task_id": task_id, "confirmed": confirm}, re=m["id"])


async def d1(rec: Recorder) -> None:
    await rec.send("mode_set", {"mode": "type"})
    await rec.send("decode_request", {"words": ["tell", "mom", "i'll", "be"], "raw_keys": [["JKL", "ABC", "TUV", "DEF"]]})
    dec = await rec.until("decode_result")
    plans = await intent(rec, dec["payload"]["sentences"][0])
    await run_task(rec, plans, 0)


async def d2(rec: Recorder) -> None:
    sug = await rec.until("suggestions")
    idx = next(i for i, p in enumerate(sug["payload"]["items"]) if p["label"].startswith("Reply"))
    await run_task(rec, sug, idx)


async def d3(rec: Recorder) -> None:
    await run_task(rec, await intent(rec, "play my focus playlist"), 0)


async def d4(rec: Recorder) -> None:
    await run_task(rec, await intent(rec, "tickets for my favorite artist"), 0, choose=1)


async def recovery(rec: Recorder) -> None:
    plans = await intent(rec, "fail on purpose")
    failed = await run_task(rec, plans, 0)
    seen = await run_task(rec, failed, 1)  # recovery:show_screen
    await run_task(rec, seen, 0)  # recovery:retry


async def stale_list(rec: Recorder) -> None:
    old = await intent(rec, "play my focus playlist")
    await intent(rec, "tell mom I'll be late")
    await rec.send("plan_select", {"list_id": old["payload"]["list_id"], "plan_id": old["payload"]["items"][0]["id"]})
    await rec.until("error", code="stale_list")


async def stop_during_confirm(rec: Recorder) -> None:
    plans = await intent(rec, "tell mom I'll be late")
    await rec.send("plan_select", {"list_id": plans["payload"]["list_id"], "plan_id": plans["payload"]["items"][0]["id"]})
    task_id = (await rec.until("task_status", state="running"))["payload"]["task_id"]
    req = await rec.until("confirm_request", task_id=task_id)
    await rec.send("stop", {"reason": "gaze"})
    await rec.until("task_status", task_id=task_id, state="stopped")
    await rec.until("task_result", task_id=task_id)
    await rec.send("confirm_response", {"task_id": task_id, "confirmed": True}, re=req["id"])
    await rec.until("error", code="no_task")


async def task_busy(rec: Recorder) -> None:
    plans = await intent(rec, "play my focus playlist")
    first = plans["payload"]["items"]
    await rec.send("plan_select", {"list_id": plans["payload"]["list_id"], "plan_id": first[0]["id"]})
    await rec.until("task_status", state="running")
    await rec.send("plan_select", {"list_id": plans["payload"]["list_id"], "plan_id": first[1]["id"]})
    await rec.until("error", code="task_busy")
    await rec.send("stop", {"reason": "user"})
    await rec.settle(0.5)


async def settings(rec: Recorder) -> None:
    await rec.send("settings_update", {"patch": {"dwellMs": 1200}})
    await rec.until("settings_result")
    await rec.send("settings_update", {"patch": {"dwellMs": 50}})
    await rec.until("error", code="bad_message")
    await rec.send("profile_update", {"patch": {"favorites": {"playlist": "Lo-fi"}}})
    await rec.until("profile_result")
    await rec.send("permissions_check", {})
    await rec.until("permissions_status")


FLOWS = {f.__name__: f for f in (d1, d2, d3, d4, recovery, stale_list, stop_during_confirm, task_busy, settings)}


async def main() -> None:
    for name, script in FLOWS.items():
        # One fresh agent per flow, so each recording starts from a clean connection.
        async with spawned_agent(delay=0.05) as (port, token):
            await asyncio.wait_for(session(port, token, name, script), 60)


if __name__ == "__main__":
    asyncio.run(main())
