"""Action metadata with seven-day retention (spec §10)."""
from __future__ import annotations
import json
import os
import time
from pathlib import Path
from gaze_agent.profile import DATA_DIR


class TaskLog:
    def __init__(self, directory: Path = DATA_DIR, *, clock=time.time):
        self.path = Path(directory) / "tasklog.jsonl"
        self.clock = clock
        self.prune()

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
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
