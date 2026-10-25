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


@pytest.mark.parametrize("has_key", [False, True])
@pytest.mark.parametrize("cache_state", ["missing", "malformed"])
def test_replay_never_constructs_fake_api_client_on_miss_or_bad_cache(monkeypatch, persona, has_key, cache_state):
    monkeypatch.setenv("REPLAY", "replay")
    if has_key:
        monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    calls = []
    class Client:
        def __init__(self, **kwargs):
            calls.append("constructed")
            self.responses = self
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def create(self, **kwargs):
            calls.append("requested")
            return SimpleNamespace(status="completed", id="r1", output_text="ok", output=[])
    monkeypatch.setattr(llm, "AsyncOpenAI", Client)
    from gaze_agent.tasklog import UsageMeter
    meter = UsageMeter(environ={})
    monkeypatch.setattr(llm, "get_usage_meter", lambda: meter)
    if cache_state == "malformed":
        llm.CACHE_DIR.mkdir()
        key = llm.cache_key("plan_intent", "fake-fast", variables(persona))
        (llm.CACHE_DIR / (key + ".json")).write_text("not JSON")
    expected = "Replay cache miss.*live calls are disabled" if cache_state == "missing" else "Invalid or incompatible replay entry"
    with pytest.raises(LLMError, match=expected) as error:
        asyncio.run(llm.complete("plan_intent", "fast", variables(persona)))
    assert calls == []
    assert meter.summary()["calls"] == 0
    assert "fake-key" not in str(error.value)
    if cache_state == "missing":
        assert "REPLAY=record" in str(error.value)
        assert not llm.CACHE_DIR.exists()


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
    assert second.text == expected.text and second.tool_calls == expected.tool_calls
    assert second.cached and second.input_tokens == second.output_tokens == 0 and len(calls) == 1
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
    assert "reasoning" not in sent


@pytest.mark.parametrize("slot,effort", [("agent", "xhigh"), ("fast", "low"), ("vision", "xhigh")])
def test_reasoning_effort_reaches_sdk_and_separates_replay(monkeypatch, persona, slot, effort):
    requests = []

    async def respond(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json={
            "id": "r1", "object": "response", "created_at": 0, "status": "completed",
            "output": [{"type": "message", "id": "m1", "status": "completed", "role": "assistant",
                        "content": [{"type": "output_text", "text": "ok", "annotations": []}]}],
        })

    def client(**kwargs):
        return AsyncOpenAI(**kwargs, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)))

    monkeypatch.setattr(llm, "AsyncOpenAI", client)
    monkeypatch.setattr(profile, "load_profile", lambda: persona)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("REPLAY", "record")
    monkeypatch.setenv(f"OPENAI_REASONING_EFFORT_{slot.upper()}", effort)
    asyncio.run(llm.complete("plan_intent", slot, variables(persona)))
    assert requests[0]["reasoning"] == {"effort": effort}
    assert requests[0]["model"] == f"fake-{slot}"

    monkeypatch.setenv("REPLAY", "replay")
    monkeypatch.delenv("OPENAI_API_KEY")
    assert asyncio.run(llm.complete("plan_intent", slot, variables(persona))).cached
    monkeypatch.setenv(f"OPENAI_REASONING_EFFORT_{slot.upper()}", "high")
    with pytest.raises(LLMError, match="Replay cache miss"):
        asyncio.run(llm.complete("plan_intent", slot, variables(persona)))
    assert len(requests) == 1


def test_invalid_reasoning_effort_rejected_before_http(monkeypatch, persona):
    monkeypatch.setenv("OPENAI_REASONING_EFFORT_FAST", "extra high")
    with pytest.raises(LLMError, match="OPENAI_REASONING_EFFORT_FAST is invalid"):
        asyncio.run(llm.complete("plan_intent", "fast", variables(persona)))


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


# ---- private demo configuration (#5): synthetic manifests and FAKE handles only ----

from gaze_agent import demo_config  # noqa: E402
from gaze_agent.tasklog import UsageMeter  # noqa: E402
from tests.runtime.test_demo_config import (FAKE_HANDLES, FAKE_PERSONA, select_private,  # noqa: E402
                                             write_manifest)

OK_RESPONSE = {
    "id": "r1", "object": "response", "created_at": 0, "status": "completed",
    "output": [{"type": "message", "id": "m1", "status": "completed", "role": "assistant",
                "content": [{"type": "output_text", "text": "ok", "annotations": []}]}],
}


