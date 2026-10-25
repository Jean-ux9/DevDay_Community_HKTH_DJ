# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["websockets>=14", "jsonschema>=4.23"]
# ///
"""Run D1-D4 against the real agent, or fake lifecycle/recovery checks.

The default target starts the real Python agent with replay and demo mode enabled.
Use ``--target fake`` for a fully local rehearsal that never touches desktop apps.
The real rehearsal activates apps, reads screens, clicks, types, and automatically
confirms Send actions in D1/D2. D4 stops at BUY without confirming a purchase.
REPLAY=replay still performs desktop actions, but a cache miss fails without
calling OpenAI. Use --target fake for checks without desktop access.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import re
import secrets
import shutil
import socket
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fake_overlay
from gaze_client import GazeClient

ROOT = Path(__file__).resolve().parent.parent
FAKE_AGENT = ROOT / "scripts" / "fake_agent.py"
AGENT_PROJECT = ROOT / "agent"
DEMO_PROFILE = json.loads((ROOT / "fixtures" / "demo_profile.json").read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Demo:
    app: str
    bundle_id: str
    intent: str
    confirmation: str | None


DEMOS = {
    "D1": Demo("Messages", "com.apple.MobileSMS", "Tell Mom I'll be late", "send"),
    "D2": Demo("Mail", "com.apple.mail", "", "send"),
    "D3": Demo("Music", "com.apple.Music", "Play my focus playlist", None),
    "D4": Demo("Safari", "com.apple.Safari", "Tickets for my favorite artist", "buy"),
}
REQUEST_TIMEOUT_S = 120.0  # Screen read + a model request (the wrapper allows 60 s).
TASK_TIMEOUT_S = 100.0     # Server's 90 active seconds + transport/terminal slack.
STOP_TIMEOUT_S = 2.0
FAKE_EXTRA_FLOWS = (
    ("recovery", "recovery"),
    ("stop_during_confirm", "stop_during_confirm"),
    ("stale_list", "stale_list"),
    ("task_busy", "task_busy"),
    ("recovery_show_screen", "recovery_show_screen"),
)


class TaskBudget:
    """One cumulative active-time budget; user waits have no task deadline (§8.4)."""

    def __init__(self, seconds: float, *, clock=time.monotonic):
        self.clock = clock
        self.deadline = clock() + seconds
        self.paused_at = None

    def status(self, state: str) -> None:
        now = self.clock()
        if state == "waiting_user" and self.paused_at is None:
            self.paused_at = now
        elif state == "running" and self.paused_at is not None:
            self.deadline += now - self.paused_at
            self.paused_at = None

    def remaining(self) -> float | None:
        return None if self.paused_at is not None else max(0.0, self.deadline - self.clock())


async def activate_app(app: str) -> None:
    """Human-run helper, invoked under the agent project for its Cocoa dependency."""
    from AppKit import NSWorkspace

    expected = next(d.bundle_id for d in DEMOS.values() if d.app == app)
    proc = await asyncio.create_subprocess_exec("/usr/bin/open", "-a", app)
    if await proc.wait() != 0:
        raise RuntimeError(f"Could not open {app}")
    async with asyncio.timeout(15):
        while True:
            front = NSWorkspace.sharedWorkspace().frontmostApplication()
            if front is not None and front.bundleIdentifier() == expected:
                return
            await asyncio.sleep(0.1)


async def prepare_app(app: str) -> None:
    """Activate and verify each demo app, never used by --target fake."""
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is required to prepare real apps")
    proc = await asyncio.create_subprocess_exec(
        uv, "run", "--project", str(AGENT_PROJECT), "python", str(Path(__file__).resolve()),
        "--prepare-app", app, cwd=ROOT,
    )
    try:
        await asyncio.wait_for(proc.wait(), timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(f"Could not activate/verify {app}; no demo task was sent")
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()


def verify_demo(client: GazeClient) -> None:
    ack = client.hello_ack["payload"]
    if not ack["demo_mode"] or ack["profile"] != DEMO_PROFILE:
        raise RuntimeError("Requires DEMO_MODE=1 and the exact fixtures/demo_profile.json profile; "
                           "no rehearsal task was sent")
    permissions = ack["permissions"]
    if not permissions["accessibility"] or not permissions["screen_recording"]:
        raise RuntimeError("Accessibility and Screen Recording are required; no rehearsal task was sent")


async def reply(client: GazeClient, kind: str, payload: dict, timeout: float) -> dict:
    request = await client.send(kind, payload)
    message = await client.next({"plans", "decode_result", "error"}, re=request["id"], timeout=timeout)
    if message["type"] == "error":
        raise RuntimeError(f"{kind}: {message['payload']['code']}: {message['payload']['message']}")
    return message


async def first_choice(request: dict) -> str:
    # The rehearsal deterministically selects the first offered demo option.
    # Repeated questions are answered separately using their own message ids.
    return request["payload"]["options"][0]["id"]


async def run_selected(client: GazeClient, index: int, demo: Demo, *,
                       choose: Callable[[dict], Awaitable[str | None]] = first_choice,
                       request_timeout: float = REQUEST_TIMEOUT_S,
                       task_timeout: float = TASK_TIMEOUT_S) -> str:
    selection = await client.select(index)
    first = await client.next({"task_status", "error"}, re=selection["id"], timeout=request_timeout)
    if first["type"] == "error":
        raise RuntimeError(first["payload"]["code"])
    if first["payload"]["state"] != "running" or first["payload"]["step"] != 0:
        raise RuntimeError("Missing initial running status at step 0")
    task_id = first["payload"]["task_id"]
    budget = TaskBudget(task_timeout)
    terminals, confirmations, choices = [], [], 0
    stopped_at_buy = False
    try:
        while True:
            message = await client.next(
                {"task_status", "choice_request", "confirm_request", "task_result", "error"},
                task_id=task_id, timeout=budget.remaining(),
            )
            kind, payload = message["type"], message["payload"]
            if kind == "error":
                raise RuntimeError(f"{payload['code']}: {payload['message']}")
            if kind == "task_status":
                budget.status(payload["state"])
                if payload["state"] in {"done", "failed", "stopped"}:
                    terminals.append(payload["state"])
                continue
            if kind == "task_result":
                expected = "stopped" if stopped_at_buy else "done"
                if terminals != [expected] or (not stopped_at_buy and not payload["ok"]):
                    raise RuntimeError(f"Task ended {terminals}: {payload['summary']}")
                if demo.confirmation and demo.confirmation not in confirmations:
                    raise RuntimeError(f"Task ended without the required {demo.confirmation.upper()} gate")
                if demo.confirmation == "buy" and choices == 0:
                    raise RuntimeError("Tickets reached BUY without a date/detail choice")
                if client.invalid:
                    raise RuntimeError("Agent sent invalid protocol messages")
                return (f"{choices} choices; reached BUY and stopped without purchase confirmation"
                        if stopped_at_buy else f"{choices} choices; {len(confirmations)} Send gates; {payload['summary']}")
            if terminals or stopped_at_buy:
                raise RuntimeError("Unexpected user request after task termination/STOP")
            if kind == "choice_request":
                budget.status("waiting_user")
                choice_id = await choose(message)
                await client.send("choice_response", {"task_id": task_id, "choice_id": choice_id}, re=message["id"])
                choices += 1
                continue
            action = payload["action"]
            if action != demo.confirmation:
                raise RuntimeError(f"Unexpected {action.upper()} confirmation; not confirmed")
            confirmations.append(action)
            if action == "buy":
                if not payload["demo_noop"]:
                    raise RuntimeError("BUY is missing the demo no-purchase flag")
                await client.send("stop", {"reason": "user"})
                stopped_at_buy = True
                budget = TaskBudget(STOP_TIMEOUT_S)
            else:
                await client.send("confirm_response", {"task_id": task_id, "confirmed": True}, re=message["id"])
    finally:
        # A timeout, failed assertion, or Ctrl+C must also cancel any active task.
        if client.active_task_id == task_id:
            with contextlib.suppress(Exception):
                await client.send("stop", {"reason": "user"})


async def run_demo(connect, name: str, *, prepare=None, choose=first_choice,
                   request_timeout=REQUEST_TIMEOUT_S, task_timeout=TASK_TIMEOUT_S) -> str:
    demo = DEMOS[name]
    async with await connect() as client:
        verify_demo(client)
        # Pause Auto while arranging the app and generating typed plans.
        await client.send("mode_set", {"mode": "type"})
        if prepare is not None:
            await prepare(demo.app)
        if name == "D2":
            await client.send("mode_set", {"mode": "auto"})
            await client.send("auto_refresh", {})
            suggestion = await client.next("suggestions", timeout=request_timeout)
            payload = suggestion["payload"]
            if (payload["app"].casefold() != demo.app.casefold()
                    or payload["window_key"].partition("|")[0] != demo.bundle_id):
                raise RuntimeError("D2 suggestions are not from Mail; no plan was selected")
            candidates = [i for i, item in enumerate(payload["items"])
                          if item["kind"] == "task" and re.search(
                              r"\b(reply|respond|answer)\b|\bsounds\s+good\b",
                              item["label"] + " " + (item.get("detail") or ""), re.I)]
            if not candidates:
                raise RuntimeError("Mail offered no reply suggestion; no plan was selected")
            index = candidates[0]
        else:
            intent = demo.intent
            if name == "D1":
                decoded = await reply(client, "decode_request", {
                    "words": ["tell", "mom", "i'll", "be"],
                    "raw_keys": [["JKL", "ABC", "TUV", "DEF"]],
                }, request_timeout)
                intent = decoded["payload"]["sentences"][0]
            plans = await reply(client, "intent_submit", {"text": intent}, request_timeout)
            items = plans["payload"]["items"]
            if items[-1]["id"] != "other" or items[-1]["kind"] != "other":
                raise RuntimeError("Plans are missing the final Something else card")
            candidates = [i for i, item in enumerate(items) if item["kind"] == "task"]
            if name == "D4":
                artist = client.hello_ack["payload"]["profile"]["favorites"]["artist"]
                candidates = [i for i in candidates if artist.casefold() in items[i]["label"].casefold()]
            if not candidates:
                raise RuntimeError("No matching executable plan was offered")
            index = candidates[0]
        return await run_selected(client, index, demo, choose=choose,
                                  request_timeout=request_timeout, task_timeout=task_timeout)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def wait_until_listening(proc: asyncio.subprocess.Process, port: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.returncode is not None:
            _, stderr = await proc.communicate()
            details = stderr.decode(errors="replace").strip() if stderr else ""
            raise RuntimeError(f"agent exited with code {proc.returncode}: {details}")
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.close()
            await writer.wait_closed()
            return
        except OSError:
            await asyncio.sleep(0.05)
    proc.terminate()
    await proc.wait()
    raise TimeoutError(f"agent did not listen on its assigned port {port} within {timeout:g}s")


@contextlib.asynccontextmanager
async def target_server(target: str, delay: float) -> AsyncIterator[tuple[int, str]]:
    port = free_port()
    token = secrets.token_hex(32)
    env = {
        **os.environ,
        "GAZE_TOKEN": token,
        "GAZE_PORT": str(port),
        "REPLAY": os.getenv("REPLAY", "replay"),
        "DEMO_MODE": "1",
        "GAZE_AUTO_AMBIENT": "0",
    }
    if target == "fake":
        command = [sys.executable, str(FAKE_AGENT), "--delay", str(delay), "--quiet"]
    else:
        uv = shutil.which("uv")
        if uv is None:
            raise RuntimeError("uv is required to start the real agent")
        command = [uv, "run", "--project", str(AGENT_PROJECT)]
        env_file = ROOT / ".env"
        if env_file.is_file():
            command.extend(["--env-file", str(env_file)])
        command.extend(["python", "-m", "gaze_agent.server"])

    proc = await asyncio.create_subprocess_exec(
        *command,
        cwd=ROOT,
        env=env,
        # Inherit output: undrained pipes can block a long live task, and the
        # human needs the agent's error/usage summaries.
    )
    try:
        await wait_until_listening(proc, port)
        yield port, token
    finally:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except TimeoutError:
                proc.kill()
                await proc.wait()


async def rehearse(target: str, delay: float) -> bool:
    all_ok = True
    async with target_server(target, delay) as (port, token):
        connect = fake_overlay.connector(port, token)
        for label in DEMOS:
            started = time.monotonic()
            try:
                detail = await run_demo(connect, label, prepare=None if target == "fake" else prepare_app)
                status = "PASS"
            except Exception as exc:
                status = "FAIL"
                detail = f"{type(exc).__name__}: {exc}"
                all_ok = False
            print(f"{status}  {label:<22} {time.monotonic() - started:5.2f}s  {detail}", flush=True)
        if target == "fake":
            for label, flow_name in FAKE_EXTRA_FLOWS:
                started = time.monotonic()
                try:
                    detail = await asyncio.wait_for(fake_overlay.FLOWS[flow_name](connect), timeout=45)
                    status = "PASS"
                except Exception as exc:
                    status, detail, all_ok = "FAIL", f"{type(exc).__name__}: {exc}", False
                print(f"{status}  {label:<22} {time.monotonic() - started:5.2f}s  {detail}", flush=True)
    return all_ok


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("real", "fake"), default="real",
                        help="start the real agent (default) or the no-desktop fake")
    parser.add_argument("--delay", type=float, default=0.03,
                        help="step delay for --target fake (default: 0.03 seconds)")
    parser.add_argument("--prepare-app", choices=tuple(d.app for d in DEMOS.values()), help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        if args.prepare_app:
            await activate_app(args.prepare_app)
            return 0
        if args.target == "real":
            print("REAL REHEARSAL: activates apps, reads screens, clicks, types, and automatically "
                  "confirms SEND in D1/D2. D4 stops at BUY. Use demo-only app content. "
                  "Ctrl+C stops the run. REPLAY=replay fails on cache misses without calling OpenAI.", flush=True)
        return 0 if await rehearse(args.target, args.delay) else 1
    except Exception as exc:
        print(f"FAIL  startup                {type(exc).__name__}: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        sys.exit(asyncio.run(main()))
