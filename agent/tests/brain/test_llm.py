import asyncio
import json
from dataclasses import asdict, replace
from types import SimpleNamespace

import httpx2
import pytest
from openai import AsyncOpenAI

from gaze_agent import llm, profile
from gaze_agent.contracts import LLMError, LLMResponse, ToolCall


def variables(persona):
    return {"profile_summary": profile.profile_summary(persona), "intent": "tickets", "app_context": ""}


def test_cache_key_ignores_only_volatile_input(snap, persona):
    other = replace(snap, snapshot_id="snapshot-new", focused=replace(snap.focused, id="e99", bbox=(900, 800, 700, 600)),
                    elements=[replace(snap.focused, id="e99", bbox=(900, 800, 700, 600))])
    a = {"screen": snap.to_prompt(), "data": {"ts": 1, "id": "a", "snapshot": asdict(snap)}}
    b = {"screen": other.to_prompt(), "data": {"ts": 2, "id": "b", "snapshot": asdict(other)}}
    first = llm.cache_key("task_system", "fake", a, input_items=[{"call_id": "call-a", "output": json.dumps(a["data"])}])
    second = llm.cache_key("task_system", "fake", b, input_items=[{"call_id": "call-b", "output": json.dumps(b["data"])}])
    assert first == second
    assert first != llm.cache_key("task_system", "different-model", a)
    assert llm.cache_key("task_system", "fake", {"screen": snap.to_prompt()}) != llm.cache_key(
        "task_system", "fake", {"screen": snap.to_prompt().replace('"Message"', '"Delete"')})
    assert llm.cache_key("look_at_screen", "fake", {"question": "Where?"}, image_jpeg=b"a") != llm.cache_key(
        "look_at_screen", "fake", {"question": "Where?"}, image_jpeg=b"b")


def test_replay_miss_without_network_is_llm_error(monkeypatch, persona):
    monkeypatch.setenv("REPLAY", "replay")
    async def network(*args, **kwargs):
        raise AssertionError("No network should be attempted without a key")
    monkeypatch.setattr(llm, "_live", network)
    with pytest.raises(LLMError):
        asyncio.run(llm.complete("plan_intent", "fast", variables(persona)))


def test_replay_miss_live_failure_is_llm_error(monkeypatch, persona):
    monkeypatch.setenv("REPLAY", "replay")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    async def offline(*args, **kwargs):
        raise ConnectionError("offline")
    monkeypatch.setattr(llm, "_live", offline)
    with pytest.raises(LLMError, match="ConnectionError"):
        asyncio.run(llm.complete("plan_intent", "fast", variables(persona)))


def test_record_replay_identical_and_no_network(monkeypatch, tmp_path, persona):
    path = tmp_path / "demo_profile.json"
    path.write_text(json.dumps(persona))
    monkeypatch.setattr(llm, "DEMO_PROFILE_PATH", path)
    monkeypatch.setattr(profile, "load_profile", lambda: persona)
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("REPLAY", "record")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    expected = LLMResponse('{"plans":[]}', [], "r1", False)
    calls = []
    async def live(*args, **kwargs):
        calls.append(args)
        return expected
    monkeypatch.setattr(llm, "_live", live)
    first = asyncio.run(llm.complete("plan_intent", "fast", variables(persona)))
    assert first == expected and len(calls) == 1
    monkeypatch.setenv("REPLAY", "replay")
    monkeypatch.delenv("OPENAI_API_KEY")
    second = asyncio.run(llm.complete("plan_intent", "fast", variables(persona)))
    assert second == replace(expected, cached=True) and len(calls) == 1
    contents = next(llm.CACHE_DIR.glob("*.json")).read_text()
    assert "fake-key" not in contents and persona["address"]["email"] not in contents


