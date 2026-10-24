"""Cancellable macOS action driver. Native imports/actions are deferred to calls."""
from __future__ import annotations

import asyncio
import subprocess
import threading
from urllib.parse import urlparse

from gaze_agent.screen import ax

KEYS = {"enter": 36, "return": 36, "tab": 48, "space": 49, "backspace": 51, "delete": 51,
        "escape": 53, "esc": 53, "cmd": 55, "command": 55, "shift": 56, "alt": 58,
        "option": 58, "ctrl": 59, "control": 59, "left": 123, "right": 124, "down": 125,
        "up": 126, "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6,
        "x": 7, "c": 8, "v": 9, "b": 11, "q": 12, "w": 13, "e": 14, "r": 15,
        "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23,
        "9": 25, "7": 26, "8": 28, "0": 29, "o": 31, "u": 32, "i": 34, "p": 35,
        "l": 37, "j": 38, "k": 40, "n": 45, "m": 46, "period": 47}


class ActionCancelled(Exception):
    pass


class DesktopActions:
    def __init__(self, profile: dict):
        self.profile = profile
        self.cancelled = threading.Event()
        self.held: set[int] = set()
        self.lock = threading.RLock()

    def _alive(self):
        if self.cancelled.is_set():
            raise ActionCancelled("task stopped")

    def cancel(self):
        self.cancelled.set()

    def release_keys(self):
        # Never import Quartz or post events when no keys were held.
        with self.lock:
            if self.held:
                import Quartz as Q
                for code in list(self.held):
                    Q.CGEventPost(Q.kCGHIDEventTap, Q.CGEventCreateKeyboardEvent(None, code, False))
                self.held.clear()

    async def run(self, name: str, args: dict, snapshot):
        self._alive()
        return await asyncio.to_thread(self._dispatch, name, args, snapshot)

    def _dispatch(self, name, args, snapshot):
        self._alive()
        if name == "click_element":
            self.click_element(args["id"], args["snapshot_id"])
        elif name == "type_text":
            self.type_text(args["text"], args.get("id"), args.get("snapshot_id"))
            if args.get("submit", False):
                self.press_keys(["enter"])
        elif name == "press_keys":
            self.press_keys(args["keys"])
        elif name == "open_app":
            self.open_app(args["name"])
        elif name == "open_url":
            self.open_url(args["url"])
        else:
            raise ValueError("unknown_tool")
        return {"ok": True}

    def click_element(self, element_id, snapshot_id):
        import ApplicationServices as AX
        element, handle = ax.resolve(snapshot_id, element_id)
        if not element.enabled:
            raise ValueError("element_disabled")
        self._alive()
        if handle is not None and AX.AXUIElementPerformAction(handle, "AXPress") == 0:
            return
        self._alive()
        x, y, width, height = element.bbox
        if width <= 0 or height <= 0:
            raise ValueError("element_has_no_bounds")
        center = (x + width / 2, y + height / 2)
        try:
            import Quartz as Q
            down = Q.CGEventCreateMouseEvent(None, Q.kCGEventLeftMouseDown, center, Q.kCGMouseButtonLeft)
            up = Q.CGEventCreateMouseEvent(None, Q.kCGEventLeftMouseUp, center, Q.kCGMouseButtonLeft)
            self._alive()
            Q.CGEventPost(Q.kCGHIDEventTap, down)
            Q.CGEventPost(Q.kCGHIDEventTap, up)
        except (ImportError, AttributeError):
            self._alive()
            import pyautogui
            pyautogui.click(*center)

    def press_keys(self, keys):
        import Quartz as Q
        codes = [KEYS[key.lower()] for key in keys]  # validate before any key goes down
        flags = 0
        modifiers = {55: Q.kCGEventFlagMaskCommand, 56: Q.kCGEventFlagMaskShift,
                     58: Q.kCGEventFlagMaskAlternate, 59: Q.kCGEventFlagMaskControl}
        try:
            for code in codes:
                with self.lock:
                    self._alive()
                    flags |= modifiers.get(code, 0)
                    event = Q.CGEventCreateKeyboardEvent(None, code, True)
                    Q.CGEventSetFlags(event, flags)
                    self.held.add(code)
                    Q.CGEventPost(Q.kCGHIDEventTap, event)
        finally:
            self.release_keys()

    def type_text(self, text, element_id=None, snapshot_id=None):
        import ApplicationServices as AX
        from AppKit import NSPasteboard, NSPasteboardItem, NSPasteboardTypeString
        self._alive()
        if element_id:
            _, handle = ax.resolve(snapshot_id, element_id)
        else:
            _, root, _ = ax.front_window()
            handle = ax.attribute(root, "AXFocusedUIElement")
        if handle is not None:
            self._alive()
            AX.AXUIElementSetAttributeValue(handle, "AXFocused", True)
            self._alive()
            if AX.AXUIElementSetAttributeValue(handle, "AXValue", text) == 0:
                return
        elif element_id:
            self.click_element(element_id, snapshot_id)
        self._alive()
        board = NSPasteboard.generalPasteboard()
        # Deep-copy every pasteboard item/type, including non-text content.
        saved = []
        for item in board.pasteboardItems() or []:
            clone = NSPasteboardItem.alloc().init()
            for kind in item.types():
                data = item.dataForType_(kind)
                if data is not None:
                    clone.setData_forType_(data, kind)
            saved.append(clone)
        wrote = False
        try:
            board.clearContents()
            wrote = bool(board.setString_forType_(text, NSPasteboardTypeString))
            if wrote:
                self.press_keys(["cmd", "v"])
                # Give the target time to consume the paste; STOP wakes this wait.
                self.cancelled.wait(0.12)
                self._alive()
                return
        finally:
            board.clearContents()
            if saved:
                board.writeObjects_(saved)
        if not wrote:
            self._alive()
            import pyautogui
            for character in text:
                self._alive()
                pyautogui.write(character)

    def open_app(self, name):
        from AppKit import NSWorkspace
        aliases = {"music": "Music", "browser": "Safari", "messages": "Messages", "mail": "Mail"}
        # The frozen Profile has no app_aliases field; string-valued contact aliases
        # must not be repurposed as application names.
        self._alive()
        if not NSWorkspace.sharedWorkspace().launchApplication_(aliases.get(name.lower(), name)):
            raise ValueError("application_not_found")

    def open_url(self, url):
        if urlparse(url).scheme not in {"http", "https"}:
            raise ValueError("unsupported_url_scheme")
        self._alive()
        subprocess.run(["open", url], check=True, timeout=5)
