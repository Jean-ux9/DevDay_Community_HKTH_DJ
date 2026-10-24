"""The no-desktop C2-C3 runner uses the fixture without changing a user profile."""
import asyncio
import copy
import importlib.util
import json

import pytest

from gaze_agent import llm, planner, profile
from gaze_agent.contracts import LLMError
from gaze_agent.protocol import Plan


def runner(name="check_planner"):
    path = llm.ROOT / f"agent/replay/{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fixture_runner_records_and_compares_without_loading_active_profile(monkeypatch, tmp_path, persona):
    module = runner()
    monkeypatch.setattr(module, "EXPECTED", tmp_path / "expected.json")
    seen = []

    async def make_plans(text, demo, snapshot):
        seen.append(copy.deepcopy(profile.load_profile()))
        assert demo == persona and snapshot is None
        return [Plan(id="p1", label="Find Taylor Swift Ticketmaster tickets", kind="task", risky=False),
                planner.OTHER]

    async def decode(words, raw, context, demo):
        assert demo == persona and words == ["tell", "mom"] and raw == [["GHI", "ABC"]]
        return ["Tell Mom ha."]

    def forbidden():
        raise AssertionError("The active user profile must not be loaded")

    monkeypatch.setattr(planner, "make_plans", make_plans)
    monkeypatch.setattr(planner, "decode", decode)
    monkeypatch.setattr(profile, "load_profile", forbidden)
    expected = asyncio.run(module.check("record"))
    assert asyncio.run(module.check("replay")) == expected
    assert seen == [persona, persona]
    assert profile.load_profile is forbidden
    changed = {**expected, "sentences": ["different"]}
    module.EXPECTED.write_text(json.dumps(changed))
    with pytest.raises(LLMError, match="differs"):
        asyncio.run(module.check("replay"))


def test_shipped_demo_cache_replays_without_api_or_active_profile(monkeypatch):
    monkeypatch.setattr(llm, "CACHE_DIR", llm.ROOT / "agent/replay/cache")
    monkeypatch.setenv("REPLAY", "replay")
    monkeypatch.setenv("DEMO_MODE", "1")
    for slot, effort in (("AGENT", "xhigh"), ("FAST", "low"), ("VISION", "xhigh")):
        monkeypatch.setenv(f"OPENAI_MODEL_{slot}", "gpt-6.1-sol")
        monkeypatch.setenv(f"OPENAI_REASONING_EFFORT_{slot}", effort)

    def forbidden(*args, **kwargs):
        raise AssertionError("Offline demo checks must not use HTTP or the active user profile")

    monkeypatch.setattr(llm, "AsyncOpenAI", forbidden)
    monkeypatch.setattr(profile, "load_profile", forbidden)
    for name in ("check_planner", "check_prompts"):
        module = runner(name)
        assert asyncio.run(module.check("replay")) == json.loads(module.EXPECTED.read_text())
