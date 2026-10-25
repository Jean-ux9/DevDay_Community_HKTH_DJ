"""Synthetic native AX controls, never observations of Messages/Mail on this Mac."""
import copy
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from gaze_agent.screen import ax, recipients
from tests.runtime.support import ROOT, SNAPSHOT


def install_native(monkeypatch, snapshot=None, *, bundle="com.apple.mail", handle="alex.rehearsal@example.invalid"):
    snapshot = snapshot or replace(SNAPSHOT, app="Mail", bundle_id=bundle)
    nodes = json.loads((ROOT / "fixtures/recipient_native_compose.json").read_text())
    nodes.pop("_note")
    nodes["to"]["AXValue"] = handle
    if bundle == "com.apple.MobileSMS":
        nodes["headers"]["AXChildren"] = ["to-label", "to"]
    state = SimpleNamespace(snapshot=snapshot, nodes=nodes, window="window", focus="send", verified=[])
    identity = ax.WindowIdentity(9001, "window", snapshot.window_title, (0, 0, 500, 400))
    state.identity = identity
    monkeypatch.setattr(ax, "attribute", lambda n, k, default=None: nodes[n].get(k, default))
    monkeypatch.setattr(ax, "front_window", lambda: (
        SimpleNamespace(bundleIdentifier=lambda: bundle), "root", state.window))
    monkeypatch.setattr(ax, "window_identity", lambda *_: state.identity)
    monkeypatch.setattr(ax, "snapshot_context", lambda _: (identity, state.focus))
    def verify(sid):
        assert sid == state.snapshot.snapshot_id
        state.verified.append(sid)
    monkeypatch.setattr(ax, "verify_snapshot", verify)
    monkeypatch.setattr(ax, "resolve", lambda sid, eid: (
        next(e for e in state.snapshot.elements if e.id == eid), "send"))
    return state


@pytest.mark.parametrize("bundle,handle", [
    ("com.apple.mail", "alex.rehearsal@example.invalid"),
    ("com.apple.MobileSMS", "+1 555 0142"),
])
def test_single_handle_from_native_field_relationship(monkeypatch, bundle, handle):
    state = install_native(monkeypatch, bundle=bundle, handle=handle)
    evidence = recipients.read(state.snapshot)
    assert evidence.handle == handle and evidence.fields
    assert handle not in repr(evidence)
    assert len(state.verified) >= 2


@pytest.mark.parametrize("value", ["", "Mom", "Moments", "NotMom", "To: Mom", "To: +1 555 0142",
    "Alex <alex.rehearsal@example.invalid>", "alex.rehearsal@example.invalid,other@example.invalid",
    "alex.rehearsal@example.invalid;other@example.invalid", "+1 555 0142;+1 555 0199",
    "+1 555 0142 +1 555 0199", " alex.rehearsal@example.invalid", "a@example.invalid\n"])
def test_alias_display_name_partial_group_and_malformed_values_rejected(monkeypatch, value):
    state = install_native(monkeypatch, handle=value)
    with pytest.raises(recipients.RecipientEvidenceError):
        recipients.read(state.snapshot)


@pytest.mark.parametrize("case", ["title_only", "sidebar_only", "body_only", "missing_relationship",
    "label_outside_scope", "duplicate_to", "cc", "bcc", "hidden_to", "hidden_container",
    "token_children", "unreadable_value", "disabled", "missing_bcc", "web", "cycle", "depth", "budget",
    "missing_children", "unreadable_role", "foreign_target", "sheet", "nested_sheet", "ocr", "no_focus",
    "recipient_target", "value_changes_during_read"])
