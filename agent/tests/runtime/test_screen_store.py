import copy
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from gaze_agent import profile, screen
from gaze_agent.screen import ax, ocr, shot
from gaze_agent.tasklog import TaskLog
from tests.runtime.support import SEND, SNAPSHOT


def test_recorded_ax_fixture_compacts_and_preserves_focus():
    fixture = json.loads((Path(__file__).parent / "fixtures/ax_tree.json").read_text())
    # A wide repeated subtree models a long document; focus occurs after 150.
    fixture["children"] = fixture["children"] * 80 + [
        {"role": "AXTextArea", "label": "Message", "bbox": [10, 500, 300, 50], "focused": True}]
    snapshot, _ = ax.compact_tree(fixture, app="Messages", bundle_id="com.apple.MobileSMS", window_title="Mom")
    assert len(snapshot.elements) == 150 and snapshot.focused in snapshot.elements
    assert snapshot.focused.label == "Message"
    for element in snapshot.elements:
        assert re.fullmatch(r'e\d+ \| AX\w+ \| ".*" \| (enabled|disabled) \| \(-?\d+,-?\d+,\d+,\d+\)', element.to_line())


def test_snapshot_registry_rejects_stale_ids():
    ax.publish(SNAPSHOT, {"e1": "fake-handle"})
    assert ax.resolve(SNAPSHOT.snapshot_id, "e1") == (SEND, "fake-handle")
    ax.publish(replace(SNAPSHOT, snapshot_id="new"))
    with pytest.raises(ValueError, match="stale_snapshot"):
        ax.resolve(SNAPSHOT.snapshot_id, "e1")


def test_ocr_offsets_and_inverts_window_coordinates():
    target = shot.TargetWindow(42, 400, 200, 1000, 500)
    assert ocr.screen_bbox((0.1, 0.2, 0.3, 0.1), target) == (500, 550, 300, 50)


def test_sparse_ax_uses_fake_ocr_and_retains_focus(monkeypatch):
    monkeypatch.setattr(ax, "read_snapshot", lambda: (copy.deepcopy(SNAPSHOT), {}))
    text = replace(SEND, id="o1", role="text", label="Tickets", source="ocr")
    monkeypatch.setattr(ocr, "read_ocr", lambda: [text])
    result = screen.get_screen()
    assert result.focused == SEND and result.elements == [SEND, text]


def test_dense_ax_never_captures(monkeypatch):
    dense = replace(SNAPSHOT, elements=[replace(SEND, id=f"e{i}") for i in range(5)])
    monkeypatch.setattr(ax, "read_snapshot", lambda: (dense, {}))
    assert screen.get_screen() == dense


def test_window_capture_command_is_window_only_and_temporary(monkeypatch):
    import subprocess
    calls = []
    def fake_run(args, **kwargs):
        calls.append(args)
        Path(args[-1]).write_bytes(b"fake-png")
    monkeypatch.setattr(subprocess, "run", fake_run)
    # Override the suite's explicit prohibition with the pure command-building implementation.
    import importlib
    module = importlib.reload(shot)
    assert module.capture_window(module.TargetWindow(42, 10, 20, 800, 600)) == b"fake-png"
    assert calls[0][:-1] == ["screencapture", "-x", "-o", "-l", "42"]
    assert not Path(calls[0][-1]).exists()


def test_profile_settings_merge_patch_is_atomic_and_strict(tmp_path):
    store = profile.ProfileStore(tmp_path, demo=False)
    old = store.load_profile()
    saved = store.update_profile({"favorites": {"playlist": "Lo-fi"}})
    assert saved["favorites"]["playlist"] == "Lo-fi"
    assert saved["favorites"]["artist"] == old["favorites"]["artist"]
    original = store.load_settings()
    for patch in [{"dwellMs": 50}, {"dwellMs": "1000"}, {"blinkSelect": "false"},
                  {"density": "tiny"}, {"dwellMs": None}, {"payment": "private"}]:
        with pytest.raises(ValidationError):
            store.update_settings(patch)
        assert store.load_settings() == original
    assert not list(tmp_path.glob(".*.json.*"))
    assert (tmp_path / "profile.json").stat().st_mode & 0o777 == 0o600


def test_demo_profile_copied_only_on_first_run(tmp_path):
    fixture = tmp_path / "demo.json"
    value = copy.deepcopy(profile.DEFAULT_PROFILE)
    value["name"] = "Sam Rivera"
    fixture.write_text(json.dumps(value))
    store = profile.ProfileStore(tmp_path / "data", demo=True, demo_profile=fixture)
    assert store.load_profile()["name"] == "Sam Rivera"
    store.update_profile({"name": "Saved demo name"})
    assert store.load_profile()["name"] == "Saved demo name"
    with pytest.raises(FileNotFoundError):
        profile.ProfileStore(tmp_path / "missing", demo=True, demo_profile=tmp_path / "absent").load_profile()


def test_address_is_opt_in_and_no_payment_fields(tmp_path):
    value = copy.deepcopy(profile.DEFAULT_PROFILE)
    value["address"]["email"] = "sam@example.invalid"
    assert "sam@example.invalid" not in profile.profile_summary(value)
    assert "sam@example.invalid" in profile.profile_summary(value, include_address=True)
    store = profile.ProfileStore(tmp_path, demo=False)
    with pytest.raises(ValidationError):
        store.update_profile({"card_number": "fake"})


def test_tasklog_retention_and_body_redaction(tmp_path, monkeypatch):
    monkeypatch.setenv("DEBUG", "0")
    now = 2000000
    path = tmp_path / "tasklog.jsonl"
    path.write_text(json.dumps({"ts": now - 8 * 86400, "task_id": "old"}) + "\n" +
                    json.dumps({"ts": now - 1, "task_id": "recent"}) + "\ninvalid\n")
    log = TaskLog(tmp_path, clock=lambda: now)
    log.event(task_id="new", plan_label="PRIVATE MESSAGE", tool="type_text", element_label="PRIVATE MESSAGE",
              outcome="done", body="PRIVATE MESSAGE", screenshot="PRIVATE IMAGE", ax="PRIVATE TREE")
    content = path.read_text()
    assert "old" not in content and "recent" in content and "new" in content
    assert "PRIVATE" not in content and "screenshot" not in content
    assert all("ts" in json.loads(line) for line in content.splitlines())
