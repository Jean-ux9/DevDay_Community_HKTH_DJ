import asyncio
import json
from pathlib import Path

import jsonschema
import pytest

from gaze_agent import llm, planner
from gaze_agent.contracts import LLMError, LLMResponse


def reply(value):
    return LLMResponse(json.dumps(value), [], "r1", False)


def test_plans_resolve_favorites_and_validate(monkeypatch, persona, snap):
    calls = []
    async def complete(name, model, vars):
        calls.append((name, model, vars))
        return reply({"plans": [
            {"label": "Find tickets for my favorite artist", "detail": "Search the site", "risky": False},
            {"label": "Buy Taylor Swift tickets", "risky": False},
        ]})
    monkeypatch.setattr(llm, "complete", complete)
    plans = asyncio.run(planner.make_plans("tickets for my favorite artist", persona, snap))
    schema = json.loads((llm.ROOT / "protocol/messages.schema.json").read_text())
    validator = jsonschema.Draft202012Validator({"$ref": "#/$defs/Plan", "$defs": schema["$defs"]})
    for plan in plans:
        validator.validate(plan.model_dump())
        assert len(plan.label) <= 40
    assert plans[-1].id == "other" and plans[-1].kind == "other"
    assert all("Taylor Swift" in p.label and "Ticketmaster" in p.label for p in plans[:-1])
    assert plans[1].risky
    assert len(calls) == 1 and calls[0][:2] == ("plan_intent", "fast")
    assert persona["address"]["email"] not in calls[0][2]["profile_summary"]


@pytest.mark.parametrize("count", [2, 3, 4])
def test_plan_count_labels_and_ids(count):
    plans = planner.parse_plans(json.dumps({"plans": [{"label": "Search " + "x" * 70} for _ in range(count)]}))
    assert len({p.id for p in plans}) == count
    assert all(len(p.label) == 40 for p in plans)


@pytest.mark.parametrize("value", [None, "not json", '{}', '[]',
    '{"plans":[{"label":""},{"label":"ok"}]}',
    '{"plans":[{"label":"Search","risky":"false"},{"label":"View"}]}',
    '{"plans":[{"label":"Search","kind":"recovery"},{"label":"View"}]}'])
def test_bad_plans_raise(value):
    with pytest.raises(LLMError):
        planner.parse_plans(value)


def test_decode_preserves_committed_words_and_one_call(monkeypatch, persona):
    calls = []
    async def complete(name, model, vars):
        calls.append((name, model, vars))
        return reply({"sentences": ["Tell Mom.", "Tell my mom.", "Tell Mom please."]})
    monkeypatch.setattr(llm, "complete", complete)
    sentences = asyncio.run(planner.decode(["tell", "mom"], [], None, persona))
    assert sentences == ["tell mom", "Tell Mom.", "Tell my mom."]
    assert len(calls) == 1 and calls[0][:2] == ("sentence_decode", "fast")
    sentences = asyncio.run(planner.decode(["tell", "mom"], [["GHI", "ABC"]], "Messages", persona))
    assert 1 <= len(sentences) <= 3
    assert json.loads(calls[1][2]["raw_keys"]) == [["GHI", "ABC"]]


@pytest.mark.parametrize("sentences", [[], [""], [1], ["a"] * 4])
def test_bad_decode(monkeypatch, sentences):
    async def complete(*args, **kwargs):
        return reply({"sentences": sentences})
    monkeypatch.setattr(llm, "complete", complete)
    with pytest.raises(LLMError):
        asyncio.run(planner.decode([], [], None, {}))


def test_prompt_text_stays_in_markdown():
    # Grep all agent source for substantive prompt lines, not just C's files.
    source = "\n".join(p.read_text() for p in (llm.ROOT / "agent/gaze_agent").rglob("*.py"))
    for prompt in llm.PROMPTS_DIR.glob("*.md"):
        body = llm._body(prompt.stem)
        for line in body.splitlines():
            if len(line) >= 55 and "{{" not in line and not line.startswith('{'):
                assert line not in source, f"Inline prompt text from {prompt.name}: {line}"
