"""Cancellable macOS action driver. Native imports/actions are deferred to calls."""
from __future__ import annotations

import asyncio
import subprocess
import threading
import time
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
MODIFIERS = {55: "kCGEventFlagMaskCommand", 56: "kCGEventFlagMaskShift",
             58: "kCGEventFlagMaskAlternate", 59: "kCGEventFlagMaskControl"}
APP_ACTIVATION_TIMEOUT_S = 10.0


def _key_flags(quartz, codes):
    flags = 0
    for code in codes:
        if code in MODIFIERS:
            flags |= getattr(quartz, MODIFIERS[code])
    return flags


class ActionCancelled(Exception):
    pass


class DesktopActions:
    def __init__(self, profile: dict):
        self.profile = profile
        self.cancelled = threading.Event()
        self.held: list[int] = []
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
                # Release the character before its modifiers, keeping flags
                # accurate until the corresponding modifier itself goes up.
                while self.held:
                    code = self.held.pop()
                    event = Q.CGEventCreateKeyboardEvent(None, code, False)
                    Q.CGEventSetFlags(event, _key_flags(Q, self.held))
                    Q.CGEventPost(Q.kCGHIDEventTap, event)

    async def run(self, name: str, args: dict, snapshot):
        self._alive()
        return await asyncio.to_thread(self._dispatch, name, args, snapshot)

    def _dispatch(self, name, args, snapshot):
        self._alive()
        if name in {"click_element", "type_text", "press_keys"}:
            ax.verify_snapshot(snapshot.snapshot_id)
            self._alive()
        if name == "click_element":
            self.click_element(args["id"], args["snapshot_id"])
        elif name == "type_text":
            self.type_text(args["text"], args.get("id"), args.get("snapshot_id", snapshot.snapshot_id))
            if args.get("submit", False):
                self._alive()
                ax.verify_snapshot(snapshot.snapshot_id)
                self._alive()
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
        self._alive()
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
            ax.verify_snapshot(snapshot_id)
            self._alive()
            Q.CGEventPost(Q.kCGHIDEventTap, down)
            Q.CGEventPost(Q.kCGHIDEventTap, up)
        except (ImportError, AttributeError):
            self._alive()
            ax.verify_snapshot(snapshot_id)
            self._alive()
            import pyautogui
            pyautogui.click(*center)

    def press_keys(self, keys):
        import Quartz as Q
        codes = list(dict.fromkeys(KEYS[key.lower()] for key in keys))  # validate before any key goes down
        codes = [code for code in codes if code in MODIFIERS] + [code for code in codes if code not in MODIFIERS]
        try:
            for code in codes:
                with self.lock:
                    self._alive()
                    event = Q.CGEventCreateKeyboardEvent(None, code, True)
                    Q.CGEventSetFlags(event, _key_flags(Q, [*self.held, code]))
                    self._alive()
                    self.held.append(code)
                    Q.CGEventPost(Q.kCGHIDEventTap, event)
        finally:
            self.release_keys()

    def type_text(self, text, element_id=None, snapshot_id=None):
        import ApplicationServices as AX
        from AppKit import NSPasteboard, NSPasteboardItem, NSPasteboardTypeString
        self._alive()
        if snapshot_id is not None:
            ax.verify_snapshot(snapshot_id)
        context = ax.snapshot_context(snapshot_id)
        identity = context[0] if context is not None else None
        if element_id:
            element, handle = ax.resolve(snapshot_id, element_id)
            if not element.enabled:
                raise ValueError("element_disabled")
            if element.source == "ax" and element.role not in {
                    "AXTextField", "AXTextArea", "AXSearchField", "AXComboBox", "AXSecureTextField"}:
                raise ValueError("element_not_editable")
        else:
            app, root, window = ax.front_window()
            current = ax.window_identity(app, window)
            handle = ax.attribute(root, "AXFocusedUIElement")
            if identity is not None and (current != identity or handle != context[1]):
                ax.invalidate()
                raise ax.WindowChanged()
            identity = current
            if handle is None:
                ax.invalidate()
                raise ValueError("cannot_focus_text_target")
        if handle is not None:
            self._alive()
            focused = AX.AXUIElementSetAttributeValue(handle, "AXFocused", True) == 0
            self._alive()
            if AX.AXUIElementSetAttributeValue(handle, "AXValue", text) == 0:
                return
            if not focused:
                if not element_id:
                    raise ValueError("cannot_focus_text_target")
                self.click_element(element_id, snapshot_id)
        elif element_id:
            self.click_element(element_id, snapshot_id)

        def verify_focus():
            self._alive()
            if identity is None:
                return handle  # Injected fixture snapshots have no native identity.
            try:
                app, root, window = ax.front_window()
                focused = ax.attribute(root, "AXFocusedUIElement")
                if (ax.window_identity(app, window) != identity or focused is None
                        or (handle is not None and focused != handle)):
                    raise ax.WindowChanged()
                return focused
            except (RuntimeError, OSError) as error:
                ax.invalidate()
                raise ax.WindowChanged() from error

        # A successful focus request alone does not prove where global keys go.
        # Pin the live focus after any intentional click, then recheck around
        # clipboard work, which may block while another app becomes active.
        handle = verify_focus()
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
        verify_focus()
        wrote = False
        try:
            board.clearContents()
            wrote = bool(board.setString_forType_(text, NSPasteboardTypeString))
            if wrote:
                verify_focus()
                self.press_keys(["cmd", "v"])
                # Give the target time to consume the paste; STOP wakes this wait.
                self.cancelled.wait(0.12)
                verify_focus()
                return
        finally:
            board.clearContents()
            if saved:
                board.writeObjects_(saved)
        if not wrote:
            self._alive()
            import pyautogui
            for character in text:
                verify_focus()
                pyautogui.write(character)

    def open_app(self, name):
        from AppKit import NSWorkspace
        from Foundation import NSBundle
        aliases = {"music": "Music", "browser": "Safari", "messages": "Messages", "mail": "Mail",
                   "textedit": "TextEdit"}
        # The frozen Profile has no app_aliases field; string-valued contact aliases
        # must not be repurposed as application names.
        self._alive()
        path = NSWorkspace.sharedWorkspace().fullPathForApplication_(aliases.get(name.lower(), name))
        if not path:
            raise ValueError("application_not_found")
        bundle = NSBundle.bundleWithPath_(path)
        bundle_id = bundle.bundleIdentifier() if bundle is not None else None
        if not bundle_id:
            raise ValueError("application_bundle_unavailable")
        self._alive()
        ax.invalidate()
        deadline = time.monotonic() + APP_ACTIVATION_TIMEOUT_S
        # Use the system launcher, then observe actual AX focus. A successful
        # launch request alone does not establish that the app/window is ready.
        process = subprocess.Popen(["/usr/bin/open", "-a", str(path)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            while True:
                self._alive()
                status = process.poll()
                if status is not None:
                    if status != 0:
                        raise ValueError("application_launch_failed")
                    try:
                        app, _, window = ax.front_window()
                        if app.bundleIdentifier() == bundle_id and window is not None:
                            self._alive()
                            return
                    except (RuntimeError, OSError):
                        pass  # A launching app may not have its first window yet.
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError("application_activation_timeout")
                self.cancelled.wait(min(0.05, remaining))
        finally:
            if process.poll() is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass  # It exited between poll and kill; still reap it.
                process.wait()

    def open_url(self, url):
        if urlparse(url).scheme not in {"http", "https"}:
            raise ValueError("unsupported_url_scheme")
        self._alive()
        subprocess.run(["open", url], check=True, timeout=5)
