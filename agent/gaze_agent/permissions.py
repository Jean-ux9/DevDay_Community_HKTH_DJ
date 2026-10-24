"""Non-prompting checks; prompt only after explicit Settings actions."""
from __future__ import annotations
import subprocess

_screen_requested = False
PANES = {
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "screen_recording": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
    "camera": "x-apple.systempreferences:com.apple.preference.security?Privacy_Camera",
}


def check() -> dict:
    try:
        import ApplicationServices as AX
        import Quartz
        accessibility = bool(AX.AXIsProcessTrusted())
        recording = bool(Quartz.CGPreflightScreenCaptureAccess())
    except (ImportError, AttributeError):
        accessibility = recording = False
    return {"accessibility": accessibility, "screen_recording": recording, "camera": "unknown"}


def open_settings_pane(pane: str) -> None:
    global _screen_requested
    url = PANES[pane]
    if pane == "screen_recording" and not _screen_requested:
        _screen_requested = True
        import Quartz
        Quartz.CGRequestScreenCaptureAccess()
    subprocess.run(["open", url], check=True, timeout=5)
