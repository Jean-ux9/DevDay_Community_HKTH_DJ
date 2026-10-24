"""Overlay-side WebSocket client (spec §4), shared by fake_overlay.py and the rehearsal script.

It applies the same filtering rules as the real overlay (§4.4): task-scoped messages for a
task_id that isn't the active task are dropped, and only the most recent list is selectable.
Needs `websockets` and `jsonschema`.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterable
from typing import Any

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

import wsproto
from wsproto import ProtocolError

TASK_SCOPED = {"task_status", "choice_request", "confirm_request", "task_result"}
TERMINAL_STATES = {"done", "failed", "stopped"}


class Closed(Exception):
    def __init__(self, code: int | None, reason: str):
        super().__init__(f"connection closed ({code}) {reason}".strip())
        self.code = code
        self.reason = reason


class GazeClient:
    def __init__(self, port: int, token: str, *, host: str = "127.0.0.1",
                 on_message: Callable[[dict[str, Any]], None] | None = None):
        self.url = f"ws://{host}:{port}/?token={token}"
        self.on_message = on_message
        self.ws: ClientConnection | None = None
        self.inbox: list[dict[str, Any]] = []
        self.dropped: list[dict[str, Any]] = []   # task-scoped messages for a dead/foreign task
        self.invalid: list[str] = []              # frames that failed schema validation
        self.sent: list[dict[str, Any]] = []
        self.active_task_id: str | None = None
        self.list_id: str | None = None
        self.list_items: list[dict[str, Any]] = []
        self.hello_ack: dict[str, Any] | None = None
        self.closed: Closed | None = None
        self._pending_select: str | None = None
        self._cond = asyncio.Condition()
        self._reader: asyncio.Task | None = None

    # -- connection --
    async def connect(self, hello: bool = True) -> dict[str, Any] | None:
        self.ws = await connect(self.url)
        self._reader = asyncio.create_task(self._read())
        if not hello:
            return None
        msg = await self.send("hello", {"client": "overlay", "version": "0.1.0"})
        self.hello_ack = await self.next("hello_ack", re=msg["id"])
        return self.hello_ack

    async def close(self) -> None:
        if self.ws is not None:
            await self.ws.close()
        if self._reader is not None:
            await asyncio.gather(self._reader, return_exceptions=True)

    async def wait_closed(self, timeout: float = 5.0) -> Closed:
        """Wait until the server closes the socket; returns the close code/reason."""
        assert self._reader is not None, "not connected"
        await asyncio.wait_for(asyncio.shield(self._reader), timeout)
        assert self.closed is not None
        return self.closed

    async def __aenter__(self) -> GazeClient:
        if self.ws is None:
            await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    # -- sending --
    async def send(self, mtype: str, payload: dict[str, Any], re: str | None = None) -> dict[str, Any]:
        msg = wsproto.make(mtype, payload, re, direction="o2a")
        if mtype == "plan_select":
            self._pending_select = msg["id"]
        assert self.ws is not None, "not connected"
        await self.ws.send(json.dumps(msg, ensure_ascii=False))
        self.sent.append(msg)
        return msg

    async def send_raw(self, frame: str) -> None:
        """Send an arbitrary frame, bypassing validation (for negative tests)."""
        assert self.ws is not None, "not connected"
        await self.ws.send(frame)

    # -- receiving --
    async def _read(self) -> None:
        assert self.ws is not None
        try:
            async for raw in self.ws:
                try:
                    msg = wsproto.parse(raw, "a2o")
                except ProtocolError as e:
                    self.invalid.append(f"{e.code}: {e.message}")
                    continue
                if self._accept(msg):
                    if self.on_message:
                        self.on_message(msg)
                    async with self._cond:
                        self.inbox.append(msg)
                        self._cond.notify_all()
        except ConnectionClosed:
            pass
        finally:
            self.closed = Closed(self.ws.close_code, self.ws.close_reason or "")
            async with self._cond:
                self._cond.notify_all()

    def _accept(self, msg: dict[str, Any]) -> bool:
        """Overlay-side state tracking + §4.4 filtering. Returns False to drop the message."""
        mtype, p = msg["type"], msg["payload"]
        if mtype == "hello_ack":
            self.active_task_id = None  # reconnect = back to idle
            self.list_id = None
            self.list_items = []
            self._pending_select = None
            self.inbox[:] = [
                old for old in self.inbox
                if old["type"] not in TASK_SCOPED and not (old["type"] == "error" and old["payload"].get("task_id"))
            ]
        if mtype == "task_status" and p["state"] == "running" and msg["re"] and msg["re"] == self._pending_select:
            self.active_task_id = p["task_id"]  # the first reply to our plan_select starts the task
            self._pending_select = None
        task_scoped = mtype in TASK_SCOPED or (mtype == "error" and p.get("task_id") is not None)
        if task_scoped and p["task_id"] != self.active_task_id:
            self.dropped.append(msg)
            return False
        if mtype == "task_result":
            self.active_task_id = None
        if mtype in ("plans", "suggestions") or (mtype == "task_result" and "list_id" in p):
            self.list_id = p["list_id"]
            self.list_items = p["items"] if mtype != "task_result" else p["recovery"]
        return True

    async def next(self, types: str | Iterable[str] | None = None, *, timeout: float = 5.0,
                   re: str | None = None, **payload_match: Any) -> dict[str, Any]:
        """Remove and return the first buffered message matching type/re/payload fields.

        Messages that don't match stay buffered for later calls.
        """
        wanted = {types} if isinstance(types, str) else set(types) if types else None

        def find() -> dict[str, Any] | Closed | None:
            for i, m in enumerate(self.inbox):
                if wanted is not None and m["type"] not in wanted:
                    continue
                if re is not None and m["re"] != re:
                    continue
                if any(m["payload"].get(k) != v for k, v in payload_match.items()):
                    continue
                return self.inbox.pop(i)
            return self.closed

        async with self._cond:
            try:
                found = await asyncio.wait_for(self._cond.wait_for(find), timeout)
            except TimeoutError:
                raise TimeoutError(f"no {wanted or 'message'} (re={re}, {payload_match}) within {timeout}s; "
                                   f"buffered: {[m['type'] for m in self.inbox]}") from None
        if isinstance(found, Closed):
            raise found
        return found

    async def wait_for(self, types: str | Iterable[str] | None = None, *, task_id: str | None = None,
                       timeout: float = 5.0, re: str | None = None,
                       **payload_match: Any) -> dict[str, Any]:
        """Wait for a validated message, optionally scoped to an active ``task_id``."""
        if task_id is not None:
            if "task_id" in payload_match:
                raise TypeError("pass task_id either by keyword or payload_match, not both")
            payload_match["task_id"] = task_id
        return await self.next(types, timeout=timeout, re=re, **payload_match)

    async def expect_nothing(self, types: str | Iterable[str], seconds: float, **payload_match: Any) -> None:
        """Assert no matching message arrives within `seconds`."""
        try:
            msg = await self.next(types, timeout=seconds, **payload_match)
        except TimeoutError:
            return
        raise AssertionError(f"unexpected {wsproto.brief(msg)}")

    # -- conveniences --
    async def select(self, index: int) -> dict[str, Any]:
        """plan_select the card at `index` (0-based) of the current list."""
        if self.list_id is None or not self.list_items:
            raise RuntimeError("no list to select from")
        item = self.list_items[index]
        return await self.send("plan_select", {"list_id": self.list_id, "plan_id": item["id"]})
