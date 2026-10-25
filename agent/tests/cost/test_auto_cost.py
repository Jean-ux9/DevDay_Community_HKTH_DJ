import asyncio
import json
from dataclasses import replace

import pytest

from gaze_agent import auto, llm, server
from gaze_agent.contracts import LLMError, Snapshot, WindowInfo
from gaze_agent.profile import ProfileStore
from tests.brain.test_auto import Rig


def test_default_off_polls_without_screen_or_model(monkeypatch, persona):
    async def scenario():
        rig = Rig(monkeypatch, persona)
        monkeypatch.delenv("GAZE_AUTO_AMBIENT", raising=False)
        polls = []
        def info():
            polls.append(rig.now)
            return rig.info
        def screen():
            raise AssertionError("On-demand idle must never read a screenshot")
        rig.watcher = auto.AutoWatcher(rig.emit, info, screen, lambda: persona, clock=lambda: rig.now)
        for at, title in [(0, "Inbox"), (2, "Sent"), (25, "Drafts"), (27, "Drafts")]:
            rig.window(title)
            await rig.tick(at)
        assert polls == [0, 2, 25, 27] and not rig.calls
        rig.watcher.get_screen = rig.screen
        rig.watcher.refresh()
        await rig.tick(27)
        assert len(rig.calls) == 1
        rig.window("Other")
        await rig.tick(60)
        await rig.tick(62)
        assert len(rig.calls) == 1
    asyncio.run(scenario())


def test_title_normalization_and_cache(monkeypatch, persona):
    async def scenario():
        rig = Rig(monkeypatch, persona)
        rig.window(" Inbox (3) 2026 ")
        await rig.tick(0)
        await rig.tick(1.5)
        assert rig.emissions[-1][0] == "fake.app|inbox"
        rig.window("INBOX (4) 2027")
        await rig.tick(30)
        await rig.tick(32)
        assert len(rig.calls) == 1
        rig.window("Sent")
        await rig.tick(33)
        await rig.tick(34.5)
        assert len(rig.calls) == 2
        rig.window("Inbox (5)")
        await rig.tick(35)
        await rig.tick(36.5)
        assert len(rig.calls) == 2 and rig.emissions[-1][-1] is True
    asyncio.run(scenario())


@pytest.mark.parametrize("new_chars,expected", [(35, 1), (39, 1), (40, 2), (70, 2)])
def test_35_percent_requires_40_new_label_characters(monkeypatch, persona, new_chars, expected):
    async def scenario():
        rig = Rig(monkeypatch, persona)
        original = [f"AXText|old {i}" for i in range(20)]
        rig.info = replace(rig.info, element_sigs=original)
        await rig.tick(0)
        await rig.tick(1.5)
        size, extra = divmod(new_chars, 7)
        new = ["AXText|" + (chr(65 + i) * (size + (i < extra))) for i in range(7)]
        rig.info = replace(rig.info, element_sigs=original[:13] + new)
        await rig.tick(23)
        await rig.tick(24.5)
        assert len(rig.calls) == expected
    asyncio.run(scenario())


@pytest.mark.parametrize("gap,expected", [(10, 1), (21, 2)])
def test_ambient_cooldown_between_windows(monkeypatch, persona, gap, expected):
    async def scenario():
        rig = Rig(monkeypatch, persona)
        await rig.tick(0)
        await rig.tick(1.5)
        rig.window("B")
        await rig.tick(gap)
        await rig.tick(gap + 1.5)
        assert len(rig.calls) == expected
    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["screen", "llm", "window"])
