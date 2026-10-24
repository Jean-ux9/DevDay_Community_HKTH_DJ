import asyncio
import json
from types import SimpleNamespace

import pytest

from gaze_agent import llm, server, tasklog
from gaze_agent.contracts import LLMError
from gaze_agent.profile import ProfileStore
from gaze_agent.tasklog import TaskLog, UsageMeter, get_usage_meter
from tests.runtime.support import INFO, SNAPSHOT, FakeDesktop


def configured_meter():
    return UsageMeter(environ={f"OPENAI_PRICE_{slot}_{direction}": price
                              for slot in ("AGENT", "FAST", "VISION")
                              for direction, price in (("IN", "2"), ("OUT", "8"))})


def test_three_calls_prices_and_per_prompt_totals():
    meter = configured_meter()
    meter.record("auto_suggest", "fast", 1000, 100)
    meter.record("plan_intent", "fast", 2000, 200)
    meter.record("auto_suggest", "fast", 3000, 300)
    summary = meter.summary()
    assert summary["calls"] == 3
    assert summary["input_tokens"] == 6000 and summary["output_tokens"] == 600
    assert summary["est_usd"] == pytest.approx(0.0168)
    assert summary["prompts"]["auto_suggest"]["calls"] == 2
    assert summary["prompts"]["auto_suggest"]["est_usd"] == pytest.approx(0.0112)


@pytest.mark.parametrize("price", [None, "", "nan", "inf", "-1", "invalid"])
def test_missing_or_invalid_prices_are_null_and_warn_once(caplog, price):
    meter = UsageMeter(environ={"OPENAI_PRICE_FAST_IN": price, "OPENAI_PRICE_FAST_OUT": "2"})
    meter.record("auto_suggest", "fast", 100, 20)
    meter.record("plan_intent", "fast", 100, 20)
    assert meter.summary()["est_usd"] is None
    assert all(row["est_usd"] is None for row in meter.summary()["prompts"].values())
    assert len(caplog.records) == 1 and "OPENAI_PRICE" in caplog.text


def fake_api(monkeypatch, *, status="completed", output_text="fake response"):
    calls = []
    class Client:
        def __init__(self, **kwargs):
            self.responses = self
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(id="fake-response", status=status, output_text=output_text, output=[],
                                   usage=SimpleNamespace(input_tokens=1000, output_tokens=100))
    monkeypatch.setattr(llm, "AsyncOpenAI", Client)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    return calls


def test_live_response_usage_all_prompts_and_replay_zero(tmp_path, monkeypatch):
    calls = fake_api(monkeypatch)
    log = TaskLog(tmp_path, usage=configured_meter())
    async def scenario():
        token = log.bind_usage()
        try:
            for prompt, slot, variables in [
                ("auto_suggest", "fast", {"profile_summary": "", "app": "Fake", "window_title": "Inbox", "screen": "PRIVATE SCREEN"}),
                ("plan_intent", "fast", {"profile_summary": "", "intent": "PRIVATE PROMPT", "app_context": ""}),
                ("sentence_decode", "fast", {"profile_style": "", "words": "", "raw_keys": "", "context": ""}),
                ("task_system", "agent", {"profile_summary": "", "plan_label": "", "plan_detail": "", "screen": ""}),
                ("look_at_screen", "vision", {"question": "Where?"}),
            ]:
                result = await llm.complete(prompt, slot, variables)
                assert result.input_tokens == 1000 and result.output_tokens == 100
            path = llm.CACHE_DIR / (llm.cache_key("look_at_screen", "fake-vision", {"question": "Where?"}) + ".json")
            llm._write_cache(path, result, {"question": "Where?"})
            monkeypatch.setenv("REPLAY", "replay")
            monkeypatch.delenv("OPENAI_API_KEY")
            replay = await llm.complete("look_at_screen", "vision", {"question": "Where?"})
            assert replay.cached and replay.input_tokens == replay.output_tokens == 0
        finally:
            log.reset_usage(token)
    asyncio.run(scenario())
    assert len(calls) == 5 and log.usage.summary()["calls"] == 5
    assert log.usage.summary()["est_usd"] == pytest.approx(0.014)
    assert set(log.usage.summary()["prompts"]) == {"auto_suggest", "plan_intent", "sentence_decode", "task_system", "look_at_screen"}
    log.write_usage(force=True)
    assert "PRIVATE" not in log.path.read_text()


