"""Action metadata with seven-day retention (spec §10)."""
from __future__ import annotations
import asyncio
import json
import logging
import math
import os
import time
from contextvars import ContextVar
from pathlib import Path
from gaze_agent.profile import DATA_DIR


class UsageMeter:
    """Session totals by prompt name; never retains inputs or model responses."""

    def __init__(self, *, environ=None):
        environ = os.environ if environ is None else environ
        self.prices = {}
        for slot in ("agent", "fast", "vision"):
            values = []
            for direction in ("IN", "OUT"):
                try:
                    price = float(environ.get(f"OPENAI_PRICE_{slot.upper()}_{direction}", ""))
                    values.append(price if math.isfinite(price) and price >= 0 else None)
                except (ValueError, TypeError):
                    values.append(None)
            self.prices[slot] = tuple(values)
        self.prompts = {}
        self._warned = False

    def record(self, prompt: str, slot: str, input_tokens: int | None, output_tokens: int | None,
               *, cached: bool = False) -> None:
        if cached:
            return
        row = self.prompts.setdefault(prompt, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "est_usd": 0.0})
        row["calls"] += 1
        row["input_tokens"] += input_tokens or 0
        row["output_tokens"] += output_tokens or 0
        price_in, price_out = self.prices[slot]
        if price_in is None or price_out is None:
            if not self._warned:
                logging.getLogger(__name__).warning("Missing OPENAI_PRICE_* configuration; usage est_usd is null")
                self._warned = True
        if None in (price_in, price_out, input_tokens, output_tokens):
            row["est_usd"] = None
        elif row["est_usd"] is not None:
            row["est_usd"] += (input_tokens * price_in + output_tokens * price_out) / 1_000_000

    def summary(self) -> dict:
        rows = list(self.prompts.values())
        return {"calls": sum(row["calls"] for row in rows),
                "input_tokens": sum(row["input_tokens"] for row in rows),
                "output_tokens": sum(row["output_tokens"] for row in rows),
                "est_usd": None if any(row["est_usd"] is None for row in rows)
                else sum(row["est_usd"] for row in rows),
                "prompts": {name: dict(row) for name, row in self.prompts.items()}}


_usage: ContextVar[UsageMeter | None] = ContextVar("session_usage", default=None)


def get_usage_meter() -> UsageMeter:
    meter = _usage.get()
    if meter is None:
        meter = UsageMeter()
        _usage.set(meter)
    return meter


class TaskLog:
    def __init__(self, directory: Path = DATA_DIR, *, clock=time.time, monotonic=None, usage=None):
        self.path = Path(directory) / "tasklog.jsonl"
        self.clock = clock
        self.monotonic = monotonic or time.monotonic
        self.usage = usage or UsageMeter()
        self._last_usage = self.monotonic()
        self.prune()

    def bind_usage(self):
        return _usage.set(self.usage)

    def reset_usage(self, token):
        _usage.reset(token)

    def write_usage(self, *, force=False) -> bool:
        now = self.monotonic()
        if not force and now - self._last_usage < 300:
            return False
        self._append({"ts": self.clock(), "tool": "usage", **self.usage.summary()})
        self._last_usage = now
        return True

    async def report_usage(self) -> None:
        while True:
            await asyncio.sleep(300)
            self.write_usage()

    def usage_summary(self) -> str:
        return "Gaze session usage: " + json.dumps(self.usage.summary(), separators=(",", ":"))

    def prune(self) -> None:
        if not self.path.exists():
            return
        cutoff = self.clock() - 7 * 24 * 3600
        kept = []
        for line in self.path.read_text().splitlines():
            try:
                item = json.loads(line)
                if isinstance(item.get("ts"), (int, float)) and item["ts"] >= cutoff:
                    kept.append(json.dumps(item, ensure_ascii=False))
            except (ValueError, TypeError, AttributeError):
                continue
        self.path.write_text("".join(line + "\n" for line in kept))
        self.path.chmod(0o600)

    def event(self, *, task_id: str, plan_label: str, tool: str, outcome: str,
              latency_ms: float = 0, element_label: str = "", **private) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Plan/element labels may themselves contain message bodies.
        debug = os.getenv("DEBUG") == "1"
        row = {"ts": self.clock(), "task_id": task_id,
               "plan_label": plan_label if debug else "", "tool": tool,
               "element_label": element_label if debug else "", "outcome": outcome,
               "latency_ms": round(latency_ms, 2)}
        if debug:
            row.update(private)
        self._append(row)

    def _append(self, row: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
