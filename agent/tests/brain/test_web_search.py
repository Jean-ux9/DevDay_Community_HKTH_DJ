"""Hosted web search: offered to the live agent only, parsed without a network call."""
import asyncio
import json

import httpx2
import pytest
from openai import AsyncOpenAI

from gaze_agent import llm, loop
from gaze_agent.contracts import LLMResponse, ToolCall

SEARCH_THEN_FINISH = {
    "id": "r1", "object": "response", "created_at": 0, "status": "completed",
    "output": [
        {"type": "web_search_call", "id": "ws1", "status": "completed",
         "action": {"type": "search", "query": "fixture tour dates"}},
        {"type": "function_call", "id": "fc1", "call_id": "c1", "name": "finish", "status": "completed",
         "arguments": json.dumps({"ok": True, "summary": "Next show is on 1 May (example.org)."})},
    ],
}
VARS = {"profile_summary": "fixture", "plan_label": "Look up fixture tour dates", "plan_detail": "", "screen": ""}


@pytest.mark.parametrize("env,offered", [
    ({}, True), ({"GAZE_WEB_SEARCH": "0"}, False), ({"REPLAY": "replay"}, False), ({"REPLAY": "record"}, False)])
def test_web_search_is_live_only_and_can_be_disabled(monkeypatch, env, offered):
    monkeypatch.delenv("GAZE_WEB_SEARCH", raising=False)
    monkeypatch.delenv("REPLAY", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    tools = loop.model_tools()
    assert (loop.WEB_SEARCH in tools) is offered
    # Function tools are unchanged either way, so recorded cache keys stay valid.
    assert [t for t in tools if t is not loop.WEB_SEARCH] == loop.TOOLS
    assert "web_search" not in loop.TOOL_SCHEMAS


def test_live_request_carries_hosted_search_and_parses_its_output(monkeypatch, persona):
    requests = []
    async def respond(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=SEARCH_THEN_FINISH)
    monkeypatch.setattr(llm, "AsyncOpenAI", lambda **kwargs: AsyncOpenAI(
        **kwargs, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond))))
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    monkeypatch.delenv("REPLAY", raising=False)
    result = asyncio.run(llm.complete("task_system", "agent", VARS, tools=loop.model_tools()))
    assert {"type": "web_search"} in requests[0]["tools"]
    assert "web_search" in requests[0]["instructions"]  # prompt guidance reaches the model
    assert result.tool_calls == [ToolCall("c1", "finish", {"ok": True, "summary": "Next show is on 1 May (example.org)."})]


def test_task_loop_offers_search_and_returns_the_answer(tmp_path, monkeypatch):
    from tests.runtime.test_tool_routing import make_task
    monkeypatch.delenv("REPLAY", raising=False)
    seen = []
    async def complete(prompt, model, variables, **kwargs):
        seen.append(kwargs["tools"])
        return LLMResponse(None, [ToolCall("c1", "finish", {"ok": True, "summary": "Opens at 9am (example.org)."})],
                           None, False)
    task = make_task(tmp_path, complete=complete)
    outcome = asyncio.run(task.run())
    assert outcome.ok and outcome.summary == "Opens at 9am (example.org)."
    assert loop.WEB_SEARCH in seen[0] and not task.desktop.calls
