import asyncio
import json
from pathlib import Path

import jsonschema
import pytest

from gaze_agent import llm, planner
from gaze_agent.contracts import Element, LLMError, LLMResponse, ProposedAction
from gaze_agent.safety import gate


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
        if json.loads(vars["raw_keys"]):
            return reply({"sentences": ['Tell Mom "ha."']})
        return reply({"sentences": ["Tell Mom.", "Tell my mom.", "Tell Mom please."]})
    monkeypatch.setattr(llm, "complete", complete)
    sentences = asyncio.run(planner.decode(["tell", "mom"], [], None, persona))
    assert sentences == ["tell mom", "Tell Mom.", "Tell my mom."]
    assert len(calls) == 1 and calls[0][:2] == ("sentence_decode", "fast")
    sentences = asyncio.run(planner.decode(["tell", "mom"], [["GHI", "ABC"]], "Messages", persona))
    assert 1 <= len(sentences) <= 3
    assert json.loads(calls[1][2]["raw_keys"]) == [["GHI", "ABC"]]


@pytest.mark.parametrize("label,detail,model_flag,expected", [
    ("Find tickets", "Search Ticketmaster. No purchase.", False, False),
    ("Find tickets", "NO PURCHASE", False, False),
    ("Find tickets", "Search events; no\npurchase; let the user choose.", False, False),
    ("Buy tickets", "No purchase.", False, True),
    ("Find tickets", "Purchase two tickets.", False, True),
    ("Find tickets", "No purchase. Then pay at checkout.", False, True),
    ("Find tickets", "No purchase without confirmation.", False, True),
    ("Find tickets", "No purchase.", True, True),
    ("Find tickets", "No purchase. Send results.", False, True),
    ("Find tickets", "No purchase. Delete saved alerts.", False, True),
])
def test_risk_hint_ignores_only_no_purchase_disclaimer(label, detail, model_flag, expected):
    plans = planner.parse_plans(json.dumps({"plans": [
        {"label": label, "detail": detail, "risky": model_flag}, {"label": "Browse events"},
    ]}))
    assert plans[0].risky is expected
    assert plans[0].detail == detail


def test_safe_search_hint_does_not_bypass_purchase_confirmation(snap):
    plans = planner.parse_plans(json.dumps({"plans": [
        {"label": "Find tickets", "detail": "Search Ticketmaster. No purchase.", "risky": False},
        {"label": "Browse events"},
    ]}))
    assert not plans[0].risky
    buy = Element("buy", "AXButton", "Buy tickets", "", True, (0, 0, 20, 20), "ax")
    decision = gate(ProposedAction("click_element", element=buy, model_flag=False), snap)
    assert decision.required and decision.action == "buy" and decision.source == "rule"


@pytest.mark.parametrize("raw", [None, "GHI", ["GHI"], [[]], [[""]], [["2"]],
    [["AB"]], [["CBA"]], [["XYZ"]], [[" ABC"]], [[1]], [[None]], [[{"group": "ABC"}]]])
def test_bad_raw_keys_fail_before_model_call(monkeypatch, raw):
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid typing keys must not call the model")
    monkeypatch.setattr(llm, "complete", forbidden)
    with pytest.raises(LLMError, match="Invalid raw typing keys"):
        asyncio.run(planner.decode(["tell", "mom"], raw, None, {}))


@pytest.mark.parametrize("words,raw,sentence", [
    (["tell", "mom"], [["GHI", "ABC"]], 'Tell Mom "ha."'),
    (["Tell", "Mom"], [["ghi", "abc"]], "tell mom Ha!"),
    ([], [["ABC", "DEF"]], "Be!"),
    (["tell", "mom", "i'll", "be"], [["JKL", "ABC", "TUV", "DEF"]], "Tell Mom I’ll be late."),
    (["set", "timer", "10"], [["MNO"] * 4], "Set timer 10: noon."),
    (["tell"], [["GHI", "MNO"], ["MNO", "TUV", "TUV"]], "Tell I’m out."),
    (["open"], [["WXYZ", "MNO", "TUV", "TUV", "TUV", "ABC", "DEF"]], "Open YouTube."),
])
def test_decode_validates_all_groups_words_and_punctuation(monkeypatch, words, raw, sentence):
    calls = []
    async def complete(name, model, vars):
        calls.append(vars)
        return reply({"sentences": [sentence]})
    monkeypatch.setattr(llm, "complete", complete)
    assert asyncio.run(planner.decode(words, raw, None, {})) == [sentence]
    assert len(calls) == 1
    assert json.loads(calls[0]["raw_keys"]) == [[group.upper() for group in groups] for groups in raw]


@pytest.mark.parametrize("sentence", [
    "Tell Mom hi.", "Tell Mom happy.", "Tell Mom h.", "Tell Mom.", "Tell Mom ha please.",
    "Tell Dad ha.", "Mom tell ha.", "Please tell Mom ha.", "Tell Mom ha ga.",
    "Tell Mom 42.", "Tell Mom hé.", "Tell Mom h a.",
])
def test_decode_rejects_changed_keys_missing_words_and_invented_text(monkeypatch, sentence):
    calls = []
    async def complete(*args, **kwargs):
        calls.append(args)
        return reply({"sentences": [sentence]})
    monkeypatch.setattr(llm, "complete", complete)
    with pytest.raises(LLMError, match="raw typing keys"):
        asyncio.run(planner.decode(["tell", "mom"], [["GHI", "ABC"]], None, {}))
    assert len(calls) == 1


def test_decode_filters_bad_variants_without_another_model_call(monkeypatch):
    calls = []
    async def complete(*args, **kwargs):
        calls.append(args)
        return reply({"sentences": ["Tell Mom hi.", "Tell Mom ha.", "Tell Mom ga."]})
    monkeypatch.setattr(llm, "complete", complete)
    assert asyncio.run(planner.decode(["tell", "mom"], [["GHI", "ABC"]], None, {})) == [
        "Tell Mom ha.", "Tell Mom ga."]
    assert len(calls) == 1


def test_decode_does_not_expand_unicode_into_typed_letters(monkeypatch):
    async def complete(*args, **kwargs):
        return reply({"sentences": ["ß"]})
    monkeypatch.setattr(llm, "complete", complete)
    with pytest.raises(LLMError, match="raw typing keys"):
        asyncio.run(planner.decode([], [["PQRS", "PQRS"]], None, {}))


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