def test_failed_attempt_still_waits_20_seconds(monkeypatch, persona, failure):
    async def scenario():
        rig = Rig(monkeypatch, persona)
        attempts = []
        def screen():
            attempts.append(rig.now)
            if failure == "screen":
                raise RuntimeError("fake capture failure")
            snapshot = rig.screen()
            return replace(snapshot, window_title="B") if failure == "window" else snapshot
        async def complete(*args, **kwargs):
            raise LLMError("fake API failure")
        rig.watcher.get_screen = screen
        monkeypatch.setattr(llm, "complete", complete)
        await rig.tick(0)
        for at in (1.5, 2.5, 3.5, 20.5, 21.5):
            try:
                await rig.tick(at)
            except (RuntimeError, LLMError):
                pass
        assert attempts == [1.5, 21.5]
    asyncio.run(scenario())


def test_refresh_has_independent_three_second_gap(monkeypatch, persona):
    async def scenario():
        rig = Rig(monkeypatch, persona)
        await rig.tick(0)
        await rig.tick(1.5)
        rig.now = 2
        rig.watcher.refresh()
        await rig.tick(2)
        assert len(rig.calls) == 2
        rig.watcher.refresh()
        await rig.tick(2.5)
        rig.now = 4.99
        rig.watcher.refresh()
        await rig.tick(4.99)
        assert len(rig.calls) == 2
        rig.now = 5
        rig.watcher.refresh()
        await rig.tick(5)
        assert len(rig.calls) == 3
    asyncio.run(scenario())


def test_failed_manual_request_does_not_retry_by_itself(monkeypatch, persona):
    async def scenario():
        rig = Rig(monkeypatch, persona)
        rig.watcher.ambient = False
        attempts = []
        def screen():
            attempts.append(rig.now)
            raise RuntimeError("fake failure")
        rig.watcher.get_screen = screen
        rig.watcher.refresh()
        with pytest.raises(RuntimeError):
            await rig.tick(0)
        await rig.tick(2)
        await rig.tick(30)
        assert attempts == [0]
    asyncio.run(scenario())


@pytest.mark.parametrize("ambient", [True, False])
def test_refresh_during_inflight_call_uses_its_result_without_a_second_call(monkeypatch, persona, ambient):
    async def scenario():
        rig = Rig(monkeypatch, persona)
        rig.watcher.ambient = ambient
        started, release = asyncio.Event(), asyncio.Event()
        async def wait():
            started.set()
            await release.wait()
        rig.before_return = wait
        await rig.tick(0)
        if not ambient:
            rig.watcher.refresh()
        task = asyncio.create_task(rig.tick(1.5))
        await started.wait()
        rig.now = 5
        rig.watcher.refresh()  # "Suggest now" again while the paid answer is in flight.
        release.set()
        await task
        assert len(rig.calls) == 1 and len(rig.emissions) == 1
        await rig.tick(6)
        await rig.tick(30)
        assert len(rig.calls) == 1 and len(rig.emissions) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("new_title,expected", [("Inbox (4)", 1), ("Sent", 0)])
def test_session_normalizes_both_sides_after_watcher_emits(tmp_path, monkeypatch, persona, new_title, expected):
    async def scenario():
        rig = Rig(monkeypatch, persona)
        rig.window("Inbox (3)")
        messages = []
        class Socket:
            async def send(self, raw):
                messages.append(json.loads(raw))
        session = server.Session(Socket(), store=ProfileStore(tmp_path, demo=False),
                                 info=lambda: rig.info, screen=rig.screen)
        session.ready = True
        original_emit = session.suggestions
        async def emit(key, app, items, cached):
            # Change happens after the watcher's final check, before the server's AX read.
            rig.window(new_title)
            await original_emit(key, app, items, cached)
        rig.watcher.emit_suggestions = emit
        await rig.tick(0)
        await rig.tick(1.5)
        assert len(rig.calls) == 1 and len(messages) == expected
        if expected:
            assert messages[0]["payload"]["window_key"] == next(iter(rig.watcher._cache))[0] == "fake.app|inbox"
        # The server also accepts a raw key from a caller.
        rig.window(new_title)
        await session.suggestions("fake.app|Inbox (3)", "Fake", list(rig.watcher._cache.values())[0], False)
        assert len(messages) == expected * 2
    asyncio.run(scenario())
