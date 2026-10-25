"""agent/replay/check_live_api.py with a fake SDK transport only.

No test reads the real .env or active profile or reaches the network. The live
mode itself is human-run; see the script's docstring for the command.
"""
import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import httpx2
import pytest
from openai import AsyncOpenAI

from gaze_agent import demo_config, llm, profile
from gaze_agent.contracts import LLMError
from gaze_agent.llm import MeasuredResponse
from tests.runtime.conftest import prohibit_real_desktop  # noqa: F401  (autouse desktop guard)

SCRIPT = llm.ROOT / "agent/replay/check_live_api.py"
OUTPUTS = [
    {"plans": [{"label": "Find Taylor Swift Ticketmaster tickets", "detail": "Search events; no purchase."},
               {"label": "Buy Taylor Swift Ticketmaster tickets", "detail": "Ask before buying.", "risky": True}]},
    {"sentences": ["Tell Mom I'll be late."]},
    {"plans": [{"label": "Reply to Alex: noon works", "detail": "Quote: \"Noon works!\"", "risky": True},
               {"label": "Ask Alex where to meet", "risky": True}, {"label": "Open Calendar for Friday"}]},
    {"plans": [{"label": "Reply to Alex: noon works", "risky": True},
               {"label": "Click Antworten to reply"}, {"label": "Ask Alex where to meet", "risky": True}]},
]
# Run as a fresh interpreter with its own guards (the suite's guards stay in-process).
DRIVER = r"""
import os, runpy, sys
def guard(event, args):
    if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
        path = os.fsdecode(args[0])
        if os.path.basename(path) == ".env" or "GazeCopilot" in path:
            raise PermissionError("blocked private read")
    elif event.startswith("socket.") or event == "subprocess.Popen":
        raise PermissionError("blocked " + event)
sys.addaudithook(guard)
sys.argv = sys.argv[1:]
try:
    runpy.run_path(sys.argv[0], run_name="__main__")
finally:
    desktop = ("gaze_agent.screen", "gaze_agent.actions", "gaze_agent.auto", "gaze_agent.loop",
               "gaze_agent.server", "Quartz", "AppKit", "ApplicationServices", "Vision")
    print("LOADED", [name for name in desktop if name in sys.modules])
"""


def runner():
    spec = importlib.util.spec_from_file_location("check_live_api", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_api(monkeypatch):
    api = SimpleNamespace(requests=[], outputs=list(OUTPUTS), usage=True)

    async def respond(request):
        api.requests.append(json.loads(request.content))
        n = len(api.requests)
        data = {"id": f"resp_fake_{n}", "object": "response", "created_at": 0, "status": "completed",
                "output": [{"type": "message", "id": f"m{n}", "status": "completed", "role": "assistant",
                            "content": [{"type": "output_text", "text": json.dumps(api.outputs[n - 1]),
                                         "annotations": []}]}]}
        if api.usage:
            data["usage"] = {"input_tokens": 100 * n, "output_tokens": 10 * n, "total_tokens": 110 * n,
                             "input_tokens_details": {"cached_tokens": 0},
                             "output_tokens_details": {"reasoning_tokens": 0}}
        return httpx2.Response(200, json=data)

    def client(**kwargs):
        return AsyncOpenAI(**kwargs, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)))

    monkeypatch.setattr(llm, "AsyncOpenAI", client)
    return api


@pytest.fixture
def live(monkeypatch):
    module = runner()
    loaded = []
    monkeypatch.setattr(module, "load_dotenv", lambda *args, **kwargs: loaded.append((args, kwargs)))
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT_FAST", "low")

    def forbidden(*args, **kwargs):
        raise AssertionError("The live check must not load the active profile")

    monkeypatch.setattr(profile, "load_profile", forbidden)
    monkeypatch.setattr(profile.ProfileStore, "load_profile", forbidden)
    return SimpleNamespace(module=module, loaded=loaded)


def test_default_and_help_make_no_call_and_read_no_env(capsys, live):
    with pytest.raises(SystemExit) as exit:
        live.module.main([])
    assert exit.value.code == 2 and "NOT RUN" in capsys.readouterr().err
    with pytest.raises(SystemExit) as exit:
        live.module.main(["--help"])
    assert exit.value.code == 0 and "--live" in capsys.readouterr().out
    assert live.loaded == []


