"""Explicit window-only capture and vision tool. Importing never captures."""
from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from gaze_agent import llm
from gaze_agent.contracts import Element, LookResult
from gaze_agent.screen import ax


@dataclass(frozen=True)
class TargetWindow:
    window_id: int
    x: int
    y: int
    width: int
    height: int


def target_window() -> TargetWindow:
    import Quartz as Q
    app, _, focused = ax.front_window()
    title = str(ax.attribute(focused, "AXTitle", ""))
    windows = Q.CGWindowListCopyWindowInfo(Q.kCGWindowListOptionOnScreenOnly, Q.kCGNullWindowID)
    candidates = [w for w in windows if w.get(Q.kCGWindowOwnerPID) == app.processIdentifier()
                  and w.get(Q.kCGWindowLayer) == 0
                  and w.get(Q.kCGWindowBounds, {}).get("Width", 0) > 0]
    if not candidates:
        raise RuntimeError("No target window; check Screen Recording permission")
    matching = [w for w in candidates if w.get(Q.kCGWindowName) == title]
    window = (matching or candidates)[0]
    bounds = window[Q.kCGWindowBounds]
    return TargetWindow(int(window[Q.kCGWindowNumber]), *(int(bounds[k]) for k in ("X", "Y", "Width", "Height")))


def capture_window(target: TargetWindow) -> bytes:
    with tempfile.TemporaryDirectory(prefix="gaze-window-") as directory:
        path = Path(directory) / "window.png"
        subprocess.run(["screencapture", "-x", "-o", "-l", str(target.window_id), str(path)],
                       check=True, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return path.read_bytes()


def vision_image(raw: bytes) -> tuple[bytes, tuple[int, int]]:
    """Resize an existing image with macOS sips; never captures on its own."""
    with tempfile.TemporaryDirectory(prefix="gaze-vision-") as directory:
        source, output = Path(directory) / "window.png", Path(directory) / "window.jpg"
        source.write_bytes(raw)
        subprocess.run(["sips", "-Z", "1280", "-s", "format", "jpeg", "-s", "formatOptions", "70",
                        str(source), "--out", str(output)], check=True, timeout=10,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        from AppKit import NSBitmapImageRep
        from Foundation import NSData
        jpeg = output.read_bytes()
        rep = NSBitmapImageRep.imageRepWithData_(NSData.dataWithBytes_length_(jpeg, len(jpeg)))
        return jpeg, (int(rep.pixelsWide()), int(rep.pixelsHigh()))


class AutoOCR:
    """A global Auto capture budget; failed attempts also consume the minute."""

    def __init__(self, *, clock=None):
        self.clock = clock or time.monotonic
        self.last_attempt = float("-inf")
        self.window_key: str | None = None
        self.elements: list[Element] = []

    def read(self, window_key: str) -> list[Element]:
        from gaze_agent.auto import normalize_window_key
        from gaze_agent.screen.ocr import recognize
        key = normalize_window_key(window_key)
        now = self.clock()
        if now - self.last_attempt < 60:
            return list(self.elements) if key == self.window_key else []
        self.last_attempt = now
        try:
            target = target_window()
            jpeg, _ = vision_image(capture_window(target))
            elements = recognize(jpeg, target, fast=True)
        except Exception:
            return list(self.elements) if key == self.window_key else []
        self.window_key, self.elements = key, elements
        return list(elements)


auto_ocr = AutoOCR()


async def look_at_screen(question: str) -> LookResult:
    target = await asyncio.to_thread(target_window)
    raw = await asyncio.to_thread(capture_window, target)
    jpeg, size = await asyncio.to_thread(vision_image, raw)
    response = await llm.complete("look_at_screen", "vision", {"question": question}, image_jpeg=jpeg)
    text, point = response.text or "", None
    try:
        data = json.loads(text)
        answer = str(data["answer"])
        xy = data.get("point")
        if isinstance(xy, list) and len(xy) == 2 and all(isinstance(v, (int, float)) for v in xy):
            if 0 <= xy[0] <= size[0] and 0 <= xy[1] <= size[1]:
                point = (target.x + round(xy[0] * target.width / size[0]),
                         target.y + round(xy[1] * target.height / size[1]))
        text = answer
    except (ValueError, KeyError, TypeError):
        pass
    return LookResult(text, point)
