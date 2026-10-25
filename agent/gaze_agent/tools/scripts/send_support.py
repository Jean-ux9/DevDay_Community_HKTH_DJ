"""Private H3 send validation and bounded subprocess transport.

Never invoke this transport from an unapproved action. Tests inject both process
creation and process-group signalling; importing/constructing it performs no I/O.
"""
from __future__ import annotations

import asyncio
import math
import os
import re
import signal
from dataclasses import dataclass, field


def text(value, *, limit=32768, single_line=False, nonempty=False):
    if not isinstance(value, str):
        raise ValueError("invalid_arguments")
    try:
        valid = len(value.encode("utf-8")) <= limit
    except UnicodeError:
        valid = False
    if (not valid or "\0" in value or (nonempty and not value)
            or (single_line and any(ord(c) < 32 or ord(c) == 127 for c in value))):
        raise ValueError("invalid_arguments")
    return value


def mailbox(value):
    """Deliberately narrow single addr-spec, never display names/lists/aliases."""
    value = text(value, limit=254, single_line=True, nonempty=True)
    if not re.fullmatch(r"[A-Za-z0-9_+][A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]*@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", value):
        raise ValueError("invalid_recipient")
    local, domain = value.split("@")
    if local.endswith(".") or ".." in value or any(
        not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
        for label in domain.split(".")
    ):
        raise ValueError("invalid_recipient")
    return value


def destination(value):
    if isinstance(value, str) and re.fullmatch(r"\+[1-9][0-9]{7,14}", value):
        return value
    return mailbox(value)


@dataclass(frozen=True, repr=False)
class ProcessReply:
    returncode: int
    stdout: bytes = field(repr=False)


class UncertainSend(Exception):
    """Fixed public code only; no exception chaining into provider results."""


class SendProcess:
    """One child session, bounded output, no shell, stderr discarded.

    Group signalling also stops imsg's osascript child. Cancellation during spawn
    waits for ownership before cleanup, including repeated cancellation requests.
    Process creation itself is an OS operation and cannot safely be abandoned.
    """

    def __init__(self, *, spawn=asyncio.create_subprocess_exec,
                 signal_group=os.killpg, timeout=20.0):
        if not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise ValueError("invalid_timeout")
        self._spawn = spawn
        self._signal_group = signal_group
        self._timeout = timeout

    async def _cleanup(self, process):
        # Signal the session even if its parent exited: a grandchild may remain.
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                self._signal_group(process.pid, sig)
            except ProcessLookupError:
                pass
            try:
                async with asyncio.timeout(0.15):
                    await process.wait()
                # SIGKILL any descendants that ignored TERM after parent exit.
                if sig == signal.SIGTERM:
                    continue
                return
            except TimeoutError:
                pass
        # SIGKILL cannot be ignored; reap the child instead of abandoning it.
        await process.wait()

    async def _settle(self, task):
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        return task.result()

    async def run(self, argv):
        await asyncio.sleep(0)  # honour cancellation before creating any child
        deadline = asyncio.get_running_loop().time() + self._timeout
        startup = asyncio.create_task(self._spawn(
            *argv, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True, limit=2048,
        ))
        try:
            async with asyncio.timeout_at(deadline):
                process = await asyncio.shield(startup)
        except (asyncio.CancelledError, TimeoutError) as error:
            code = "timeout_unknown" if isinstance(error, TimeoutError) else "cancelled_unknown"
            try:
                process = await self._settle(startup)
            except OSError:
                raise UncertainSend(code) from None
            await self._settle(asyncio.create_task(self._cleanup(process)))
            raise UncertainSend(code) from None
        try:
            async with asyncio.timeout_at(deadline):
                # Read to EOF with a hard cap; never retain raw diagnostics.
                output = await process.stdout.read(1025)
                while len(output) <= 1024:
                    part = await process.stdout.read(1025 - len(output))
                    if not part:
                        break
                    output += part
                if len(output) > 1024:
                    raise UncertainSend("output_unknown")
                code = await process.wait()
                return ProcessReply(code, output)
        except (TimeoutError, asyncio.CancelledError, UncertainSend) as error:
            code = ("timeout_unknown" if isinstance(error, TimeoutError) else
                    "cancelled_unknown" if isinstance(error, asyncio.CancelledError) else
                    "output_unknown")
            await self._settle(asyncio.create_task(self._cleanup(process)))
            raise UncertainSend(code) from None
        except Exception:
            await self._settle(asyncio.create_task(self._cleanup(process)))
            raise UncertainSend("transport_unknown") from None