def test_recording_refuses_non_demo_profile_before_http(monkeypatch, tmp_path, persona):
    monkeypatch.setenv("REPLAY", "record")
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    path = tmp_path / "demo.json"
    path.write_text(json.dumps(persona))
    monkeypatch.setattr(llm, "DEMO_PROFILE_PATH", path)
    monkeypatch.setattr(profile, "load_profile", lambda: {**persona, "name": "Different persona"})
    with pytest.raises(LLMError, match="demo_profile"):
        asyncio.run(llm.complete("plan_intent", "fast", variables(persona)))
    assert not llm.CACHE_DIR.exists()


def test_replay_rebinds_element_and_snapshot_ids(monkeypatch, tmp_path, snap):
    vars = {"profile_summary": "", "plan_label": "Open", "plan_detail": "", "screen": snap.to_prompt()}
    result = LLMResponse(None, [ToolCall("call1", "click_element", {"id": "e1", "snapshot_id": "s1"})], "r", False)
    path = tmp_path / "entry.json"
    llm._write_cache(path, result, vars)
    field = replace(snap.focused, id="e8", bbox=(90, 80, 50, 40))
    current = replace(snap, snapshot_id="s9", focused=field, elements=[field])
    replayed = llm._read_cache(path, {**vars, "screen": current.to_prompt()})
    assert replayed.tool_calls[0].args == {"id": "e8", "snapshot_id": "s9"}
    ambiguous = replace(current, elements=[field, replace(field, id="e10")])
    with pytest.raises(LLMError):
        llm._read_cache(path, {**vars, "screen": ambiguous.to_prompt()})


def test_responses_transport_mapping(monkeypatch, persona):
    captured = []
    class Client:
        def __init__(self, **kwargs):
            self.responses = self
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def create(self, **kwargs):
            captured.append(kwargs)
            return SimpleNamespace(status="completed", id="r1", output_text="ok", output=[
                SimpleNamespace(type="function_call", call_id="c1", name="press_keys", arguments='{"keys":["tab"]}')])
    monkeypatch.setattr(llm, "AsyncOpenAI", Client)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    tools = [{"type": "function", "name": "press_keys", "parameters": {}}]
    prior = [{"type": "function_call_output", "call_id": "c0", "output": "done"}]
    result = asyncio.run(llm.complete("look_at_screen", "vision", {"question": "Where?"},
                                      tools=tools, input_items=prior, image_jpeg=b"fake-jpeg"))
    sent = captured[0]
    assert sent["model"] == "fake-vision" and sent["store"] is False
    assert sent["tools"] == tools and sent["parallel_tool_calls"] is False
    assert sent["input"][0] == prior[0] and len(prior) == 1
    assert sent["input"][1]["content"][0]["image_url"].startswith("data:image/jpeg;base64,")
    assert result.tool_calls == [ToolCall("c1", "press_keys", {"keys": ["tab"]})]


def test_cancel_aborts_actual_sdk_fake_http_transport(monkeypatch, persona):
    async def scenario():
        started, aborted, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        class Transport(httpx2.AsyncBaseTransport):
            async def handle_async_request(self, request):
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    aborted.set()
                    raise
            async def aclose(self):
                closed.set()
        def client(**kwargs):
            return AsyncOpenAI(**kwargs, http_client=httpx2.AsyncClient(transport=Transport()))
        monkeypatch.setattr(llm, "AsyncOpenAI", client)
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
        task = asyncio.create_task(llm.complete("plan_intent", "fast", variables(persona)))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 0.5)
        assert aborted.is_set() and closed.is_set()
    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["template", "tools", "text"])
def test_key_preserves_semantic_inputs(monkeypatch, persona, change):
    vars = variables(persona)
    key = llm.cache_key("plan_intent", "fake", vars)
    if change == "template":
        body = llm._body("plan_intent")
        monkeypatch.setattr(llm, "_body", lambda _: body + "\nchanged")
        changed = llm.cache_key("plan_intent", "fake", vars)
    elif change == "tools":
        changed = llm.cache_key("plan_intent", "fake", vars, tools=[{"name": "finish"}])
    else:
        changed = llm.cache_key("plan_intent", "fake", {**vars, "intent": "different"})
    assert key != changed