@pytest.fixture(autouse=True)
def no_inherited_private_selector(monkeypatch, tmp_path):
    monkeypatch.delenv(demo_config.SELECTOR_ENV, raising=False)
    monkeypatch.setattr(demo_config, "USER_DATA_DIR", tmp_path / "default-user-data")


def fake_http_sdk(monkeypatch, requests, status=200, body=OK_RESPONSE):
    async def respond(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(status, json=body)
    monkeypatch.setattr(llm, "AsyncOpenAI", lambda **kwargs: AsyncOpenAI(
        **kwargs, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond))))


def forbid_client(monkeypatch):
    constructed = []
    monkeypatch.setattr(llm, "AsyncOpenAI", lambda **kwargs: constructed.append(kwargs))
    return constructed


def assert_clean(text, tmp_path):
    assert "fake-key" not in text and str(tmp_path) not in text
    assert not any(handle in text for handle in FAKE_HANDLES)


@pytest.mark.parametrize("slot,effort", [("agent", "xhigh"), ("fast", "low"), ("vision", "xhigh")])
def test_private_record_and_replay_stay_in_the_selected_namespace(monkeypatch, tmp_path, slot, effort):
    tracked = sorted(path.name for path in (llm.ROOT / "agent/replay/cache").iterdir())
    config = select_private(monkeypatch, tmp_path)
    requests = []
    fake_http_sdk(monkeypatch, requests)
    monkeypatch.setenv("REPLAY", "record")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    monkeypatch.setenv(f"OPENAI_REASONING_EFFORT_{slot.upper()}", effort)
    vars = variables(config.persona())
    recorded = asyncio.run(llm.complete("plan_intent", slot, vars))
    assert recorded.text == "ok" and not recorded.cached
    assert requests[0]["model"] == f"fake-{slot}" and requests[0]["reasoning"] == {"effort": effort}
    entries = list(config.recording_dir.glob("*.json"))
    assert len(entries) == 1 and entries[0].stat().st_mode & 0o777 == 0o600
    assert {d.stat().st_mode & 0o777 for d in (config.cache_dir, config.recording_dir)} == {0o700}
    assert "fake-key" not in entries[0].read_text()
    assert (config.data_dir / "profile.json").is_file()  # the guard used the private store
    assert not llm.CACHE_DIR.exists()
    assert sorted(path.name for path in (llm.ROOT / "agent/replay/cache").iterdir()) == tracked

    monkeypatch.setenv("REPLAY", "replay")  # the key stays set: replay must still be strict
    replayed = asyncio.run(llm.complete("plan_intent", slot, vars))
    assert replayed.cached and replayed.text == "ok" and len(requests) == 1

    # A different persona sharing the cache root, and the public default, never reuse it.
    contacts = {"Mom": ["+1 555 0177"], "Alex": ["alex.rehearsal@example.invalid"]}
    other = select_private(monkeypatch, tmp_path, "other.json", persona={**config.persona(), "contacts": contacts},
                           approved_recipients=contacts)
    assert other.cache_dir == config.cache_dir and other.recording_dir != config.recording_dir
    with pytest.raises(LLMError, match="Replay cache miss"):
        asyncio.run(llm.complete("plan_intent", slot, vars))
    monkeypatch.delenv(demo_config.SELECTOR_ENV)
    with pytest.raises(LLMError, match="Replay cache miss"):
        asyncio.run(llm.complete("plan_intent", slot, vars))
    assert len(requests) == 1


@pytest.mark.parametrize("state", ["missing", "malformed", "incompatible"])
def test_private_replay_never_calls_api_even_with_key(monkeypatch, tmp_path, state):
    config = select_private(monkeypatch, tmp_path)
    monkeypatch.setenv("REPLAY", "replay")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    constructed = forbid_client(monkeypatch)
    meter = UsageMeter(environ={})
    monkeypatch.setattr(llm, "get_usage_meter", lambda: meter)
    vars = variables(config.persona())
    if state != "missing":
        config.recording_dir.mkdir(parents=True)
        entry = "not JSON" if state == "malformed" else json.dumps({"response": {"text": "ok"}})
        (config.recording_dir / (llm.cache_key("plan_intent", "fake-fast", vars) + ".json")).write_text(entry)
    expected = "Replay cache miss.*REPLAY=record" if state == "missing" else "Invalid or incompatible replay entry"
    with pytest.raises(LLMError, match=expected) as error:
        asyncio.run(llm.complete("plan_intent", "fast", vars))
    assert constructed == [] and meter.summary()["calls"] == 0
    assert_clean(str(error.value), tmp_path)


