# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["websockets>=14", "jsonschema>=4.23"]
# ///
"""Run D1-D4 against the real agent, or all fake lifecycle/recovery checks.

The default target starts the real Python agent with replay and demo mode enabled.
Use ``--target fake`` for a fully local rehearsal that never touches desktop apps.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import secrets
import shutil
import socket
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fake_overlay

ROOT = Path(__file__).resolve().parent.parent
FAKE_AGENT = ROOT / "scripts" / "fake_agent.py"
AGENT_PROJECT = ROOT / "agent"
DEMO_PROFILE = json.loads((ROOT / "fixtures" / "demo_profile.json").read_text(encoding="utf-8"))
DEMO_FLOWS = (
    ("D1", "d1"),
    ("D2", "d2"),
    ("D3", "d3"),
    ("D4", "d4"),
)
FAKE_EXTRA_FLOWS = (
    ("recovery", "recovery"),
    ("stop_during_confirm", "stop_during_confirm"),
    ("stale_list", "stale_list"),
    ("task_busy", "task_busy"),
    ("recovery_show_screen", "recovery_show_screen"),
)


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
        "REPLAY": "replay",
        "DEMO_MODE": "1",
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
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
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
        if target == "real":
            async with await connect() as client:
                ack = client.hello_ack["payload"]
                if not ack["demo_mode"]:
                    raise RuntimeError("agent did not report demo mode; no rehearsal tasks were sent")
                if ack["profile"] != DEMO_PROFILE:
                    raise RuntimeError("agent profile does not match fixtures/demo_profile.json; "
                                       "no rehearsal tasks were sent")
        flows = DEMO_FLOWS + FAKE_EXTRA_FLOWS if target == "fake" else DEMO_FLOWS
        for label, flow_name in flows:
            started = time.monotonic()
            try:
                detail = await asyncio.wait_for(fake_overlay.FLOWS[flow_name](connect), timeout=45)
                status = "PASS"
            except Exception as exc:  # report all failures in one rehearsal run
                status = "FAIL"
                detail = f"{type(exc).__name__}: {exc}"
                all_ok = False
            print(f"{status}  {label:<22} {time.monotonic() - started:5.2f}s  {detail}", flush=True)
    return all_ok


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("real", "fake"), default="real",
                        help="start the real agent (default) or the no-desktop fake")
    parser.add_argument("--delay", type=float, default=0.03,
                        help="step delay for --target fake (default: 0.03 seconds)")
    args = parser.parse_args()
    try:
        return 0 if await rehearse(args.target, args.delay) else 1
    except Exception as exc:
        print(f"FAIL  startup                {type(exc).__name__}: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        sys.exit(asyncio.run(main()))
