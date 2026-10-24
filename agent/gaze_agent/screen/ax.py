"""Bounded AX traversal and pure fixture compaction; no desktop work on import."""
from __future__ import annotations
import threading
import uuid
from typing import Any
from gaze_agent.contracts import Element, Snapshot, WindowInfo

_lock = threading.Lock()
_latest: Snapshot | None = None
_handles: dict[str, Any] = {}
INTERACTIVE = {"AXButton", "AXTextField", "AXTextArea", "AXComboBox", "AXCheckBox", "AXRadioButton",
               "AXLink", "AXMenuItem", "AXPopUpButton", "AXSlider", "AXTab", "AXDisclosureTriangle"}


def publish(snapshot: Snapshot, handles: dict | None = None) -> Snapshot:
    global _latest, _handles
    with _lock:
        _latest, _handles = snapshot, handles or {}
    return snapshot


def resolve(snapshot_id: str, element_id: str) -> tuple[Element, Any]:
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
    elements, handles, focused = [], {}, None
    pending, visited = [tree], 0
    while pending and visited < 3000:
        node = pending.pop()
        visited += 1
        pending.extend(reversed(node.get("children", [])))
        role = str(node.get("role", ""))
        label = str(node.get("label") or node.get("description") or "").replace("\n", " ")
        is_focused = bool(node.get("focused")) or (focused_key is not None and node.get("key") == focused_key)
        bbox = tuple(int(v) for v in node.get("bbox", (0, 0, 0, 0)))
        if node.get("hidden", False) or len(bbox) != 4:
            continue
        if not (is_focused or label or role in INTERACTIVE):
            continue
        if len(elements) >= limit and not is_focused:
            continue
        element = Element(f"e{visited}", role, label, str(node.get("description", "")),
                          bool(node.get("enabled", True)), bbox, "ax")
        if len(elements) >= limit:
            removed = elements.pop()
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
    from AppKit import NSWorkspace
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        raise RuntimeError("No frontmost application")
    root = AX.AXUIElementCreateApplication(app.processIdentifier())
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


def read_snapshot(*, limit: int = 150) -> tuple[Snapshot, dict]:
    app, root, window = front_window()
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
        if not title and role in {"AXStaticText", "AXLink"}:
            title = attribute(handle, "AXValue", "")
        return {"role": role, "label": str(title), "description": str(attribute(handle, "AXDescription", "")),
                "enabled": bool(attribute(handle, "AXEnabled", True)), "bbox": (*pos, *size),
                "focused": handle == focus, "handle": handle,
                "hidden": bool(attribute(handle, "AXHidden", False)),
                "children": [walk(child, depth + 1) for child in attribute(handle, "AXChildren", [])]}

    tree = walk(window)
    if focus is not None and hash(focus) not in seen:
        count = min(count, 2999)
        tree["children"].append(walk(focus))
    url = attribute(window, "AXDocument")
    return compact_tree(tree, app=str(app.localizedName()), bundle_id=str(app.bundleIdentifier() or ""),
                        window_title=str(attribute(window, "AXTitle", "")),
                        url=str(url) if url else None, limit=limit)


def window_info() -> WindowInfo:
    snapshot, _ = read_snapshot(limit=200)
    return WindowInfo(snapshot.bundle_id, snapshot.app, snapshot.window_title,
                      snapshot.bundle_id + "|" + snapshot.window_title,
                      [e.role + "|" + e.label for e in snapshot.elements][:200])
