# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["websockets>=14", "jsonschema>=4.23"]
# ///
"""Mock overlay: sends fake selections to an agent over the real protocol (spec §4).

Scripted flows (D1-D4, recovery, §4.4 races), printing PASS/FAIL:
    uv run scripts/fake_overlay.py demo --spawn            # starts its own fake_agent
    GAZE_TOKEN=… GAZE_PORT=… uv run scripts/fake_overlay.py demo d1 d4   # against a running agent

Interactive:
    uv run scripts/fake_overlay.py repl [--spawn]
    > intent tell mom I'll be late      > select 1      > confirm yes      > help

WARNING: demo automatically confirms Send when connected to a real agent.
demo --spawn uses fakes. The REPL requires manual confirmation; DEMO_MODE=1
does not make desktop actions a dry run.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import secrets
import shlex
import socket
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import wsproto
from gaze_client import Closed, GazeClient

AGENT_PATH = Path(__file__).resolve().parent / "fake_agent.py"


# ---- agent process ------------------------------------------------------------------------

@contextlib.asynccontextmanager
async def spawned_agent(delay: float = 0.05, quiet: bool = True) -> AsyncIterator[tuple[int, str]]:
    """Start fake_agent.py on a free port with a random token; yields (port, token)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    token = secrets.token_hex(32)
    args = [sys.executable, str(AGENT_PATH), "--delay", str(delay)] + (["--quiet"] if quiet else [])
    proc = await asyncio.create_subprocess_exec(
        *args, env={**os.environ, "GAZE_TOKEN": token, "GAZE_PORT": str(port), "DEMO_MODE": "1"},
        stderr=asyncio.subprocess.DEVNULL if quiet else None)
    try:
        deadline = time.monotonic() + 15
        while True:
            try:
                _, writer = await asyncio.open_connection("127.0.0.1", port)
                writer.close()
                break
            except OSError:
                if proc.returncode is not None or time.monotonic() > deadline:
                    raise RuntimeError("fake_agent did not start") from None
                await asyncio.sleep(0.05)
        yield port, token
    finally:
        if proc.returncode is None:
            proc.terminate()
            await proc.wait()


# ---- scripted flows -----------------------------------------------------------------------

Connect = Callable[..., Awaitable[GazeClient]]


