"""Phase 0 stubs import cleanly and honor the contracts.py shapes. None of them touch the desktop."""
import asyncio
import importlib
import json

import pytest

from gaze_agent import llm, planner, profile, safety
from gaze_agent.contracts import Element, LLMError, LLMResponse, ProposedAction, Snapshot

MODULES = ["gaze_agent.server", "gaze_agent.llm", "gaze_agent.planner", "gaze_agent.auto", "gaze_agent.safety",
           "gaze_agent.screen", "gaze_agent.screen.ax", "gaze_agent.screen.shot", "gaze_agent.profile",
           "gaze_agent.contracts", "gaze_agent.protocol"]

SEND = Element("e1", "AXButton", "Send", "", True, (10, 20, 80, 30), "ax")
SNAP = Snapshot("s1", "Messages", "com.apple.MobileSMS", "Mom", None, focused=SEND, elements=[SEND])


@pytest.mark.parametrize("name", MODULES)
def test_imports(name):
    importlib.import_module(name)


def test_snapshot_prompt_format():
    assert SEND.to_line() == 'e1 | AXButton | "Send" | enabled | (10,20,80,30)'
    assert SNAP.to_prompt().splitlines()[-1] == SEND.to_line()


def test_stub_gate():
    assert safety.gate(ProposedAction("click_element", element=SEND), SNAP).source == "rule"
    other = Element("e2", "AXButton", "Cancel", "", True, (0, 0, 1, 1), "ax")
    assert not safety.gate(ProposedAction("click_element", element=other), SNAP).required
    flagged = safety.gate(ProposedAction("click_element", element=other, model_flag=True), SNAP)
    assert flagged.required and flagged.source == "model"


def test_stub_planner_shapes(monkeypatch):
    responses = {
        "plan_intent": {"plans": [
            {"label": "Open Messages", "risky": False},
            {"label": "Draft a message", "risky": False},
        ]},
        "sentence_decode": {"sentences": ["Tell Mom I'll be late."]},
    }

    async def fake_complete(prompt, model, vars, **kwargs):
        assert model == "fast"
        return LLMResponse(json.dumps(responses[prompt]), [], "test-response", False)

    monkeypatch.setattr(llm, "complete", fake_complete)
    plans = asyncio.run(planner.make_plans("x" * 60, profile.load_profile(), None))
    assert 3 <= len(plans) <= 5 and plans[-1].id == "other" and all(len(p.label) <= 40 for p in plans)
    sentences = asyncio.run(planner.decode(
        ["tell", "mom", "i'll", "be"], [["JKL", "ABC", "TUV", "DEF"]], None, {}))
    assert sentences == responses["sentence_decode"]["sentences"]
    # The old fixture supplied one key but returned an entire untyped message.
    # Keep rejecting it rather than weakening production key validation.
    with pytest.raises(LLMError, match="raw typing keys"):
        asyncio.run(planner.decode(["tell"], [["GHI"]], None, {}))


def test_stub_llm_raises_llm_error():
    from gaze_agent import llm
    with pytest.raises(LLMError):
        asyncio.run(llm.complete("plan_intent", "fast", {}))
