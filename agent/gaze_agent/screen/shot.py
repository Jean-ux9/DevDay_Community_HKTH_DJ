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


def select_window(windows, *, pid: int, title: str, bbox=None) -> TargetWindow:
    """Select the AX-focused window, never an arbitrary window or the overlay."""
    candidates = []
    for window in windows or []:
        rect = window.get("kCGWindowBounds", {})
        bounds = ax.bounds(tuple(rect.get(k) for k in ("X", "Y", "Width", "Height")))
        if (window.get("kCGWindowOwnerPID") == pid and window.get("kCGWindowLayer") == 0
                and window.get("kCGWindowIsOnscreen", True) and bounds is not None
                and bounds[2] > 0 and bounds[3] > 0 and window.get("kCGWindowNumber", 0) > 0):
            candidates.append((window, bounds))
    if bbox is not None and bbox[2] > 0 and bbox[3] > 0:
        candidates = [(w, b) for w, b in candidates if all(abs(a - c) <= 2 for a, c in zip(b, bbox))]
    matching = [(w, b) for w, b in candidates if title and w.get("kCGWindowName") == title]
    candidates = matching or candidates
    if len(candidates) != 1:
        raise RuntimeError("Cannot identify the focused target window; check permissions and re-read")
    window, bounds = candidates[0]
    return TargetWindow(int(window["kCGWindowNumber"]), *bounds)


def target_window() -> TargetWindow:
    import Quartz as Q
    app, _, focused = ax.front_window()
    read = ax.current_read()
    if read is not None:
        read.check(app, focused)
    title = str(ax.attribute(focused, "AXTitle", ""))
    windows = Q.CGWindowListCopyWindowInfo(Q.kCGWindowListOptionOnScreenOnly, Q.kCGNullWindowID)
    position = ax._point(ax.attribute(focused, "AXPosition"), "kAXValueCGPointType")
    size = ax._point(ax.attribute(focused, "AXSize"), "kAXValueCGSizeType")
    return select_window(windows, pid=app.processIdentifier(), title=title, bbox=(*position, *size))


def _check_capture_target(target: TargetWindow) -> None:
    read = ax.current_read()
    if read is not None and read.identity is not None and target_window() != target:
        raise ax.WindowChanged()


def capture_window(target: TargetWindow) -> bytes:
    if target.window_id <= 0 or target.width <= 0 or target.height <= 0:
        raise ValueError("Invalid target window")
    _check_capture_target(target)
    with tempfile.TemporaryDirectory(prefix="gaze-window-") as directory:
        path = Path(directory) / "window.png"
        subprocess.run(["screencapture", "-x", "-o", "-l", str(target.window_id), str(path)],
                       check=True, timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        raw = path.read_bytes()
        if not raw:
            raise RuntimeError("Window capture returned no image")
        _check_capture_target(target)
        return raw


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
        if rep is None or not jpeg:
            raise RuntimeError("Could not decode the window image")
        size = (int(rep.pixelsWide()), int(rep.pixelsHigh()))
        if min(size) <= 0 or max(size) > 1280:
            raise RuntimeError("Invalid downscaled image dimensions")
        return jpeg, size


class AutoOCR:
    """A global Auto capture budget; failed attempts also consume the minute."""

    def __init__(self, *, clock=None):
        self.clock = clock or time.monotonic
        self.last_attempt = float("-inf")
        self.window_key: str | None = None
        self.identity: ax.WindowIdentity | None = None
        self.elements: list[Element] = []

    def _cached(self, key: str, identity: ax.WindowIdentity | None) -> list[Element]:
        same_window = (self.identity is None and identity is None or
                       self.identity is not None and identity is not None and self.identity.same_window(identity))
        return list(self.elements) if key == self.window_key and same_window else []

    def read(self, window_key: str) -> list[Element]:
        from gaze_agent.auto import normalize_window_key
        from gaze_agent.screen.ocr import recognize
        key = normalize_window_key(window_key)
        read = ax.current_read()
        if read is not None:
            read.verify()
        identity = read.identity if read is not None else None
        now = self.clock()
        if now - self.last_attempt < 60:
            return self._cached(key, identity)
        self.last_attempt = now
        try:
            target = target_window()
            jpeg, _ = vision_image(capture_window(target))
            elements = recognize(jpeg, target, fast=True)
            if read is not None:
                read.verify()
        except ax.WindowChanged:
            # Never disguise a switch as an ordinary OCR failure or reuse its cache.
            self.window_key, self.identity, self.elements = None, None, []
            raise
        except Exception:
            return self._cached(key, identity)
        self.window_key, self.identity, self.elements = key, identity, elements
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
        if isinstance(xy, list) and len(xy) == 2 and all(type(v) in (int, float) for v in xy):
            if 0 <= xy[0] < size[0] and 0 <= xy[1] < size[1]:
                point = (target.x + min(target.width - 1, round(xy[0] * target.width / size[0])),
                         target.y + min(target.height - 1, round(xy[1] * target.height / size[1])))
        text = answer
    except (ValueError, KeyError, TypeError):
        pass
    return LookResult(text, point)
