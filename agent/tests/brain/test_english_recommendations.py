"""English recommendations: prompt contract plus fake-response format and meaning checks.

Fakes show that code keeps names, native labels and message text intact and that
outputs fit the protocol. They do not prove the real model writes good English;
the human-run agent/replay/check_live_api.py --live check is for that.
"""
import asyncio
import json

import jsonschema
import pytest

from gaze_agent import auto, llm, planner
from gaze_agent.contracts import PROMPT_VARS, Element, LLMError, LLMResponse, Snapshot, WindowInfo

SCHEMA = json.loads((llm.ROOT / "protocol/messages.schema.json").read_text())
GERMAN = [Element("e1", "AXStaticText", "Von: Alex <alex@example.com>", "", True, (0, 0, 200, 20), "ax"),
          Element("e2", "AXStaticText", "Passt dir 12 Uhr am Freitag?", "", True, (0, 30, 300, 20), "ax"),
          Element("e3", "AXButton", "Antworten", "", True, (0, 60, 80, 20), "ax")]
MAIL_DE = Snapshot("s-de", "Mail", "com.apple.mail", "Mittagessen am Freitag (2)", None, None, GERMAN)


def reply(value):
    return LLMResponse(json.dumps(value, ensure_ascii=False), [], "r1", False)


def validate(name, payload):
    jsonschema.Draft202012Validator({"$defs": SCHEMA["$defs"], "$ref": f"#/$defs/{name}"}).validate(payload)


@pytest.mark.parametrize("prompt", ["plan_intent", "auto_suggest"])
def test_recommendation_prompts_request_english_without_translating_source_text(prompt):
    body = llm._body(prompt)
    assert "natural English" in body and "translate" in body
    # The English rule adds to, not replaces, the existing output contract.
    assert all(term in body for term in ("imperative", "40 characters", "risky", "favorite"))
    assert llm.placeholders(prompt) == PROMPT_VARS[prompt]


def test_auto_passes_native_text_verbatim_and_emits_english_labels_unchanged(monkeypatch, persona):
    info = WindowInfo(MAIL_DE.bundle_id, MAIL_DE.app, MAIL_DE.window_title,
                      f"{MAIL_DE.bundle_id}|{MAIL_DE.window_title}", [f"{e.role}|{e.label}" for e in GERMAN])
    items = [{"label": "Send Alex: „12 Uhr passt“", "detail": "Quote: „12 Uhr passt.“", "risky": False},
             {"label": "Click Antworten to reply to Alex", "risky": False},
             {"label": "Ask Alex where to meet", "detail": "Draft it; ask before sending.", "risky": True}]
    calls, emitted = [], []

    async def complete(prompt, model, vars):
        calls.append((prompt, model, vars))
        return reply({"plans": items})

    async def emit(*args):
        emitted.append(args)

    monkeypatch.setattr(llm, "complete", complete)
    watcher = auto.AutoWatcher(emit, lambda: info, lambda: MAIL_DE, lambda: persona, clock=lambda: 0.0)
    watcher.refresh()
    asyncio.run(watcher._tick())
    [(prompt, model, vars)] = calls
    assert (prompt, model) == ("auto_suggest", "fast")
    assert vars["window_title"] == "Mittagessen am Freitag (2)"
    assert all(element.to_line() in vars["screen"] for element in GERMAN)
    [(key, app, plans, cached)] = emitted
    assert key == "com.apple.mail|mittagessen am freitag" and app == "Mail" and cached is False
    assert [(p.label, p.detail) for p in plans] == [(item["label"], item.get("detail")) for item in items]
    # A Send label is risky by rule even when the model's hint says otherwise.
    assert [p.risky for p in plans] == [True, False, True]
    validate("payload_suggestions", {"list_id": "l1", "window_key": key, "app": app, "cached": cached,
                                     "items": [p.model_dump() for p in plans]})


def test_plans_keep_aliases_message_text_and_native_context(monkeypatch, persona):
    send = Element("e2", "AXButton", "Senden", "", True, (0, 0, 40, 20), "ax")
    context = Snapshot("s-msg", "Nachrichten", "com.apple.MobileSMS", "Mom", None, None, [send])
    items = [{"label": "Send Mom: I'll be late", "detail": "Quote: \"I'll be late, sorry!\"", "risky": False},
             {"label": "Draft a text to Mom", "detail": "Write it without sending.", "risky": False}]
    calls = []

    async def complete(prompt, model, vars):
        calls.append(vars)
        return reply({"plans": items})

    monkeypatch.setattr(llm, "complete", complete)
    plans = asyncio.run(planner.make_plans("Tell Mom I'll be late.", persona, context))
    assert calls[0]["intent"] == "Tell Mom I'll be late." and send.to_line() in calls[0]["app_context"]
    assert [(p.label, p.detail, p.risky) for p in plans[:-1]] == [
        ("Send Mom: I'll be late", "Quote: \"I'll be late, sorry!\"", True),
        ("Draft a text to Mom", "Write it without sending.", False)]
    validate("payload_plans", {"list_id": "l1", "items": [p.model_dump() for p in plans]})


def test_decode_never_returns_a_translation_of_committed_words(monkeypatch, persona):
    async def complete(prompt, model, vars):
        if json.loads(vars["raw_keys"]):
            return reply({"sentences": ["Dile mamá ha."]})
        return reply({"sentences": ["Dile a mamá que llegaré tarde.", "Tell Mom I'll be late."]})

    monkeypatch.setattr(llm, "complete", complete)
    sentences = asyncio.run(planner.decode(["tell", "mom", "ill", "be", "late"], [], "Mensajes", persona))
    assert sentences == ["tell mom ill be late", "Tell Mom I'll be late."]
    validate("payload_decode_result", {"sentences": sentences})
    with pytest.raises(LLMError, match="raw typing keys"):
        asyncio.run(planner.decode(["tell", "mom"], [["GHI", "ABC"]], None, persona))
