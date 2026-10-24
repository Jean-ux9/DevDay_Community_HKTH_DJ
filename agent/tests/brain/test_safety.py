from dataclasses import replace

import pytest

from gaze_agent.contracts import Element, ProposedAction
from gaze_agent.safety import gate

LABELS = [
    ("Send", "send"), ("SEND MESSAGE", "send"), ("Reply All", "send"),
    ("Place order", "buy"), ("Buy", "buy"), ("Purchase", "buy"), ("Pay", "buy"),
    ("Checkout", "buy"), ("Order now", "buy"), ("Book", "buy"), ("Reserve", "buy"),
    ("Confirm order", "buy"), ("Delete", "delete"), ("Remove", "delete"),
    ("Trash", "delete"), ("Erase", "delete"), ("Submit", "submit"),
    ("Post", "post"), ("Publish", "post"), ("Tweet", "post"),
    ("Transfer", "other"), ("Unsubscribe", "other"),
    ("Cancel", None), ("Search", None), ("Sender", None), ("Bookmarks", None),
    ("Playback", None), ("Open", None), ("Reply", None), ("Continue", None),
]


@pytest.mark.parametrize("label,expected", LABELS)
@pytest.mark.parametrize("source", ["ax", "ocr"])
def test_label_table(snap, label, expected, source):
    element = Element("e2", "AXButton" if source == "ax" else "text", label, "", True, (0, 0, 20, 20), source)
    result = gate(ProposedAction("click_element", element=element), snap)
    assert result.required == (expected is not None)
    assert result.action == (expected or "other")


@pytest.mark.parametrize("keys,expected", [
    (["cmd", "enter"], "send"), (["command", "return"], "send"),
    (["cmd", "shift", "d"], "send"), (["shift", "cmd", "d"], "send"),
    (["cmd", "delete"], "delete"), (["cmd", "backspace"], "delete"),
    (["shift", "cmd", "delete"], "delete"), (["enter"], "send"),
    (["return"], "send"), (["cmd", "c"], None), (["tab"], None), (["escape"], None),
])
def test_key_table(snap, keys, expected):
    result = gate(ProposedAction("press_keys", keys=keys), snap)
    assert result.required == (expected is not None)
    assert result.action == (expected or "other")


def test_description_finder_and_model_sources(snap):
    described = replace(snap.focused, label="", description="Send", role="AXButton")
    action = ProposedAction("click_element", element=described)
    assert gate(action, snap).action == "send"
    assert gate(replace(action, model_flag=True), snap).source == "both"
    flagged = ProposedAction("click_element", model_flag=True, model_reason="An irreversible action")
    assert gate(flagged, snap).source == "model"
    finder = replace(snap, app="Finder", bundle_id="com.apple.finder")
    trash = replace(described, label="Move to Trash", description="")
    assert gate(ProposedAction("click_element", element=trash), finder).action == "delete"


@pytest.mark.parametrize("app,bundle,label,description,title,expected", [
    ("TextEdit", "com.apple.TextEdit", "Document", "", "Untitled", False),
    ("Messages", "com.apple.MobileSMS", "Message", "Compose", "Mom", True),
    ("Mail", "com.apple.mail", "Body", "", "New message", True),
    ("Messages", "com.apple.MobileSMS", "Search", "", "Messages", False),
    ("Safari", "com.apple.Safari", "Chat input", "", "Support", True),
    ("Safari", "com.apple.Safari", "Address", "", "Checkout", True),
    ("Safari", "com.apple.Safari", "Name", "", "Payment details", True),
    ("Safari", "com.apple.Safari", "Quantity", "", "Order", True),
    ("Safari", "com.apple.Safari", "Search", "", "Search", False),
])
def test_enter_context(snap, app, bundle, label, description, title, expected):
    field = replace(snap.focused, label=label, description=description)
    snap = replace(snap, app=app, bundle_id=bundle, focused=field, window_title=title)
    assert gate(ProposedAction("press_keys", keys=["enter"]), snap).required == expected


@pytest.mark.parametrize("url,required", [
    ("https://example.com/checkout", True), ("https://example.com/PAYMENT/step", True),
    ("https://example.com/cart/buy", True), ("https://example.com/%63heckout", True),
    ("https://example.com/help/checkout", True), ("https://example.com/checkout-help", False),
    ("https://example.com/search?q=checkout", False), ("https://example.com/", False),
])
def test_urls(snap, url, required):
    result = gate(ProposedAction("open_url", url=url), snap)
    assert result.required == required
    if required:
        assert result.action == "buy"


def test_drafting_is_safe_but_submission_is_not(snap):
    send = replace(snap.focused, label="Send")
    assert not gate(ProposedAction("type_text", element=send, text="hello"), snap).required
    assert gate(ProposedAction("type_text", element=send, text="hello", submit=True), snap).action == "send"


def test_details_are_observed_not_model_inventions(snap):
    amount = replace(snap.focused, id="o2", label="Total $125.50", description="", source="ocr")
    snap = replace(snap, elements=[amount])
    action = ProposedAction("type_text", text="Exact message\nsecond line", submit=True,
                            model_flag=True, model_reason="Send to a different person")
    decision = gate(action, snap)
    assert "Exact text: Exact message\nsecond line" in decision.details
    assert "Visible amount: Total $125.50" in decision.details
    assert "Recipient/compose context: Mom" in decision.details
    assert "different person" not in decision.title
    assert decision.source == "both"