@pytest.mark.parametrize("mode", ["record", "replay"])
@pytest.mark.parametrize("case,changes,expected", [
    ("demo mode off", {}, "requires DEMO_MODE=1"),
    ("tracked cache", {"cache_dir": str(llm.ROOT / "agent/replay/cache/private")}, "outside every Git work tree"),
    ("unapproved persona", {"approved_recipients": {"Mom": ["+1 555 0142"]}}, "exactly the persona's contacts"),
])
def test_private_selection_errors_fail_before_http_or_storage(monkeypatch, tmp_path, mode, case, changes, expected):
    monkeypatch.setenv(demo_config.SELECTOR_ENV, str(write_manifest(tmp_path, **changes)))
    monkeypatch.setenv("DEMO_MODE", "0" if case == "demo mode off" else "1")
    monkeypatch.setenv("REPLAY", mode)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    constructed = forbid_client(monkeypatch)
    with pytest.raises(LLMError, match=expected) as error:
        asyncio.run(llm.complete("plan_intent", "fast", variables(FAKE_PERSONA)))
    assert constructed == []
    assert_clean(str(error.value), tmp_path)
    assert not (llm.ROOT / "agent/replay/cache/private").exists()
    assert not (tmp_path / "private-data").exists() and not (tmp_path / "private-cache").exists()


@pytest.mark.parametrize("case", ["edited profile", "unapproved contact on disk", "public prompt persona",
                                  "public decode style"])
def test_private_recording_guard_requires_the_selected_persona(monkeypatch, tmp_path, persona, case):
    config = select_private(monkeypatch, tmp_path)
    monkeypatch.setenv("REPLAY", "record")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    constructed = forbid_client(monkeypatch)
    private = config.persona()
    prompt, vars = "plan_intent", variables(private)
    if case in {"edited profile", "unapproved contact on disk"}:
        stored = ({**private, "name": "Edited name"} if case == "edited profile" else
                  {**private, "contacts": {**private["contacts"], "Boss": ["boss@example.invalid"]}})
        config.data_dir.mkdir()
        (config.data_dir / "profile.json").write_text(json.dumps(stored))
    elif case == "public prompt persona":
        vars = variables(persona)
    else:
        prompt = "sentence_decode"
        vars = {"profile_style": json.dumps(persona["style"]), "words": "tell", "raw_keys": "GHI", "context": ""}
    with pytest.raises(LLMError, match="selected private demo persona") as error:
        asyncio.run(llm.complete(prompt, "fast", vars))
    assert constructed == [] and not config.cache_dir.exists()
    assert_clean(str(error.value), tmp_path)


def test_private_record_cancel_aborts_fake_transport_and_writes_nothing(monkeypatch, tmp_path):
    config = select_private(monkeypatch, tmp_path)
    monkeypatch.setenv("REPLAY", "record")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

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
        monkeypatch.setattr(llm, "AsyncOpenAI", lambda **kwargs: AsyncOpenAI(
            **kwargs, http_client=httpx2.AsyncClient(transport=Transport())))
        task = asyncio.create_task(llm.complete("plan_intent", "fast", variables(config.persona())))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 0.5)
        assert aborted.is_set() and closed.is_set()
    asyncio.run(scenario())
    assert not config.cache_dir.exists()


def test_private_record_api_failure_is_sanitized_and_not_cached(monkeypatch, tmp_path):
    config = select_private(monkeypatch, tmp_path)
    monkeypatch.setenv("REPLAY", "record")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    requests = []
    echo = f"fake-key {FAKE_HANDLES[0]} {tmp_path}"
    fake_http_sdk(monkeypatch, requests, status=500, body={"error": {"message": echo, "type": "server_error"}})
    with pytest.raises(LLMError) as error:
        asyncio.run(llm.complete("plan_intent", "fast", variables(config.persona())))
    assert str(error.value) == "LLM call failed (InternalServerError)" and len(requests) == 1
    assert not config.cache_dir.exists()