async def run_task(c: GazeClient, index: int, *, choose: int = 0, confirm: bool = True,
                   ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Select card `index`, answer every choice/confirm, return (task_result, requests seen)."""
    sel = await c.select(index)
    first = await c.next("task_status", re=sel["id"])
    assert first["payload"]["state"] == "running" and first["payload"]["step"] == 0, first
    task_id = first["payload"]["task_id"]
    seen: list[dict[str, Any]] = []
    while True:
        m = await c.next({"choice_request", "confirm_request", "task_result"}, task_id=task_id, timeout=10)
        if m["type"] == "task_result":
            terminal = [s for s in c.inbox if s["type"] == "task_status" and s["payload"]["task_id"] == task_id
                        and s["payload"]["state"] in ("done", "failed", "stopped")]
            assert len(terminal) == 1, f"expected exactly one terminal task_status, got {len(terminal)}"
            return m, seen
        seen.append(m)
        if m["type"] == "choice_request":
            option = m["payload"]["options"][choose]
            await c.send("choice_response", {"task_id": task_id, "choice_id": option["id"]}, re=m["id"])
        else:
            await c.send("confirm_response", {"task_id": task_id, "confirmed": confirm}, re=m["id"])


async def get_plans(c: GazeClient, text: str) -> list[dict[str, Any]]:
    intent = await c.send("intent_submit", {"text": text})
    plans = await c.next("plans", re=intent["id"])
    items = plans["payload"]["items"]
    assert items[-1]["id"] == "other" and items[-1]["kind"] == "other", "last plan must be 'Something else'"
    return items


async def flow_d1(connect: Connect) -> str:
    """Type mode: T9 words → decode → intent → plan → confirm Send."""
    async with await connect() as c:
        await c.send("mode_set", {"mode": "type"})
        dreq = await c.send("decode_request", {"words": ["tell", "mom", "i'll", "be"],
                                               "raw_keys": [["JKL", "ABC", "TUV", "DEF"]]})
        sentences = (await c.next("decode_result", re=dreq["id"]))["payload"]["sentences"]
        items = await get_plans(c, sentences[0])
        assert "Mom" in items[0]["label"], items[0]
        result, seen = await run_task(c, 0)
        assert [m["payload"]["action"] for m in seen] == ["send"], seen
        assert result["payload"]["ok"], result
        return f"“{sentences[0]}” → {items[0]['label']} → {result['payload']['summary']}"


async def flow_d2(connect: Connect) -> str:
    """Auto mode: suggestion card → confirm Send."""
    async with await connect() as c:
        await c.send("auto_refresh", {})
        sug = await c.next("suggestions")
        idx = next(i for i, p in enumerate(sug["payload"]["items"]) if p["label"].startswith("Reply"))
        result, seen = await run_task(c, idx)
        assert [m["payload"]["action"] for m in seen] == ["send"], seen
        assert result["payload"]["ok"], result
        return f"{sug['payload']['app']}: {sug['payload']['items'][idx]['label']} → {result['payload']['summary']}"


async def flow_d3(connect: Connect) -> str:
    """No confirm needed."""
    async with await connect() as c:
        items = await get_plans(c, "play my focus playlist")
        result, seen = await run_task(c, 0)
        assert not seen, f"D3 must not ask anything: {seen}"
        assert result["payload"]["ok"], result
        return f"{items[0]['label']} → {result['payload']['summary']}"


async def flow_d4(connect: Connect) -> str:
    """Profile reference resolved in the label → date choice → BUY confirm, demo no-op."""
    async with await connect() as c:
        artist = c.hello_ack["payload"]["profile"]["favorites"]["artist"]
        items = await get_plans(c, "tickets for my favorite artist")
        assert artist in items[0]["label"], f"artist {artist!r} not resolved in {items[0]['label']!r}"
        sel = await c.select(0)
        first = await c.wait_for("task_status", re=sel["id"])
        task_id = first["payload"]["task_id"]
        choice = await c.wait_for("choice_request", task_id=task_id, timeout=10)
        await c.send("choice_response", {"task_id": task_id,
                                         "choice_id": choice["payload"]["options"][1]["id"]}, re=choice["id"])
        confirm = await c.wait_for("confirm_request", task_id=task_id, timeout=10)
        payload = confirm["payload"]
        assert payload["action"] == "buy" and payload["demo_noop"], payload
        assert not any(m["type"] == "confirm_response" and m["payload"]["task_id"] == task_id
                       for m in c.sent), "rehearsal must stop at BUY confirm"
        return f"{items[0]['label']} → reached BUY confirm; no purchase response sent"


async def flow_recovery(connect: Connect) -> str:
    """Failure → recovery cards → Show me the screen → Try again."""
    async with await connect() as c:
        await get_plans(c, "fail on purpose")
        result, _ = await run_task(c, 0)
        p = result["payload"]
        assert not p["ok"] and [r["id"] for r in p["recovery"]] == [
            "recovery:retry", "recovery:show_screen", "recovery:cancel"], p
        look, _ = await run_task(c, 1)  # recovery:show_screen
        lp = look["payload"]
        assert lp["ok"] and lp["summary"] and [r["id"] for r in lp["recovery"]] == ["recovery:retry",
                                                                                   "recovery:cancel"], lp
        retry, _ = await run_task(c, 0)  # recovery:retry
        assert retry["payload"]["ok"], retry
        return f"failed → saw “{lp['summary'][:40]}…” → retry ok"


async def flow_recovery_show_screen(connect: Connect) -> str:
    """A failed task can select Show me the screen and get a read-only summary."""
    async with await connect() as c:
        await get_plans(c, "fail on purpose")
        failed, _ = await run_task(c, 0)
        assert not failed["payload"]["ok"], failed
        recovery = failed["payload"].get("recovery", [])
        show_screen = next((i for i, item in enumerate(recovery)
                            if item["id"] == "recovery:show_screen"), None)
        assert show_screen is not None, recovery
        shown, _ = await run_task(c, show_screen)
        payload = shown["payload"]
        assert payload["ok"] and payload["summary"], payload
        assert [item["id"] for item in payload["recovery"]] == ["recovery:retry", "recovery:cancel"], payload
        return f"failure → read-only screen summary → {payload['summary'][:40]}…"


async def flow_stop_during_confirm(connect: Connect) -> str:
    """Stop wins: a confirm sent after stop must never execute (§4.4)."""
    async with await connect() as c:
        await get_plans(c, "tell mom I'll be late")
        sel = await c.select(0)
        task_id = (await c.next("task_status", re=sel["id"]))["payload"]["task_id"]
        req = await c.next("confirm_request", task_id=task_id, timeout=10)
        await c.send("stop", {"reason": "gaze"})
        await c.next("task_status", task_id=task_id, state="stopped")
        result = await c.next("task_result", task_id=task_id)
        assert not result["payload"]["ok"], result
        late = await c.send("confirm_response", {"task_id": task_id, "confirmed": True}, re=req["id"])
        await c.expect_nothing("error", 0.1, re=late["id"])
        assert any(m["type"] == "error" and m["re"] == late["id"] and
                   m["payload"]["code"] == "no_task" for m in c.dropped), c.dropped
        await c.expect_nothing("task_status", 0.3, state="done")
        return "stopped at confirm; late CONFIRM → no_task"


async def flow_task_busy(connect: Connect) -> str:
    async with await connect() as c:
        await get_plans(c, "play my focus playlist")
        sel = await c.select(0)
        first = await c.next("task_status", re=sel["id"])
        second = await c.select(1)
        err = await c.next("error", re=second["id"])
        assert err["payload"]["code"] == "task_busy", err
        await c.send("stop", {"reason": "user"})
        await c.next("task_status", task_id=first["payload"]["task_id"], state="stopped")
        await c.next("task_result", task_id=first["payload"]["task_id"])
        return "second plan_select → task_busy"


async def flow_stale_list(connect: Connect) -> str:
    async with await connect() as c:
        await get_plans(c, "play my focus playlist")
        old_list, old_plan = c.list_id, c.list_items[0]["id"]
        await get_plans(c, "tell mom I'll be late")
        sel = await c.send("plan_select", {"list_id": old_list, "plan_id": old_plan})
        err = await c.next("error", re=sel["id"])
        assert err["payload"]["code"] == "stale_list", err
        return "old list_id → stale_list"


async def flow_settings(connect: Connect) -> str:
    async with await connect() as c:
        ok = await c.send("settings_update", {"patch": {"dwellMs": 1200}})
        res = await c.next("settings_result", re=ok["id"])
        assert res["payload"]["settings"]["dwellMs"] == 1200, res
        bad = await c.send("settings_update", {"patch": {"dwellMs": 50}})
        err = await c.next("error", re=bad["id"])
        assert err["payload"]["code"] == "bad_message", err
        prof = await c.send("profile_update", {"patch": {"favorites": {"playlist": "Lo-fi"}}})
        pres = await c.next("profile_result", re=prof["id"])
        assert pres["payload"]["profile"]["favorites"]["playlist"] == "Lo-fi", pres
        return "settings/profile merge-patch + validation"


async def flow_bad_input(connect: Connect) -> str:
    """Wrong token → 4401; garbage → bad_message; v:2 → version_mismatch + 4400."""
    c = await connect(token="wrong", hello=False)
    closed = await c.wait_closed()
    assert closed.code == 4401, closed
    async with await connect() as c:
        await c.send_raw("{not json")
        assert (await c.next("error"))["payload"]["code"] == "bad_message"
        frame = wsproto.make("permissions_check", {}) | {"v": 2}
        await c.send_raw(json.dumps(frame))
        err = await c.next("error", re=frame["id"])
        assert err["payload"]["code"] == "version_mismatch", err
        closed = await c.wait_closed()
        assert closed.code == 4400, closed
    return "4401 / bad_message / version_mismatch + 4400"


FLOWS: dict[str, Callable[[Connect], Awaitable[str]]] = {
    "d1": flow_d1, "d2": flow_d2, "d3": flow_d3, "d4": flow_d4, "recovery": flow_recovery,
    "recovery_show_screen": flow_recovery_show_screen,
    "stop_during_confirm": flow_stop_during_confirm, "task_busy": flow_task_busy,
    "stale_list": flow_stale_list, "settings": flow_settings, "bad_input": flow_bad_input,
}


def connector(port: int, token: str) -> Connect:
    async def connect(token: str = token, hello: bool = True) -> GazeClient:
        c = GazeClient(port, token)
        await c.connect(hello=hello)
        return c
    return connect


async def run_flows(names: list[str], port: int, token: str) -> bool:
    connect = connector(port, token)
    all_ok = True
    for name in names:
        t0 = time.monotonic()
        try:
            detail = await asyncio.wait_for(FLOWS[name](connect), 30)
            status = "PASS"
        except Exception as e:  # noqa: BLE001 - report every failure and keep going
            detail, status, all_ok = f"{type(e).__name__}: {e}", "FAIL", False
        print(f"{status}  {name:<20} {time.monotonic() - t0:5.2f}s  {detail}", flush=True)
    return all_ok


# ---- interactive ----------------------------------------------------------------------------

HELP = """commands:
  intent <text>              intent_submit
  decode <w1 w2 ...> [/ KEYS KEYS]   decode_request, e.g. decode tell mom / JKL ABC TUV DEF
  select <n>                 select plan/recovery card n (1-based); Cancel/Other stay local
  choose <n>|cancel          answer the pending choice_request
  confirm yes|no             answer the pending confirm_request
  stop                       stop{reason:"user"}
  mode auto|type             mode_set
  refresh                    auto_refresh
  idle on|off                gaze_context
  profile | perms            profile_get | permissions_check
  set <json>                 settings_update, e.g. set {"dwellMs":1200}
  quit"""


def clear_waits(state: dict[str, Any]) -> None:
    state.pop("choice", None)
    state.pop("confirm", None)


def show_cards(items: list[dict[str, Any]]) -> None:
    for i, item in enumerate(items, 1):
        local = " (local; no task sent)" if item["id"] in {"other", "recovery:cancel"} else ""
        print(f"   [{i}] {item['label']}" + (" ⚠" if item["risky"] else "") + local)
    if items:
        print("   Use select 1 (or another displayed plan number).")


def show(msg: dict[str, Any], state: dict[str, Any]) -> None:
    mtype, p = msg["type"], msg["payload"]
    if mtype in {"hello_ack", "task_result"} or (mtype == "task_status" and p["state"] != "waiting_user"):
        clear_waits(state)
    if mtype in ("plans", "suggestions"):
        print(f"\n← {mtype}" + (f" ({p['app']}, cached={p['cached']})" if mtype == "suggestions" else ""))
        show_cards(p["items"])
    elif mtype == "task_status":
        print(f"\n← [{p['state']} {p['step']}/{p['max_steps']}] {p['message']}")
    elif mtype == "choice_request":
        clear_waits(state)
        state["choice"] = msg
        print(f"\n← CHOICE: {p['question']}")
        for i, o in enumerate(p["options"], 1):
            print(f"   ({i}) {o['label']}")
        print("   Use choose 1 (or another option), choose cancel, or stop.")
    elif mtype == "confirm_request":
        clear_waits(state)
        state["confirm"] = msg
        badge = "  [DEMO: will not purchase]" if p["demo_noop"] else ""
        print(f"\n← CONFIRM {p['action'].upper()}: {p['title']}{badge}")
        for line in p["details"]:
            print(f"     {line}")
        print("   Use confirm no to cancel, confirm yes to execute, or stop.")
    elif mtype == "task_result":
        print(f"\n← RESULT ok={p['ok']}: {p['summary']}")
        show_cards(p.get("recovery", []))
    else:
        print(f"\n← {wsproto.brief(msg)}")
    print("> ", end="", flush=True)


def card_index(value: str, items: list) -> int:
    index = int(value) - 1
    if not 0 <= index < len(items):
        raise ValueError(f"Use a displayed number from 1 to {len(items)}")
    return index


async def command(c: GazeClient, state: dict[str, Any], line: str) -> bool:
    """Handle REPL UI actions; raw client.send/select remain available to negative tests."""
    cmd, _, rest = line.partition(" ")
    rest = rest.strip()
    if cmd == "quit":
        return False
    if cmd == "help":
        print(HELP)
    elif cmd == "intent":
        await c.send("intent_submit", {"text": rest})
        state["intent"] = rest
    elif cmd == "decode":
        words_part, _, keys_part = rest.partition("/")
        raw = [keys_part.split()] if keys_part.strip() else []
        await c.send("decode_request", {"words": words_part.split(), "raw_keys": raw})
    elif cmd == "select":
        if c.active_task_id or c._pending_select:
            raise RuntimeError("A task is active or starting; use choose N for a choice, confirm yes|no, or stop")
        index = card_index(rest, c.list_items)
        if c.list_items[index]["id"] in {"other", "recovery:cancel"}:
            clear_waits(state)
            c.list_id, c.list_items = None, []
            print("Back to input. Use intent <text>; your last intent is retained locally.")
        else:
            await c.select(index)
    elif cmd in {"choose", "confirm"}:
        key = "choice" if cmd == "choose" else "confirm"
        req = state.get(key)
        if req is None or req["payload"]["task_id"] != c.active_task_id:
            state.pop(key, None)
            raise RuntimeError(f"No pending {key}; wait for a request")
        if cmd == "choose":
            options = req["payload"]["options"]
            choice = None if rest == "cancel" else options[card_index(rest, options)]["id"]
            payload = {"task_id": c.active_task_id, "choice_id": choice}
        else:
            if rest not in {"yes", "no"}:
                raise ValueError("Use confirm yes|no")
            payload = {"task_id": c.active_task_id, "confirmed": rest == "yes"}
        await c.send("choice_response" if cmd == "choose" else "confirm_response", payload, re=req["id"])
        # A new request may arrive while send yields; never discard that wait.
        if state.get(key) is req:
            state.pop(key)
    elif cmd == "stop":
        clear_waits(state)
        await c.send("stop", {"reason": "user"})
    elif cmd == "mode":
        await c.send("mode_set", {"mode": rest})
    elif cmd == "refresh":
        await c.send("auto_refresh", {})
    elif cmd == "idle":
        await c.send("gaze_context", {"dock_idle": rest == "on", "idle_ms": 1500 if rest == "on" else 0})
    elif cmd == "profile":
        await c.send("profile_get", {})
    elif cmd == "perms":
        await c.send("permissions_check", {})
    elif cmd == "set":
        await c.send("settings_update", {"patch": json.loads(rest)})
    else:
        print(f"unknown command {cmd!r}; use select N for plans, choose N for choices, or help")
    return True


async def repl(port: int, token: str) -> None:
    state: dict[str, Any] = {}
    c = GazeClient(port, token, on_message=lambda m: show(m, state))
    await c.connect()
    print(HELP)
    try:
        while True:
            line = (await asyncio.to_thread(input, "> ")).strip()
            if not line:
                continue
            if c.closed:
                print(f"! {c.closed}")
                return
            try:
                if not await command(c, state, line):
                    return
            except (KeyError, IndexError, ValueError, RuntimeError) as e:
                print(f"! {type(e).__name__}: {e}")
            if c.closed:
                print(f"! {c.closed}")
                return
    finally:
        clear_waits(state)
        await c.close()


# ---- main -----------------------------------------------------------------------------------

async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["demo", "repl"])
    ap.add_argument("flows", nargs="*", help=f"demo flows to run (default: all): {', '.join(FLOWS)}")
    ap.add_argument("--spawn", action="store_true", help="start a fake_agent on a free port")
    ap.add_argument("--delay", type=float, default=None,
                    help="step delay for a spawned agent (default 0.05 for demo, 0.6 for repl)")
    args = ap.parse_args()

    unknown = [f for f in args.flows if f not in FLOWS]
    if unknown:
        ap.error(f"unknown flows: {unknown}")
    names = args.flows or list(FLOWS)

    async def go(port: int, token: str) -> int:
        if args.command == "repl":
            await repl(port, token)
            return 0
        return 0 if await run_flows(names, port, token) else 1

    if args.spawn:
        delay = args.delay if args.delay is not None else (0.05 if args.command == "demo" else 0.6)
        async with spawned_agent(delay=delay) as (port, token):
            return await go(port, token)
    return await go(int(os.environ.get("GAZE_PORT", "8765")), os.environ.get("GAZE_TOKEN") or "dev-token")


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt, EOFError):
        sys.exit(asyncio.run(main()))
