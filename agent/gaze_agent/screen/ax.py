"""Bounded AX traversal and pure fixture compaction; no desktop work on import."""
from __future__ import annotations
import threading
import uuid
import math
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from gaze_agent.contracts import Element, Snapshot, WindowInfo

_lock = threading.Lock()
_latest: Snapshot | None = None
_handles: dict[str, Any] = {}
_identity: WindowIdentity | None = None
INTERACTIVE = {"AXButton", "AXTextField", "AXTextArea", "AXComboBox", "AXCheckBox", "AXRadioButton",
               "AXLink", "AXMenuItem", "AXPopUpButton", "AXSlider", "AXTab", "AXDisclosureTriangle",
               "AXSearchField"}


class WindowChanged(RuntimeError):
    def __init__(self):
        super().__init__("window_changed, re-read")


@dataclass(frozen=True)
class WindowIdentity:
    pid: int
    window: Any
    title: str
    bbox: tuple

    def same_window(self, other: WindowIdentity) -> bool:
        # Counters in titles may change between Auto reads; window handles and
        # geometry must still match before reusing screen-coordinate OCR boxes.
        return (self.pid == other.pid and self.window == other.window and self.bbox == other.bbox)


def window_identity(app, window) -> WindowIdentity:
    position = _point(attribute(window, "AXPosition"), "kAXValueCGPointType")
    size = _point(attribute(window, "AXSize"), "kAXValueCGSizeType")
    return WindowIdentity(app.processIdentifier(), window, str(attribute(window, "AXTitle", "")),
                          (*position, *size))


@dataclass
class ScreenRead:
    identity: WindowIdentity | None = None

    def check(self, app, window) -> None:
        identity = window_identity(app, window)
        if self.identity is None:
            self.identity = identity
        elif identity != self.identity:
            raise WindowChanged()

    def verify(self) -> None:
        if self.identity is not None:
            try:
                app, _, window = front_window()
                self.check(app, window)
            except (RuntimeError, OSError) as error:
                raise WindowChanged() from error


_screen_read: ContextVar[ScreenRead | None] = ContextVar("gaze_screen_read", default=None)


def current_read() -> ScreenRead | None:
    return _screen_read.get()


@contextmanager
def screen_read():
    """Share native window identity without changing the frozen Snapshot shape.

    Context-local state keeps concurrent reads separate. Injected zero-argument
    snapshot providers can still supply their own desktop-independent snapshots.
    """
    read = ScreenRead()
    token = _screen_read.set(read)
    try:
        yield read
    finally:
        _screen_read.reset(token)


def bounds(value) -> tuple[int, int, int, int] | None:
    try:
        if len(value) == 4 and all(math.isfinite(v) for v in value):
            x, y, width, height = (round(v) for v in value)
            if width >= 0 and height >= 0:
                return x, y, width, height
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def publish(snapshot: Snapshot, handles: dict | None = None) -> Snapshot:
    global _latest, _handles, _identity
    with _lock:
        _latest, _handles = snapshot, handles or {}
        read = current_read()
        _identity = read.identity if read else None
    return snapshot


def invalidate() -> None:
    global _latest, _handles, _identity
    with _lock:
        _latest, _handles, _identity = None, {}, None


def snapshot_context(snapshot_id: str):
    """Native identity stays internal; never put handles in the frozen Snapshot."""
    with _lock:
        if _latest is None or _latest.snapshot_id != snapshot_id or _identity is None:
            return None
        return _snapshot_context_unlocked()


def verify_snapshot(snapshot_id: str) -> None:
    with _lock:
        if _latest is None or _latest.snapshot_id != snapshot_id:
            raise ValueError("stale_snapshot, re-read")
        context = _snapshot_context_unlocked()
    if context is not None:
        identity, focused = context
        try:
            app, root, window = front_window()
            if (window_identity(app, window) != identity
                    or attribute(root, "AXFocusedUIElement") != focused):
                raise WindowChanged()
        except (RuntimeError, OSError) as error:
            invalidate()
            raise WindowChanged() from error
    with _lock:
        if _latest is None or _latest.snapshot_id != snapshot_id:
            raise ValueError("stale_snapshot, re-read")


def _snapshot_context_unlocked():
    if _latest is None or _identity is None:
        return None
    return _identity, _handles.get(_latest.focused.id) if _latest.focused else None


def resolve(snapshot_id: str, element_id: str) -> tuple[Element, Any]:
    verify_snapshot(snapshot_id)
    with _lock:
        if _latest is None or snapshot_id != _latest.snapshot_id:
            raise ValueError("stale_snapshot, re-read")
        element = next((e for e in _latest.elements if e.id == element_id), None)
        if element is None:
            raise ValueError("unknown_element")
        return element, _handles.get(element_id)


