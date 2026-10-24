import asyncio
import json
from dataclasses import replace

from gaze_agent import auto, llm
from gaze_agent.contracts import LLMError, LLMResponse, Snapshot, WindowInfo


class Rig:
    def __init__(self, monkeypatch, persona):
        self.now = 0.0
        self.info = WindowInfo("fake.app", "Fake", "A", "fake.app|A", [f"AXButton|{i}" for i in range(10)])
        self.persona = persona
        self.calls = []
        self.emissions = []
        self.before_return = None
        monkeypatch.setattr(auto.time, "monotonic", lambda: self.now)
        monkeypatch.setattr(llm, "complete", self.complete)
        self.watcher = auto.AutoWatcher(self.emit, lambda: self.info, self.screen, lambda: self.persona)

    def screen(self):
        return Snapshot("s", self.info.app, self.info.bundle_id, self.info.window_title, None, None)

    async def emit(self, *args):
        self.emissions.append(args)

    async def complete(self, *args):
        self.calls.append(args)
        if self.before_return:
            await self.before_return()
        return LLMResponse(json.dumps({"plans": [{"label": f"Open item {i}", "risky": False}
                                                 for i in range(3)]}), [], "r1", False)

    async def tick(self, at):
        self.now = at
        await self.watcher._tick()

    def window(self, title):
        self.info = replace(self.info, window_title=title, window_key="fake.app|" + title)


def test_debounce_interval_and_refresh(monkeypatch, persona):
    async def scenario():
        rig = Rig(monkeypatch, persona)
        await rig.tick(0)
        await rig.tick(1.49)
        assert not rig.calls
        await rig.tick(1.5)
        assert len(rig.calls) == 1
        rig.window("B")
        await rig.tick(2)
        await rig.tick(3.5)
        assert len(rig.calls) == 1
        rig.watcher.refresh()
        await rig.tick(3.6)
        assert len(rig.calls) == 2
        rig.window("C")
        await rig.tick(4)
        await rig.tick(13.59)
        assert len(rig.calls) == 2
        await rig.tick(13.6)
        assert len(rig.calls) == 3
    asyncio.run(scenario())


def test_returning_window_cache_and_lru(monkeypatch, persona):
    async def scenario():
        rig = Rig(monkeypatch, persona)
        for i in range(21):
            rig.window(str(i))
            await rig.tick(i * 12)
            await rig.tick(i * 12 + 1.5)
        assert len(rig.calls) == 21 and len(rig.watcher._cache) == 20
        rig.window("1")
        await rig.tick(242)
        await rig.tick(243.5)
        assert len(rig.calls) == 21 and rig.emissions[-1][-1] is True
        assert list(rig.watcher._cache)[-1][0] == "fake.app|1"
        rig.window("0")  # First inserted entry was evicted.
        await rig.tick(252)
        await rig.tick(253.5)
        assert len(rig.calls) == 22 and rig.emissions[-1][-1] is False
    asyncio.run(scenario())


def test_content_threshold_and_gaze(monkeypatch, persona):
    async def scenario():
        rig = Rig(monkeypatch, persona)
        await rig.tick(0)
        await rig.tick(2)
        rig.info = replace(rig.info, element_sigs=rig.info.element_sigs[:7] + ["new1", "new2", "new3"])
        rig.watcher.on_gaze_context(True, 1600)
        await rig.tick(12)
        await rig.tick(14)
        assert len(rig.calls) == 1  # Exactly 30% is not more than 30%.
        rig.info = replace(rig.info, element_sigs=rig.info.element_sigs[:6] + ["a", "b", "c", "d"])
        rig.watcher.on_gaze_context(False, 0)
        await rig.tick(15)
        await rig.tick(17)
        assert len(rig.calls) == 1
        rig.watcher.on_gaze_context(True, 1499)
        await rig.tick(18)
        assert len(rig.calls) == 1
        rig.watcher.on_gaze_context(True, 1500)
        await rig.tick(19)
        assert len(rig.calls) == 2
    asyncio.run(scenario())


def test_no_calls_in_type_or_running_task(monkeypatch, persona):
    async def scenario():
        rig = Rig(monkeypatch, persona)
        rig.watcher.set_mode("type")
        await rig.tick(0)
        await rig.tick(2)
        assert not rig.calls
        rig.watcher.set_mode("auto")
        rig.watcher.set_task_running(True)
        rig.watcher.refresh()
        await rig.tick(4)
        await rig.tick(6)
        assert not rig.calls
        rig.watcher.set_task_running(False)
        await rig.tick(8)
        await rig.tick(10)
        assert len(rig.calls) == 1
    asyncio.run(scenario())


def test_task_start_during_real_inflight_wait_drops_result(monkeypatch, persona):
    async def scenario():
        rig = Rig(monkeypatch, persona)
        started, release = asyncio.Event(), asyncio.Event()
        async def wait():
            started.set()
            await release.wait()
        rig.before_return = wait
        await rig.tick(0)
        task = asyncio.create_task(rig.tick(2))
        await started.wait()
        rig.watcher.set_task_running(True)
        rig.watcher.set_task_running(False)  # A task round-trip still invalidates.
        release.set()
        await task
        assert not rig.emissions and not rig.watcher._cache
    asyncio.run(scenario())


def test_stale_window_content_mode_and_profile_are_dropped(monkeypatch, persona):
    async def scenario(change):
        rig = Rig(monkeypatch, persona)
        async def mutate():
            if change == "window":
                rig.window("B")
            elif change == "content":
                rig.info = replace(rig.info, element_sigs=["new"])
            elif change == "mode":
                rig.watcher.set_mode("type")
                rig.watcher.set_mode("auto")
            else:
                rig.persona["name"] = "Changed demo name"
        rig.before_return = mutate
        await rig.tick(0)
        await rig.tick(2)
        assert not rig.emissions and not rig.watcher._cache
    for change in ("window", "content", "mode", "profile"):
        asyncio.run(scenario(change))


def test_run_polls_at_one_hz_and_cancels(monkeypatch, persona):
    async def scenario():
        rig = Rig(monkeypatch, persona)
        sleeps = []
        async def sleep(seconds):
            sleeps.append(seconds)
            rig.now += seconds
            if len(sleeps) == 4:
                raise asyncio.CancelledError
        monkeypatch.setattr(auto.asyncio, "sleep", sleep)
        try:
            await rig.watcher.run()
        except asyncio.CancelledError:
            pass
        assert sleeps == [1, 1, 1, 1]
        assert len(rig.calls) == 1
    asyncio.run(scenario())