def test_unsupported_or_incomplete_native_evidence_fails_closed(monkeypatch, case):
    state = install_native(monkeypatch)
    n = state.nodes
    if case in {"title_only", "sidebar_only", "body_only"}:
        n["headers"]["AXChildren"] = []
        state.snapshot = replace(state.snapshot, window_title="Mom — +1 555 0142")
        if case == "body_only":
            n["body"]["AXChildren"] = ["to-label", "to"]
    elif case == "missing_relationship":
        del n["to"]["AXTitleUIElement"]
    elif case == "label_outside_scope":
        n["headers"]["AXChildren"].remove("to-label")
    elif case == "duplicate_to":
        n["other-to"] = copy.deepcopy(n["to"])
        n["headers"]["AXChildren"].append("other-to")
    elif case in {"cc", "bcc"}:
        n[case]["AXValue"] = "+1 555 0142"
    elif case in {"hidden_to", "hidden_container"}:
        n["to" if case == "hidden_to" else "headers"]["AXHidden"] = True
    elif case == "token_children":
        n["to"]["AXChildren"] = ["token"]
    elif case == "unreadable_value":
        del n["to"]["AXValue"]
    elif case == "disabled":
        n["to"]["AXEnabled"] = False
    elif case == "missing_bcc":
        n["headers"]["AXChildren"].remove("bcc")
    elif case == "web":
        n["headers"]["AXRole"] = "AXWebArea"
    elif case == "cycle":
        n["headers"]["AXChildren"].append("window")
    elif case in {"depth", "budget"}:
        count = 30 if case == "depth" else 520
        n["window"]["AXChildren"].append("extra0")
        for i in range(count):
            n[f"extra{i}"] = {"AXRole": "AXGroup", "AXChildren": [f"extra{i+1}"] if i+1 < count else []}
        if case == "budget":
            n["window"]["AXChildren"] += [f"extra{i}" for i in range(1, count)]
            for i in range(count):
                n[f"extra{i}"]["AXChildren"] = []
    elif case in {"missing_children", "unreadable_role"}:
        del n["headers"]["AXChildren" if case == "missing_children" else "AXRole"]
    elif case == "foreign_target":
        n["window"]["AXChildren"].remove("send")
    elif case == "sheet":
        n["window"]["AXRole"] = "AXSheet"
    elif case == "nested_sheet":
        n["window"]["AXChildren"].append("sheet")
        n["sheet"] = {"AXRole": "AXSheet"}
    elif case == "recipient_target":
        monkeypatch.setattr(ax, "resolve", lambda sid, eid: (state.snapshot.focused, "to"))
    elif case == "value_changes_during_read":
        attribute = ax.attribute
        def changed(node, name, default=None):
            if node == "bcc" and name == "AXValue":
                n["to"]["AXValue"] = "outside@example.invalid"
            return attribute(node, name, default)
        monkeypatch.setattr(ax, "attribute", changed)
    elif case == "ocr":
        target = replace(state.snapshot.focused, source="ocr")
        state.snapshot = replace(state.snapshot, focused=target, elements=[target])
    elif case == "no_focus":
        state.snapshot = replace(state.snapshot, focused=None)
    with pytest.raises(recipients.RecipientEvidenceError):
        recipients.read(state.snapshot)


@pytest.mark.parametrize("case", ["window", "focus", "stale", "no_identity", "ax_error", "bundle", "bounds"])
def test_native_identity_and_failed_rechecks_are_blocked(monkeypatch, case):
    state = install_native(monkeypatch)
    if case == "window":
        state.window = "different-window"
    elif case == "focus":
        def context(_):
            return state.identity, "different-focus" if len(state.verified) > 1 else "send"
        monkeypatch.setattr(ax, "snapshot_context", context)
    elif case == "stale":
        def stale(_):
            raise ValueError("stale_snapshot, re-read")
        monkeypatch.setattr(ax, "verify_snapshot", stale)
    elif case == "no_identity":
        monkeypatch.setattr(ax, "snapshot_context", lambda _: None)
    elif case == "ax_error":
        def unavailable(*_):
            raise RuntimeError("Synthetic private handle must not be included")
        monkeypatch.setattr(ax, "front_window", unavailable)
    elif case == "bundle":
        state.snapshot = replace(state.snapshot, bundle_id="com.apple.Safari")
    elif case == "bounds":
        state.identity = replace(state.identity, bbox=(100, 100, 500, 400))
    with pytest.raises(recipients.RecipientEvidenceError) as error:
        recipients.read(state.snapshot)
    assert "private handle" not in str(error.value)