def compact_tree(tree: dict, *, app: str, bundle_id: str, window_title: str,
                 url: str | None = None, focused_key: str | None = None,
                 limit: int = 150) -> tuple[Snapshot, dict]:
    """Keep focus even when it appears after the first 150 elements."""
    if limit < 1:
        raise ValueError("limit must be positive")
    elements, handles, focused = [], {}, None
    seen_handles = set()
    pending, visited = [tree], 0
    while pending and visited < 3000:
        node = pending.pop()
        visited += 1
        if node.get("hidden", False):
            continue  # A hidden container's descendants aren't visible either.
        pending.extend(reversed(node.get("children", [])))
        if "handle" in node:
            key = hash(node["handle"])
            if key in seen_handles:
                continue
            seen_handles.add(key)
        role = str(node.get("role", ""))
        label = " ".join(str(node.get("label") or node.get("description") or "").split())
        is_focused = bool(node.get("focused")) or (focused_key is not None and node.get("key") == focused_key)
        bbox = bounds(node.get("bbox", (0, 0, 0, 0)))
        if bbox is None:
            continue
        if not (is_focused or label or role in INTERACTIVE):
            continue
        if len(elements) >= limit and not is_focused:
            continue
        element = Element(f"e{visited}", role, label, str(node.get("description", "")),
                          bool(node.get("enabled", True)), bbox, "ax")
        if len(elements) >= limit:
            # Multiple AX nodes may report focus; retain only the last one.
            removed = elements.pop(next((i for i, e in enumerate(elements) if e == focused), -1))
            handles.pop(removed.id, None)
        elements.append(element)
        if "handle" in node:
            handles[element.id] = node["handle"]
        if is_focused:
            focused = element
    return Snapshot(str(uuid.uuid4()), app, bundle_id, window_title, url, focused, elements), handles


def attribute(handle, name: str, default=None):
    import ApplicationServices as AX
    error, value = AX.AXUIElementCopyAttributeValue(handle, name, None)
    return value if error == 0 and value is not None else default


def front_window():
    import ApplicationServices as AX
    from AppKit import NSRunningApplication
    # NSWorkspace's foreground state depends on Cocoa's main run loop. This
    # asyncio process reads screens in worker threads and does not run that loop.
    # Ask AX for live focus, and use AppKit only for the PID's fixed metadata.
    root = attribute(AX.AXUIElementCreateSystemWide(), "AXFocusedApplication")
    if root is None:
        raise RuntimeError("No accessible focused application; check Accessibility permission")
    error, pid = AX.AXUIElementGetPid(root, None)
    if error != 0 or pid <= 0:
        raise RuntimeError("Could not identify the focused application")
    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if app is None:
        raise RuntimeError("Focused application is no longer running")
    window = attribute(root, "AXFocusedWindow")
    if window is None:
        raise RuntimeError("No accessible focused window; check Accessibility permission")
    return app, root, window


def _point(value, kind: str) -> tuple:
    import ApplicationServices as AX
    if value is None:
        return (0, 0)
    ok, result = AX.AXValueGetValue(value, getattr(AX, kind), None)
    return tuple(result) if ok else (0, 0)


def read_snapshot(*, limit: int = 150, dump: dict | None = None) -> tuple[Snapshot, dict]:
    app, root, window = front_window()
    read = current_read()
    if read is not None:
        read.check(app, window)
    focus = attribute(root, "AXFocusedUIElement")
    seen, count = set(), 0

    def walk(handle, depth=0):
        nonlocal count
        key = hash(handle)
        if key in seen or count >= 3000 or depth > 60:
            return {"children": []}
        seen.add(key)
        count += 1
        pos = _point(attribute(handle, "AXPosition"), "kAXValueCGPointType")
        size = _point(attribute(handle, "AXSize"), "kAXValueCGSizeType")
        role = str(attribute(handle, "AXRole", ""))
        title = attribute(handle, "AXTitle", "") or attribute(handle, "AXDescription", "")
        if not title and role in {"AXStaticText", "AXLink", "AXTextField", "AXTextArea", "AXSearchField"}:
            title = attribute(handle, "AXValue", "")
        hidden = bool(attribute(handle, "AXHidden", False))
        return {"role": role, "label": str(title), "description": str(attribute(handle, "AXDescription", "")),
                "enabled": bool(attribute(handle, "AXEnabled", True)), "bbox": (*pos, *size),
                "focused": handle == focus, "handle": handle,
                "hidden": hidden,
                "children": [] if hidden else [walk(child, depth + 1) for child in attribute(handle, "AXChildren", [])]}

    # Reserve focus before a large AXWebArea can exhaust the traversal budget.
    focus_node = walk(focus, depth=60) if focus is not None else None
    if focus is not None:
        # The focused node can itself be a web area. Still walk its descendants
        # normally when reaching it from the window.
        seen.discard(hash(focus))
    tree = walk(window)
    if focus_node is not None:
        tree["children"].insert(0, focus_node)
    url = attribute(window, "AXDocument")
    metadata = dict(app=str(app.localizedName()), bundle_id=str(app.bundleIdentifier() or ""),
                    window_title=str(attribute(window, "AXTitle", "")), url=str(url) if url else None)
    if dump is not None:
        dumped_handles = set()
        def serializable(node):
            key = hash(node["handle"]) if "handle" in node else None
            duplicate = key is not None and key in dumped_handles
            if key is not None:
                dumped_handles.add(key)
            if duplicate:
                return {"children": [serializable(child) for child in node.get("children", [])]}
            return {**{k: v for k, v in node.items() if k not in {"handle", "children"}},
                    "children": [serializable(child) for child in node.get("children", [])]}
        dump.update(**metadata, tree=serializable(tree))
    snapshot, handles = compact_tree(tree, **metadata, limit=limit)
    if read is not None:
        read.verify()
    return snapshot, handles


def window_info() -> WindowInfo:
    snapshot, _ = read_snapshot(limit=200)
    return WindowInfo(snapshot.bundle_id, snapshot.app, snapshot.window_title,
                      snapshot.bundle_id + "|" + snapshot.window_title,
                      [e.role + "|" + e.label for e in snapshot.elements][:200])
