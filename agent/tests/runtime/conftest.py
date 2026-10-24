import pytest

from gaze_agent import actions, permissions
from gaze_agent.screen import ax, shot


@pytest.fixture(autouse=True)
def prohibit_real_desktop(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Runtime tests must never touch the real desktop")
    monkeypatch.setattr(ax, "front_window", forbidden)
    monkeypatch.setattr(shot, "capture_window", forbidden)
    monkeypatch.setattr(actions.DesktopActions, "_dispatch", forbidden)
    monkeypatch.setattr(permissions, "open_settings_pane", forbidden)
    monkeypatch.setattr(permissions, "check", lambda: {
        "accessibility": True, "screen_recording": True, "camera": "unknown"})
