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
            {"label": "Find my favorite artist on Ticketmaster", "detail": "Search the site", "risky": False},
            {"label": "Buy Taylor Swift Ticketmaster tickets", "risky": False},
            {"label": "Compare resale prices", "risky": False},
        ]})
    monkeypatch.setattr(llm, "complete", complete)
    plans = asyncio.run(planner.make_plans("tickets for my favorite artist", persona, snap))
    schema = json.loads((llm.ROOT / "protocol/messages.schema.json").read_text())
    validator = jsonschema.Draft202012Validator({"$ref": "#/$defs/Plan", "$defs": schema["$defs"]})
    for plan in plans:
        validator.validate(plan.model_dump())
        assert len(plan.label) <= 40
    # The unresolved plan is dropped, never relabeled with a template.
    assert [(p.id, p.label) for p in plans] == [("p1", "Find Taylor Swift on Ticketmaster"),
                                                ("p2", "Buy Taylor Swift Ticketmaster tickets"),
                                                ("other", "Something else")]
    assert plans[-1].kind == "other"
    assert plans[0].detail == "Search the site" and plans[1].risky
    assert len(calls) == 1 and calls[0][:2] == ("plan_intent", "fast")
    assert persona["address"]["email"] not in calls[0][2]["profile_summary"]


def test_unresolved_favorites_fail_instead_of_template_labels(monkeypatch, persona):
    async def complete(*args):
        # The old fallback turned "Buy" into a "Browse" label but kept its risk/detail.
        return reply({"plans": [
            {"label": "Find tickets for my favorite artist", "detail": "Search the site", "risky": False},
            {"label": "Buy Taylor Swift tickets", "detail": "Buy two tickets", "risky": True},
        ]})
    monkeypatch.setattr(llm, "complete", complete)
    with pytest.raises(LLMError, match="did not visibly resolve"):
        asyncio.run(planner.make_plans("tickets for my favorite artist", persona, None))


def test_label_with_a_cut_site_is_dropped(monkeypatch, persona):
    async def complete(*args):
        return reply({"plans": [
            # 41 characters: truncation would cut the site out of the visible label.
            {"label": "Find Taylor Swift tickets on Ticketmaster"},
            {"label": "Find Taylor Swift Ticketmaster tickets"},
            {"label": "Search Ticketmaster for Taylor Swift"},
        ]})
    monkeypatch.setattr(llm, "complete", complete)
    plans = asyncio.run(planner.make_plans("tickets for my favourite artist", persona, None))
    assert [p.label for p in plans] == ["Find Taylor Swift Ticketmaster tickets",
                                        "Search Ticketmaster for Taylor Swift", "Something else"]


def test_label_over_40_characters_after_resolution_is_dropped(monkeypatch, persona):
    persona["favorites"]["playlist"] = "Late Night Lo-Fi Coding Session"
    async def complete(*args):
        return reply({"plans": [{"label": "Play my focus playlist on Spotify"},  # 47 once resolved
                                {"label": "Play my focus playlist"}, {"label": "Shuffle my playlist"}]})
    monkeypatch.setattr(llm, "complete", complete)
    plans = asyncio.run(planner.make_plans("play my focus playlist", persona, None))
    assert [p.label for p in plans[:-1]] == ["Play Late Night Lo-Fi Coding Session",
                                             "Shuffle Late Night Lo-Fi Coding Session"]


def test_any_configured_site_counts_as_visible(monkeypatch, persona):
    persona["favorites"]["sites"] = ["https://www.youtube.com/", "ticketmaster.com"]
    async def complete(*args):
        return reply({"plans": [{"label": "Find Taylor Swift Ticketmaster tickets"},
                                {"label": "Watch Taylor Swift on YouTube"}]})
    monkeypatch.setattr(llm, "complete", complete)
    plans = asyncio.run(planner.make_plans("tickets for my favorite artist", persona, None))
    assert [p.label for p in plans[:-1]] == ["Find Taylor Swift Ticketmaster tickets",
                                             "Watch Taylor Swift on YouTube"]


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


@pytest.mark.parametrize("sentences", [[], [""], [1], ["Tell Mom."] * 4])
def test_bad_decode(monkeypatch, sentences):
    async def complete(*args, **kwargs):
        return reply({"sentences": sentences})
    monkeypatch.setattr(llm, "complete", complete)
    with pytest.raises(LLMError, match="Invalid sentences response"):
        asyncio.run(planner.decode(["tell", "mom"], [], None, {}))


@pytest.mark.parametrize("words", [[], ["?"], [" "]])
def test_decode_with_nothing_typed_makes_no_model_call(monkeypatch, words):
    def forbidden(*args, **kwargs):
        raise AssertionError("An empty request must not ask the model to invent a sentence")
    monkeypatch.setattr(llm, "complete", forbidden)
    with pytest.raises(LLMError, match="Nothing was typed"):
        asyncio.run(planner.decode(words, [], None, {}))


@pytest.mark.parametrize("words,raw,sentence", [
    # The T9 word list has no apostrophes; correcting them is the requested grammar fix.
    (["tell", "mom", "ill", "be"], [["JKL", "ABC", "TUV", "DEF"]], "Tell Mom I'll be late."),
    (["i", "dont", "know"], [], "I don't know."),
    (["im", "on", "my", "way"], [], "I’m on my way."),
])
def test_decode_accepts_apostrophes_in_committed_t9_words(monkeypatch, words, raw, sentence):
    async def complete(*args, **kwargs):
        return reply({"sentences": [sentence]})
    monkeypatch.setattr(llm, "complete", complete)
    assert asyncio.run(planner.decode(words, raw, None, {}))[-1] == sentence


def test_decode_without_raw_keys_keeps_committed_words_in_order(monkeypatch):
    async def complete(*args, **kwargs):
        return reply({"sentences": ["Tell Dad I'm late.", "Mom, I'm late.", "Tell Mom that I'm running late."]})
    monkeypatch.setattr(llm, "complete", complete)
    # The literal words stay first; a variant may add words but not drop or swap them.
    assert asyncio.run(planner.decode(["tell", "mom", "im", "late"], [], None, {})) == [
        "tell mom im late", "Tell Mom that I'm running late."]


def test_prompt_text_stays_in_markdown():
    # Grep all agent source for substantive prompt lines, not just C's files.
    source = "\n".join(p.read_text() for p in (llm.ROOT / "agent/gaze_agent").rglob("*.py"))
    for prompt in llm.PROMPTS_DIR.glob("*.md"):
        body = llm._body(prompt.stem)
        for line in body.splitlines():
            if len(line) >= 55 and "{{" not in line and not line.startswith('{'):
                assert line not in source, f"Inline prompt text from {prompt.name}: {line}"