def test_failed_response_still_accounts_known_usage(tmp_path, monkeypatch):
    fake_api(monkeypatch, status="incomplete")
    log = TaskLog(tmp_path, usage=configured_meter())
    async def scenario():
        token = log.bind_usage()
        try:
            with pytest.raises(LLMError, match="incomplete"):
                await llm.complete("look_at_screen", "vision", {"question": "Where?"})
        finally:
            log.reset_usage(token)
    asyncio.run(scenario())
    assert log.usage.summary()["calls"] == 1
    assert log.usage.summary()["input_tokens"] == 1000
    assert log.usage.summary()["est_usd"] == pytest.approx(0.0028)


def test_transport_failure_and_cancellation_count_attempts(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    log = TaskLog(tmp_path, usage=configured_meter())
    async def scenario():
        token = log.bind_usage()
        try:
            for error in (ConnectionError, asyncio.CancelledError):
                async def fail(*args, **kwargs):
                    raise error()
                monkeypatch.setattr(llm, "_live", fail)
                with pytest.raises(LLMError if error is ConnectionError else error):
                    await llm.complete("look_at_screen", "vision", {"question": "Where?"})
        finally:
            log.reset_usage(token)
    asyncio.run(scenario())
    assert log.usage.summary()["calls"] == 2 and log.usage.summary()["est_usd"] is None


def test_usage_every_five_minutes_and_privacy_even_in_debug(tmp_path, monkeypatch):
    monkeypatch.setenv("DEBUG", "1")
    now = [0.0]
    meter = configured_meter()
    log = TaskLog(tmp_path, clock=lambda: now[0], monotonic=lambda: now[0], usage=meter)
    meter.record("auto_suggest", "fast", 1000, 100)
    now[0] = 299
    assert not log.write_usage() and not log.path.exists()
    now[0] = 300
    assert log.write_usage() and not log.write_usage()
    now[0] = 600
    assert log.write_usage()
    assert log.write_usage(force=True)
    rows = [json.loads(line) for line in log.path.read_text().splitlines()]
    assert len(rows) == 3 and all(row["tool"] == "usage" for row in rows)
    assert set(rows[0]) == {"ts", "tool", "calls", "input_tokens", "output_tokens", "est_usd", "prompts"}
    assert log.path.stat().st_mode & 0o777 == 0o600


def test_periodic_reporter_with_fake_clock_and_no_sleep(tmp_path, monkeypatch):
    now = [0.0]
    log = TaskLog(tmp_path, clock=lambda: now[0], monotonic=lambda: now[0])
    async def sleep(seconds):
        assert seconds == 300
        if now[0] == 600:
            raise asyncio.CancelledError
        now[0] += seconds
    monkeypatch.setattr(tasklog.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(log.report_usage())
    assert [json.loads(line)["ts"] for line in log.path.read_text().splitlines()] == [300, 600]


def test_sessions_are_isolated_and_flush_at_disconnect(tmp_path, monkeypatch, capsys):
    fake_api(monkeypatch)
    class Socket:
        def __init__(self, count):
            self.count = count
        async def __aiter__(self):
            for _ in range(self.count):
                # Child tasks must inherit only this connection's usage meter.
                await asyncio.create_task(llm.complete("look_at_screen", "vision", {"question": "Where?"}))
            if False:
                yield ""
    logs = [TaskLog(tmp_path / str(i), usage=configured_meter()) for i in range(2)]
    async def scenario():
        original = get_usage_meter()
        sessions = [server.Session(Socket(i + 1), store=ProfileStore(tmp_path / str(i), demo=False),
                    screen=lambda: SNAPSHOT, info=lambda: INFO, desktop_factory=FakeDesktop, log=logs[i])
                    for i in range(2)]
        await asyncio.gather(*(session.run() for session in sessions))
        assert get_usage_meter() is original
    asyncio.run(scenario())
    assert [log.usage.summary()["calls"] for log in logs] == [1, 2]
    assert [json.loads(log.path.read_text())["calls"] for log in logs] == [1, 2]
    assert capsys.readouterr().out.count("Gaze session usage:") == 2
