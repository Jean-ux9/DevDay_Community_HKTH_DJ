import pytest

from gaze_agent import actions, llm, permissions
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


@pytest.fixture(autouse=True)
def prohibit_live_rehearsal_and_openai(monkeypatch):
    # Rehearsal app preparation lives outside DesktopActions. Block it too;
    # tests must explicitly inject a fixture preparer or use --target fake.
    # Keep this separate from prohibit_real_desktop, which the cost tests reuse
    # while exercising the real wrapper against their own fake API transport.
    import sys
    from pathlib import Path
    scripts = str(Path(__file__).resolve().parents[3] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import rehearse
    async def forbidden_async(*args, **kwargs):
        raise AssertionError("Runtime tests must use fake desktop preparation and fake OpenAI")
    monkeypatch.setattr(rehearse, "prepare_app", forbidden_async)
    monkeypatch.setattr(rehearse, "activate_app", forbidden_async)
    monkeypatch.setattr(llm, "_live", forbidden_async)
