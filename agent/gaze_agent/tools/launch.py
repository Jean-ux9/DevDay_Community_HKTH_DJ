"""Bounded macOS launcher; completion means launcher acceptance only.

Runtime owns URL risk/confirmation checks, registration and task deduplication.
This provider never observes focus, rendered pages or installed applications.
"""
from __future__ import annotations

import asyncio
import ipaddress
import math
import re
import unicodedata
from collections.abc import Awaitable, Callable
from types import MappingProxyType
from typing import Protocol
from urllib.parse import unquote, urlsplit

from .contracts import ActionRequest, ActionResult, PreparedAction


APP_BUNDLES = MappingProxyType({
    "Safari": "com.apple.Safari",
    "Mail": "com.apple.mail",
    "Messages": "com.apple.MobileSMS",
    "TextEdit": "com.apple.TextEdit",
    "Notes": "com.apple.Notes",
    "Calendar": "com.apple.iCal",
})
PROVIDER = "system_launcher"


class Process(Protocol):
    async def wait(self) -> int: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...


ProcessTransport = Callable[..., Awaitable[Process]]


def _consume_error(task: asyncio.Task) -> None:
    if not task.cancelled():
        task.exception()


def _control(text: str) -> bool:
    return any(unicodedata.category(char).startswith("C") for char in text)


def _url(value: object) -> str:
    # urlsplit strips some controls: reject before parsing, including escaped ones.
    if (not isinstance(value, str) or not value or len(value) > 4096
            or _control(value) or any(char.isspace() for char in value)
            or "\\" in value or re.search(r"%(?![0-9a-fA-F]{2})", value)
            or _control(unquote(value)) or "\\" in unquote(value)):
        raise ValueError("invalid_url")
    try:
        parsed = urlsplit(value)
        if (parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc
                or "@" in parsed.netloc or "%" in parsed.netloc
                or parsed.username is not None or parsed.password is not None
                or not parsed.hostname or parsed.port == 0):
            raise ValueError
        if parsed.netloc.startswith("["):
            if not re.fullmatch(r"\[[0-9a-fA-F:.]+\](?::[0-9]+)?", parsed.netloc):
                raise ValueError
            ipaddress.IPv6Address(parsed.hostname)
        else:
            if not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]+)?", parsed.netloc):
                raise ValueError
            host = parsed.hostname.removesuffix(".")
            if len(host) > 253 or not all(
                re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                for label in host.split(".")
            ):
                raise ValueError
            if re.fullmatch(r"[0-9.]+", host):
                ipaddress.IPv4Address(host)
    except ValueError:
        raise ValueError("invalid_url") from None
    return value


def _payload(operation: str, arguments) -> dict[str, str]:
    if operation == "app.open" and set(arguments) == {"name"}:
        name = arguments["name"]
        if isinstance(name, str):
            for approved in APP_BUNDLES:
                if name.casefold() == approved.casefold():
                    return {"name": approved}
        raise ValueError("unsupported_app")
    if operation == "web.open" and set(arguments) == {"url"}:
        return {"url": _url(arguments["url"])}
    raise ValueError("invalid_launch_request")


class LaunchProvider:
    """No I/O until execute; inject an async create_subprocess_exec-style transport.

    Cancellation propagates after cleanup so runtime STOP/disconnect stays intact.
    Post-dispatch timeout is unknown: terminating open cannot recall an app/page.
    """

    def __init__(self, *, process_transport: ProcessTransport | None = None,
                 timeout: float = 5.0, cleanup_timeout: float = 0.5):
        if not all(isinstance(n, (float, int)) and not isinstance(n, bool)
                   and math.isfinite(n) and 0 < n <= 10
                   for n in (timeout, cleanup_timeout)):
            raise ValueError("invalid_launch_timeout")
        self._transport = process_transport or asyncio.create_subprocess_exec
        self._timeout = timeout
        self._cleanup_timeout = cleanup_timeout

    async def prepare(self, request: ActionRequest) -> PreparedAction:
        return PreparedAction(request.request_id, request.operation, PROVIDER,
                              _payload(request.operation, request.arguments))

    async def _reap(self, process: Process, waiter: asyncio.Task | None = None) -> None:
        waiter = waiter if waiter is not None else asyncio.create_task(process.wait())
        for stop in (process.terminate, process.kill):
            if waiter.done():
                if not waiter.cancelled() and waiter.exception() is None:
                    return
                waiter = asyncio.create_task(process.wait())
            try:
                stop()
            except Exception:
                # Transport errors must never escape with provider diagnostics.
                pass
            try:
                await asyncio.wait_for(asyncio.shield(waiter), self._cleanup_timeout)
                return
            except Exception:
                continue
        # Real OS children are reapable after kill. Keep the waiter alive even if
        # a broken injected transport fails to acknowledge death within the bound.
        waiter.add_done_callback(_consume_error)

    async def _cleanup(self, spawn: asyncio.Task, process: Process | None,
                       waiter: asyncio.Task | None) -> None:
        if process is None:
            try:
                process = await asyncio.wait_for(asyncio.shield(spawn), self._cleanup_timeout)
            except TimeoutError:
                # Cancellation can race subprocess creation. Own the eventual child
                # too, without leaving STOP waiting indefinitely for a transport.
                def late_child(done):
                    if not done.cancelled() and done.exception() is None:
                        cleanup = asyncio.create_task(self._reap(done.result()))
                        cleanup.add_done_callback(_consume_error)
                spawn.add_done_callback(late_child)
                return
            except Exception:
                return
        await self._reap(process, waiter)

    async def execute(self, action: PreparedAction) -> ActionResult:
        try:
            payload = _payload(action.operation, action.payload)
            if action.provider != PROVIDER or payload != dict(action.payload):
                raise ValueError
        except (ValueError, TypeError):
            return ActionResult("failed", "invalid_prepared_action")

        argv = (["/usr/bin/open", "-b", APP_BUNDLES[payload["name"]]]
                if action.operation == "app.open" else ["/usr/bin/open", payload["url"]])
        process = None
        waiter = None
        spawn = asyncio.create_task(self._transport(
            *argv, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        ))
        try:
            async with asyncio.timeout(self._timeout):
                process = await asyncio.shield(spawn)
                waiter = asyncio.create_task(process.wait())
                returncode = await asyncio.shield(waiter)
            if returncode == 0:
                return ActionResult("completed", "launcher_accepted")
            return ActionResult("failed", "launcher_rejected")
        except (asyncio.CancelledError, TimeoutError) as error:
            cleanup = asyncio.create_task(self._cleanup(spawn, process, waiter))
            # Repeated STOP/cancel signals must not interrupt terminate/reap.
            cancelled = isinstance(error, asyncio.CancelledError)
            while not cleanup.done():
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    cancelled = True
            cleanup.result()
            if cancelled:
                raise asyncio.CancelledError from None
            return ActionResult("unknown", "launcher_timeout")
        except OSError:
            if process is None:
                return ActionResult("failed", "launcher_unavailable")
            await self._cleanup(spawn, process, waiter)
            return ActionResult("unknown", "launcher_error")
        except Exception:
            await self._cleanup(spawn, process, waiter)
            return ActionResult("unknown", "launcher_error")