@pytest.mark.parametrize("args,code", [([], 2), (["--help"], 0)])
def test_fresh_process_import_help_and_default_stay_offline_and_desktop_free(tmp_path, args, code):
    env = {name: value for name, value in os.environ.items() if name != "PYTHON_DOTENV_DISABLED"}
    env.update(HOME=str(tmp_path), PYTHONPATH=str(llm.ROOT / "agent"))
    result = subprocess.run([sys.executable, "-c", DRIVER, str(SCRIPT), *args], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == code, result.stderr
    assert "LOADED []" in result.stdout and "blocked" not in result.stderr


def test_live_run_with_fake_sdk_proves_uncached_usage_and_valid_output(monkeypatch, capsys, fake_api, live):
    monkeypatch.setenv("REPLAY", "replay")
    monkeypatch.setenv(demo_config.SELECTOR_ENV, "/nonexistent/fake-private-demo.json")
    live.module.main(["--live"])
    out, err = capsys.readouterr()
    result = json.loads(out[:out.rindex("\nPASS")])
    assert live.loaded == [((llm.ROOT / ".env",), {"override": False})]
    assert os.environ["REPLAY"] == "off" and demo_config.SELECTOR_ENV not in os.environ
    assert "REPLAY set to off" in err and f"{demo_config.SELECTOR_ENV} ignored" in err
    assert [(c["prompt"], c["cached"], c["input_tokens"], c["output_tokens"]) for c in result["calls"]] == [
        ("plan_intent", False, 100, 10), ("sentence_decode", False, 200, 20),
        ("auto_suggest", False, 300, 30), ("auto_suggest", False, 400, 40)]
    assert [p["label"] for p in result["plans"]] == [
        "Find Taylor Swift Ticketmaster tickets", "Buy Taylor Swift Ticketmaster tickets", "Something else"]
    assert result["sentences"] == ["Tell Mom I'll be late."]
    assert [len(items) for items in result["suggestions"].values()] == [3, 3]
    assert len(fake_api.requests) == 4
    for body in fake_api.requests:
        assert body["model"] == "fake-fast" and body["store"] is False and body["reasoning"] == {"effort": "low"}
        assert "sam@example.com" not in json.dumps(body)  # the persona's address stays out
    assert "Lunch Friday?" in fake_api.requests[2]["instructions"]
    assert "Mittagessen am Freitag?" in fake_api.requests[3]["instructions"]
    assert "fake-key" not in out + err and not llm.CACHE_DIR.exists()


def test_missing_key_is_a_setup_failure_before_any_request(monkeypatch, capsys, fake_api, live):
    monkeypatch.delenv("OPENAI_API_KEY")
    with pytest.raises(SystemExit) as exit:
        live.module.main(["--live"])
    assert exit.value.code == 1 and "SETUP FAILURE" in capsys.readouterr().err
    assert fake_api.requests == []


@pytest.mark.parametrize("failure,message", [
    ("no_usage", "reported no token usage"),
    ("cached", "served from a replay cache"),
    ("unresolved", "did not visibly resolve"),
    ("too_few", "Invalid plans response"),
])
def test_live_check_fails_honestly(monkeypatch, capsys, fake_api, live, failure, message):
    if failure == "no_usage":
        fake_api.usage = False
    elif failure == "cached":
        index = {"plan_intent": 0, "sentence_decode": 1, "auto_suggest": 2}
        async def cached(prompt, model, vars, **kwargs):
            return MeasuredResponse(json.dumps(OUTPUTS[index[prompt]]), [], "r1", True)
        monkeypatch.setattr(llm, "complete", cached)
    elif failure == "unresolved":
        fake_api.outputs[0] = {"plans": [{"label": "Find concert tickets"}, {"label": "Browse events"}]}
    else:
        fake_api.outputs[2] = {"plans": [{"label": "Open the email"}, {"label": "Reply to Alex"}]}
    with pytest.raises(SystemExit) as exit:
        live.module.main(["--live"])
    out, err = capsys.readouterr()
    assert exit.value.code == 1 and message in err and "PASS" not in out


@pytest.mark.parametrize("mode", ["replay", "record"])
def test_check_refuses_cached_modes_before_any_request(monkeypatch, fake_api, live, mode):
    monkeypatch.setenv("REPLAY", mode)
    with pytest.raises(LLMError, match="REPLAY=off"):
        asyncio.run(live.module.check())
    assert fake_api.requests == []
