import asyncio
import json
from types import SimpleNamespace

import pytest

from tests.runtime.support import ROOT  # also exposes the standalone mock on sys.path
import fake_agent
import wsproto


@pytest.mark.parametrize("ambient,initial", [("0", 0), ("1", 1), (None, 0)])
def test_mock_ambient_default_and_manual_cooldown(monkeypatch, ambient, initial):
    if ambient is None:
        monkeypatch.delenv("GAZE_AUTO_AMBIENT", raising=False)
    else:
        monkeypatch.setenv("GAZE_AUTO_AMBIENT", ambient)
    now, messages = [0.0], []
    monkeypatch.setattr(fake_agent, "time", SimpleNamespace(monotonic=lambda: now[0]))
    class Socket:
        async def send(self, raw):
            messages.append(json.loads(raw))
    async def scenario():
        session = fake_agent.Session(Socket(), delay=0, demo_mode=True, quiet=True)
        await session.on_hello({}, wsproto.new_id())
        suggestions = lambda: [msg for msg in messages if msg["type"] == "suggestions"]
        assert len(suggestions()) == initial
        await session.on_gaze_context({"dock_idle": True, "idle_ms": 1500}, wsproto.new_id())
        assert len(suggestions()) == initial
        await session.on_auto_refresh({}, wsproto.new_id())
        assert len(suggestions()) == initial + 1
        assert suggestions()[-1]["payload"]["app"] == "Mail"
        now[0] = 2.99
        await session.on_auto_refresh({}, wsproto.new_id())
        assert len(suggestions()) == initial + 1
        now[0] = 3
        await session.on_auto_refresh({}, wsproto.new_id())
        assert len(suggestions()) == initial + 2
    asyncio.run(scenario())
