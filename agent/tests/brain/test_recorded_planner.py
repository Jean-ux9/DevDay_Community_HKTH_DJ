"""The no-desktop C2-C3 runner uses the fixture without changing a user profile."""
import asyncio
import copy
import importlib.util
import json
import os
import sys

import pytest

from gaze_agent import demo_config, llm, planner, profile
from gaze_agent.contracts import LLMError
from gaze_agent.protocol import Plan


@pytest.fixture(autouse=True)
def no_inherited_private_selector(monkeypatch):
    monkeypatch.delenv(demo_config.SELECTOR_ENV, raising=False)


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


@pytest.mark.parametrize("name", ["check_planner", "check_prompts"])
def test_synthetic_checks_refuse_a_private_selector_before_any_call(monkeypatch, name):
    module = runner(name)
    monkeypatch.setenv(demo_config.SELECTOR_ENV, "/nonexistent/fake-private-demo.json")
    monkeypatch.setenv("REPLAY", "replay")
    monkeypatch.setenv("DEMO_MODE", "1")

    def forbidden(*args, **kwargs):
        raise AssertionError("A refused synthetic check must not reach the model or a profile")

    monkeypatch.setattr(llm, "AsyncOpenAI", forbidden)
    monkeypatch.setattr(profile, "load_profile", forbidden)
    monkeypatch.setattr(planner, "make_plans", forbidden)
    monkeypatch.setattr(llm, "complete", forbidden)
    with pytest.raises(LLMError, match="public fixture"):
        asyncio.run(module.check("replay"))


@pytest.mark.parametrize("name", ["check_planner", "check_prompts"])
def test_synthetic_check_cli_drops_a_private_selector(monkeypatch, capsys, name):
    module = runner(name)
    monkeypatch.setattr(module, "load_dotenv", lambda *args, **kwargs: None)  # never read a real .env
    seen = {}

    async def check(mode):
        seen.update(mode=mode, selector=os.environ.get(demo_config.SELECTOR_ENV),
                    key=os.environ.get("OPENAI_API_KEY"), demo=os.environ.get("DEMO_MODE"))
        return {}

    monkeypatch.setattr(module, "check", check)
    for variable, value in ((demo_config.SELECTOR_ENV, "/nonexistent/fake-private-demo.json"),
                            ("OPENAI_API_KEY", "fake-key"), ("REPLAY", "off"), ("DEMO_MODE", "0")):
        monkeypatch.setenv(variable, value)
    monkeypatch.setattr(sys, "argv", [f"{name}.py", "replay"])
    module.main()
    assert seen == {"mode": "replay", "selector": None, "key": None, "demo": "1"}
    assert f"{demo_config.SELECTOR_ENV} ignored" in capsys.readouterr().err
