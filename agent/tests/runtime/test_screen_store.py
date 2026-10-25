import copy
import asyncio
import json
import re
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from gaze_agent import actions, profile, screen
from gaze_agent.contracts import LLMResponse
from gaze_agent.permissions import check as permission_check
from gaze_agent.screen import ax, ocr, shot
from gaze_agent.tasklog import TaskLog
from tests.runtime.support import SEND, SNAPSHOT

FIXTURES = Path(__file__).parent / "fixtures"
# Invoke this only after replacing every native entry point in the focus tests.
NATIVE_FRONT_WINDOW = ax.front_window
NATIVE_DISPATCH = actions.DesktopActions._dispatch


def test_default_test_stores_use_temporary_user_data(monkeypatch, tmp_path):
    # Fail before any read if isolation is removed; never inspect the real file.
    original_load = profile.ProfileStore._load
    def checked_load(self, *args, **kwargs):
        assert self.directory.resolve() != profile.DATA_DIR.resolve()
        return original_load(self, *args, **kwargs)
    monkeypatch.setattr(profile.ProfileStore, "_load", checked_load)
    assert profile.load_profile() == profile.DEFAULT_PROFILE
    assert profile.ProfileStore().directory.is_relative_to(tmp_path)
    assert TaskLog().path.is_relative_to(tmp_path)


def test_explicit_private_test_store_is_rejected_without_reading():
    with pytest.raises(AssertionError, match="private user storage"):
        profile.ProfileStore(profile.DATA_DIR)
    with pytest.raises(AssertionError, match="private user storage"):
        TaskLog(profile.DATA_DIR)


@pytest.mark.parametrize("destination", ["other_messages", "mail", "unavailable", "moved"])
@pytest.mark.parametrize("tool,args", [("press_keys", {"keys": ["cmd", "enter"]}),
                                      ("type_text", {"text": "Synthetic text"}),
                                      ("click_element", {"id": "e1", "snapshot_id": "unused"})])
def test_dispatch_rejects_changed_native_window_without_events(monkeypatch, destination, tool, args):
    state = fake_native_screen(monkeypatch)
    snapshot = screen.get_screen()
    driver = actions.DesktopActions({})
    events = []
    monkeypatch.setattr(driver, "press_keys", lambda *a: events.append(a))
    monkeypatch.setattr(driver, "type_text", lambda *a: events.append(a))
    monkeypatch.setattr(driver, "click_element", lambda *a: events.append(a))
    if destination == "unavailable":
        state.unavailable = True
    elif destination == "moved":
        state.windows["messages"]["bbox"] = (100, 100, 500, 500)
    else:
        state.current = destination
    with pytest.raises(ax.WindowChanged):
        NATIVE_DISPATCH(driver, tool, args, snapshot)
    assert events == []
    with pytest.raises(ValueError, match="stale_snapshot"):
        ax.resolve(snapshot.snapshot_id, snapshot.elements[0].id)


def test_dispatch_accepts_stable_native_context_with_fake_keys(monkeypatch):
    fake_native_screen(monkeypatch)
    snapshot = screen.get_screen()
    driver = actions.DesktopActions({})
    events = []
    monkeypatch.setattr(driver, "press_keys", lambda keys: events.append(keys))
    assert NATIVE_DISPATCH(driver, "press_keys", {"keys": ["tab"]}, snapshot) == {"ok": True}
    assert events == [["tab"]]


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


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("demo_*.json")), ids=lambda p: p.stem)
def test_demo_app_ax_fixtures_keep_controls_and_focus(path):
    data = json.loads(path.read_text())
    snapshot, _ = ax.compact_tree(data["tree"], **{k: data[k] for k in
                                                ("app", "bundle_id", "window_title", "url")})
    assert set(data["expected_labels"]) <= {e.label for e in snapshot.elements}
    assert snapshot.focused.label == data["expected_focus"]
    assert snapshot.focused in snapshot.elements and len(snapshot.elements) <= 150
    assert "Hidden control" not in snapshot.to_prompt()


@pytest.mark.parametrize("bbox", [[1, 2, 3], [1, 2, -3, 4], [1, 2, float("nan"), 4], None])
def test_malformed_ax_bounds_do_not_hide_other_controls(bbox):
    tree = {"children": [{"role": "AXButton", "label": "Invalid", "bbox": bbox},
                         {"role": "AXButton", "label": "Send", "bbox": [10, 20, 80, 30]}]}
    snapshot, _ = ax.compact_tree(tree, app="Messages", bundle_id="com.apple.MobileSMS", window_title="Mom")
    assert [e.label for e in snapshot.elements] == ["Send"]


def test_native_ax_reserves_focus_before_large_web_area_and_can_dump(monkeypatch):
    root, window, focus = 1, 2, 5000
    nodes = {root: {"AXFocusedUIElement": focus}, window: {"AXRole": "AXWindow", "AXTitle": "Mom",
             "AXChildren": list(range(10, 3100)) + [focus]},
             focus: {"AXRole": "AXTextArea", "AXValue": "I'll be late", "AXPosition": (10, 500), "AXSize": (300, 50)}}
    for handle in range(10, 3100):
        nodes[handle] = {"AXRole": "AXStaticText", "AXValue": "Sam Rivera demo"}
    app = SimpleNamespace(localizedName=lambda: "Messages", bundleIdentifier=lambda: "com.apple.MobileSMS")
    monkeypatch.setattr(ax, "front_window", lambda: (app, root, window))
    reads = []
    def attribute(handle, name, default=None):
        reads.append(name)
        return nodes[handle].get(name, default)
    monkeypatch.setattr(ax, "attribute", attribute)
    monkeypatch.setattr(ax, "_point", lambda value, kind: value or (0, 0))
    dump = {}
    snapshot, handles = ax.read_snapshot(dump=dump)
    assert len(snapshot.elements) == 150
    assert snapshot.focused.label == "I'll be late" and snapshot.focused in snapshot.elements
    assert handles[snapshot.focused.id] == focus
    assert "AXEnhancedUserInterface" not in reads
    assert '"handle"' not in json.dumps(dump)
    replay, _ = ax.compact_tree(dump["tree"], **{k: dump[k] for k in
                                              ("app", "bundle_id", "window_title", "url")})
    assert replay.elements == snapshot.elements and replay.focused == snapshot.focused


def test_focused_safari_web_area_keeps_its_children_and_dump_roundtrips(monkeypatch):
    nodes = {1: {"AXFocusedUIElement": 3}, 2: {"AXRole": "AXWindow", "AXChildren": [3]},
             3: {"AXRole": "AXWebArea", "AXChildren": [4]},
             4: {"AXRole": "AXLink", "AXValue": "Buy tickets"}}
    app = SimpleNamespace(localizedName=lambda: "Safari", bundleIdentifier=lambda: "com.apple.Safari")
    monkeypatch.setattr(ax, "front_window", lambda: (app, 1, 2))
    monkeypatch.setattr(ax, "attribute", lambda handle, name, default=None: nodes[handle].get(name, default))
    monkeypatch.setattr(ax, "_point", lambda value, kind: value or (0, 0))
    dump = {}
    snapshot, _ = ax.read_snapshot(dump=dump)
    assert [e.label for e in snapshot.elements] == ["", "Buy tickets"]
    replay, _ = ax.compact_tree(dump["tree"], **{k: dump[k] for k in
                                              ("app", "bundle_id", "window_title", "url")})
    assert replay.elements == snapshot.elements and replay.focused == snapshot.focused


def cg_window(number=42, *, pid=100, layer=0, title="Mom", bbox=(400, 200, 1000, 500)):
    return {"kCGWindowNumber": number, "kCGWindowOwnerPID": pid, "kCGWindowLayer": layer,
            "kCGWindowName": title, "kCGWindowBounds": dict(zip(("X", "Y", "Width", "Height"), bbox))}


def test_capture_selects_focused_geometry_and_excludes_overlay_and_other_apps():
    windows = [cg_window(1, pid=999), cg_window(2, layer=1000), cg_window(3, bbox=(0, 0, 800, 600)),
               cg_window(42)]
    target = shot.select_window(windows, pid=100, title="Mom", bbox=(400, 200, 1000, 500))
    assert target == shot.TargetWindow(42, 400, 200, 1000, 500)


@pytest.mark.parametrize("windows,bbox", [
    ([], None), ([cg_window(pid=999)], None), ([cg_window(layer=1000)], None),
    ([cg_window(bbox=(0, 0, 0, 100))], None),
    ([cg_window(1), cg_window(2)], None),
    ([cg_window()], (0, 0, 800, 600)),
])
def test_capture_refuses_missing_or_ambiguous_target(windows, bbox):
    with pytest.raises(RuntimeError, match="focused target window"):
        shot.select_window(windows, pid=100, title="Mom", bbox=bbox)


def test_capture_geometry_works_without_cg_titles_or_primary_display_origin():
    window = cg_window(title="", bbox=(-1200, -100, 1000, 500))
    assert shot.select_window([window], pid=100, title="Mom", bbox=(-1200, -100, 1000, 500)).x == -1200


@pytest.mark.parametrize("box,expected", [
    ((0, 0, 1, 1), (-1200, -100, 1000, 500)),
    ((0.1, 0.2, 0.3, 0.1), (-1100, 250, 300, 50)),
    ((-0.1, 0.9, 0.3, 0.2), (-1200, -100, 200, 50)),
])
def test_ocr_retina_and_secondary_display_coordinates(box, expected):
    # Vision's normalized boxes apply equally to full-size and downscaled images.
    assert ocr.screen_bbox(box, shot.TargetWindow(42, -1200, -100, 1000, 500)) == expected


@pytest.mark.parametrize("box", [(2, 0, 0.2, 0.2), (0, 0, 0, 1), (0, 0, float("inf"), 1)])
def test_ocr_rejects_unclickable_boxes(box):
    with pytest.raises(ValueError):
        ocr.screen_bbox(box, shot.TargetWindow(42, 400, 200, 1000, 500))


def test_sparse_ocr_retains_ax_handles_and_focus_under_150_element_cap(monkeypatch):
    compose = replace(SEND, id="e2", role="AXTextArea", label="Message", bbox=(10, 500, 300, 50))
    snapshot = replace(SNAPSHOT, focused=compose, elements=[SEND, compose])
    monkeypatch.setattr(ax, "read_snapshot", lambda: (snapshot, {"e1": "send-handle", "e2": "compose-handle"}))
    monkeypatch.setattr(ocr, "read_ocr", lambda: [replace(SEND, id=f"o{i}", role="text", source="ocr",
                                                       label=f"Demo text {i}") for i in range(150)])
    result = screen.get_screen()
    assert len(result.elements) == 150 and result.focused == compose
    assert SEND in result.elements and compose in result.elements
    assert ax.resolve(result.snapshot_id, "e1") == (SEND, "send-handle")
    with pytest.raises(ValueError, match="unknown_element"):
        ax.resolve(result.snapshot_id, "o149")


@pytest.mark.parametrize("error", [RuntimeError("permission denied"), OSError("capture failed"),
                                  subprocess.CalledProcessError(1, ["fake-capture"])])
def test_ocr_failure_keeps_usable_ax_controls(monkeypatch, error):
    monkeypatch.setattr(ax, "read_snapshot", lambda: (SNAPSHOT, {"e1": "send-handle"}))
    def fail():
        raise error
    monkeypatch.setattr(ocr, "read_ocr", fail)
    assert screen.get_screen() == SNAPSHOT
    assert ax.resolve(SNAPSHOT.snapshot_id, "e1") == (SEND, "send-handle")


@pytest.mark.parametrize("xy,expected", [([500, 250], (-200, 700)), ([999.9, 499.9], (799, 1199)),
                                       ([1000, 500], None), ([-1, 0], None), ([True, False], None),
                                       ([float("nan"), 2], None)])
def test_explicit_vision_uses_window_jpeg_and_scales_only_valid_points(monkeypatch, xy, expected):
    target = shot.TargetWindow(42, -1200, 200, 2000, 1000)
    captures, calls = [], []
    monkeypatch.setattr(shot, "target_window", lambda: target)
    monkeypatch.setattr(shot, "capture_window", lambda window: captures.append(window) or b"fake-png")
    monkeypatch.setattr(shot, "vision_image", lambda raw: (b"fake-jpeg", (1000, 500)))
    async def complete(prompt, model, variables, **kwargs):
        calls.append((prompt, model, variables, kwargs))
        return LLMResponse(json.dumps({"answer": "Demo control", "point": xy}), [], "fake-response", False)
    monkeypatch.setattr(shot.llm, "complete", complete)
    result = asyncio.run(shot.look_at_screen("Where is the demo control?"))
    assert result.answer == "Demo control" and result.point == expected
    assert captures == [target]
    assert calls == [("look_at_screen", "vision", {"question": "Where is the demo control?"},
                      {"image_jpeg": b"fake-jpeg"})]


def test_fixture_cli_never_reads_desktop_and_roundtrips_json(capsys):
    from gaze_agent.screen.__main__ import main
    main(["--fixture", str(FIXTURES / "demo_safari_tickets.json"), "--json"])
    data = json.loads(capsys.readouterr().out)
    assert data["app"] == "Safari" and data["focused"]["label"] == "Quantity"
    assert data["url"].endswith("/checkout")


def test_dump_cli_saves_no_native_handles_and_refuses_overwrite(monkeypatch, tmp_path, capsys):
    from gaze_agent.screen.__main__ import main
    data = json.loads((FIXTURES / "demo_messages.json").read_text())
    def read(*, dump):
        dump.update({key: data[key] for key in ("app", "bundle_id", "window_title", "url", "tree")})
        return SNAPSHOT, {}
    monkeypatch.setattr(ax, "read_snapshot", read)
    path = tmp_path / "messages.json"
    main(["--dump-ax", str(path)])
    capsys.readouterr()
    assert json.loads(path.read_text())["tree"] == data["tree"]
    with pytest.raises(SystemExit) as error:
        main(["--dump-ax", str(path)])
    assert error.value.code == 2
    assert json.loads(path.read_text())["tree"] == data["tree"]


def native_action_fakes(monkeypatch, *, value_ok=False, focus_ok=True, paste_ok=True):
    """Fake every native entry point before calling the action implementations."""
    events = []
    class Item:
        def __init__(self, data=None):
            self.data = dict(data or {})
        def types(self):
            return list(self.data)
        def dataForType_(self, kind):
            return self.data[kind]
        def setData_forType_(self, data, kind):
            self.data[kind] = data
    original = [Item({"public.utf8-plain-text": b"demo clipboard", "public.png": b"fake-image"}),
                Item({"public.html": b"<b>demo clipboard</b>"})]
    class Board:
        def __init__(self):
            self.items = original
        def pasteboardItems(self):
            return self.items
        def clearContents(self):
            events.append(("clear",))
            self.items = []
        def setString_forType_(self, text, kind):
            events.append(("pasteboard", text))
            self.items = [Item({kind: text.encode()})]
            return paste_ok
        def writeObjects_(self, items):
            events.append(("restore",))
            self.items = items
    board = Board()
    def set_attribute(handle, name, value):
        events.append((name, value))
        return 0 if (value_ok if name == "AXValue" else focus_ok) else 1
    monkeypatch.setitem(sys.modules, "ApplicationServices", SimpleNamespace(
        AXUIElementSetAttributeValue=set_attribute,
        AXUIElementPerformAction=lambda handle, name: events.append(("AXPress", handle)) or 1))
    monkeypatch.setitem(sys.modules, "AppKit", SimpleNamespace(
        NSPasteboard=SimpleNamespace(generalPasteboard=lambda: board), NSPasteboardTypeString="public.utf8-plain-text",
        NSPasteboardItem=SimpleNamespace(alloc=lambda: SimpleNamespace(init=Item))))
    monkeypatch.setitem(sys.modules, "Quartz", SimpleNamespace(
        kCGEventLeftMouseDown="down", kCGEventLeftMouseUp="up", kCGMouseButtonLeft=0, kCGHIDEventTap=0,
        CGEventCreateMouseEvent=lambda source, kind, center, button: (kind, center),
        CGEventPost=lambda tap, event: events.append(event)))
    monkeypatch.setitem(sys.modules, "pyautogui", SimpleNamespace(
        write=lambda text: events.append(("key_text", text)), click=lambda *xy: events.append(("click", xy))))
    driver = actions.DesktopActions({})
    monkeypatch.setattr(driver, "press_keys", lambda keys: events.append(("keys", keys)))
    monkeypatch.setattr(driver.cancelled, "wait", lambda timeout: False)
    return driver, events, board, original


def publish_text_target(*, handle="text-handle", enabled=True):
    field = replace(SEND, role="AXTextArea", label="Message", enabled=enabled, bbox=(10, 500, 300, 50))
    snapshot = replace(SNAPSHOT, focused=field, elements=[field])
    ax.publish(snapshot, {field.id: handle} if handle is not None else {})
    return field


def test_ax_value_typing_leaves_clipboard_untouched(monkeypatch):
    driver, events, board, original = native_action_fakes(monkeypatch, value_ok=True)
    field = publish_text_target()
    driver.type_text("I'll be late", field.id, SNAPSHOT.snapshot_id)
    assert events == [("AXFocused", True), ("AXValue", "I'll be late")]
    assert board.items is original


@pytest.mark.parametrize("paste_ok", [True, False])
def test_typing_fallback_restores_all_clipboard_items_and_types(monkeypatch, paste_ok):
    driver, events, board, original = native_action_fakes(monkeypatch, paste_ok=paste_ok)
    field = publish_text_target()
    driver.type_text("hello world", field.id, SNAPSHOT.snapshot_id)
    assert [item.data for item in board.items] == [item.data for item in original]
    assert ("keys", ["cmd", "v"]) in events if paste_ok else ("key_text", "h") in events
    assert ("keys", ["enter"]) not in events


def test_stop_during_paste_restores_clipboard(monkeypatch):
    driver, events, board, original = native_action_fakes(monkeypatch)
    field = publish_text_target()
    monkeypatch.setattr(driver, "press_keys", lambda keys: driver.cancel())
    with pytest.raises(actions.ActionCancelled):
        driver.type_text("hello world", field.id, SNAPSHOT.snapshot_id)
    assert [item.data for item in board.items] == [item.data for item in original]


def test_failed_focus_clicks_text_target_before_paste(monkeypatch):
    driver, events, _, _ = native_action_fakes(monkeypatch, focus_ok=False)
    field = publish_text_target()
    driver.type_text("hello world", field.id, SNAPSHOT.snapshot_id)
    assert events.index(("down", (160, 525))) < events.index(("keys", ["cmd", "v"]))


def test_typing_never_presses_a_non_editable_send_button(monkeypatch):
    driver, events, _, _ = native_action_fakes(monkeypatch, focus_ok=False)
    ax.publish(SNAPSHOT, {SEND.id: "send-handle"})
    with pytest.raises(ValueError, match="element_not_editable"):
        driver.type_text("hello world", SEND.id, SNAPSHOT.snapshot_id)
    assert events == []


def test_disabled_and_stale_targets_never_type(monkeypatch):
    driver, events, _, _ = native_action_fakes(monkeypatch)
    field = publish_text_target(enabled=False)
    with pytest.raises(ValueError, match="element_disabled"):
        driver.type_text("hello world", field.id, SNAPSHOT.snapshot_id)
    with pytest.raises(ValueError, match="stale_snapshot"):
        driver.type_text("hello world", field.id, "old-snapshot")
    assert events == []


def test_ocr_click_uses_screen_center_without_ax_press(monkeypatch):
    driver, events, _, _ = native_action_fakes(monkeypatch)
    text = replace(SEND, id="o1", role="text", source="ocr", bbox=(-1000, 200, 100, 40))
    ax.publish(replace(SNAPSHOT, elements=[text], focused=None))
    driver.click_element(text.id, SNAPSHOT.snapshot_id)
    assert events == [("down", (-950, 220)), ("up", (-950, 220))]


@pytest.mark.parametrize("recording", [True, False, "error"])
def test_permissions_recheck_screen_recording_independently(monkeypatch, recording):
    def preflight():
        if recording == "error":
            raise RuntimeError("fake permission check failure")
        return recording
    monkeypatch.setitem(sys.modules, "ApplicationServices", SimpleNamespace(AXIsProcessTrusted=lambda: True))
    monkeypatch.setitem(sys.modules, "Quartz", SimpleNamespace(CGPreflightScreenCaptureAccess=preflight))
    assert permission_check() == {"accessibility": True, "screen_recording": recording is True, "camera": "unknown"}


@pytest.mark.parametrize("stop_after_down", [False, True])
def test_key_chord_releases_every_posted_key_even_when_stopped(monkeypatch, stop_after_down):
    driver = actions.DesktopActions({})
    posted = []
    def post(tap, event):
        posted.append(event.copy())
        if stop_after_down and event["down"]:
            driver.cancel()
    monkeypatch.setitem(sys.modules, "Quartz", SimpleNamespace(
        kCGEventFlagMaskCommand=1, kCGEventFlagMaskShift=2, kCGEventFlagMaskAlternate=4,
        kCGEventFlagMaskControl=8, kCGHIDEventTap=0,
        CGEventCreateKeyboardEvent=lambda source, code, down: {"code": code, "down": down},
        CGEventSetFlags=lambda event, flags: event.update(flags=flags), CGEventPost=post))
    if stop_after_down:
        with pytest.raises(actions.ActionCancelled):
            driver.press_keys(["cmd", "enter"])
    else:
        driver.press_keys(["cmd", "enter"])
        assert posted[1] == {"code": 36, "down": True, "flags": 1}
    assert not driver.held
    assert {e["code"] for e in posted if e["down"]} == {e["code"] for e in posted if not e["down"]}


@pytest.mark.parametrize("keys, codes, up_flags", [
    (["cmd", "space"], [55, 49], [1, 0]),
    (["cmd", "shift", "d"], [55, 56, 2], [3, 1, 0]),
    (["v", "cmd"], [55, 9], [1, 0]),
])
def test_key_chords_release_in_reverse_order_with_modifier_flags(monkeypatch, keys, codes, up_flags):
    posted = []
    monkeypatch.setitem(sys.modules, "Quartz", SimpleNamespace(
        kCGEventFlagMaskCommand=1, kCGEventFlagMaskShift=2, kCGEventFlagMaskAlternate=4,
        kCGEventFlagMaskControl=8, kCGHIDEventTap=0,
        CGEventCreateKeyboardEvent=lambda source, code, down: {"code": code, "down": down},
        CGEventSetFlags=lambda event, flags: event.update(flags=flags),
        CGEventPost=lambda tap, event: posted.append(event.copy())))
    driver = actions.DesktopActions({})
    driver.press_keys(keys)
    assert [event["code"] for event in posted if event["down"]] == codes
    released = [event for event in posted if not event["down"]]
    assert [event["code"] for event in released] == codes[::-1]
    assert [event["flags"] for event in released] == up_flags
    assert not driver.held


def native_focus_fakes(monkeypatch):
    monkeypatch.setattr(ax, "_system_focus_unavailable", False)
    state = SimpleNamespace(pid=11, pid_error=0, focused=True, window=True, metadata=True,
                            workspace_reads=0, app_error=0, window_error=0, trusted=True,
                            timeout_error=0, timeouts=[], roots=[], window_reads=0,
                            window_version=0, on_window=None, root_pid=None, system_queries=0)
    apps = {pid: SimpleNamespace(processIdentifier=lambda pid=pid: pid,
                                bundleIdentifier=lambda pid=pid: f"fake.app.{pid}") for pid in (11, 22)}
    def attribute(handle, name, out):
        if handle == "system" and name == "AXFocusedApplication":
            state.system_queries += 1
            return state.app_error, f"app-{state.pid}" if state.focused and not state.app_error else None
        if name == "AXFocusedWindow":
            state.window_reads += 1
            window = f"window-{handle}" if state.window else None
            if window and state.window_version:
                window += f"-{state.window_version}"
            if state.on_window:
                state.on_window(state.window_reads)
            return state.window_error, window
        raise AssertionError("Unexpected fake AX query")
    def timeout(handle, seconds):
        state.timeouts.append((handle, seconds))
        return state.timeout_error
    def application(pid):
        state.roots.append(pid)
        return f"app-{pid}"
    def cached_frontmost():
        state.workspace_reads += 1
        return apps[11]  # Cocoa's cached value never changes in this regression.
    monkeypatch.setitem(sys.modules, "ApplicationServices", SimpleNamespace(
        AXUIElementCreateSystemWide=lambda: "system",
        AXUIElementCreateApplication=application,
        AXUIElementCopyAttributeValue=attribute,
        AXUIElementGetPid=lambda root, out: (state.pid_error,
            state.root_pid if state.root_pid is not None else int(root.removeprefix("app-"))),
        AXUIElementSetMessagingTimeout=timeout,
        AXIsProcessTrusted=lambda: state.trusted))
    monkeypatch.setitem(sys.modules, "AppKit", SimpleNamespace(
        NSWorkspace=SimpleNamespace(sharedWorkspace=lambda: SimpleNamespace(frontmostApplication=cached_frontmost)),
        NSRunningApplication=SimpleNamespace(
            runningApplicationWithProcessIdentifier_=lambda pid: apps.get(pid) if state.metadata else None)))
    return state


def test_front_window_tracks_focus_changes_without_cached_workspace(monkeypatch):
    state = native_focus_fakes(monkeypatch)
    first, root, window = NATIVE_FRONT_WINDOW()
    assert first.processIdentifier() == 11 and root == "app-11" and window == "window-app-11"
    state.pid = 22
    second, root, window = NATIVE_FRONT_WINDOW()
    assert second.processIdentifier() == 22 and root == "app-22" and window == "window-app-22"
    assert state.workspace_reads == 0


@pytest.mark.parametrize("change", [
    {"focused": False}, {"pid_error": -1}, {"pid": 0}, {"metadata": False}, {"window": False},
])
def test_front_window_fails_closed_when_current_focus_is_unavailable(monkeypatch, change):
    state = native_focus_fakes(monkeypatch)
    for key, value in change.items():
        setattr(state, key, value)
    with pytest.raises(RuntimeError):
        NATIVE_FRONT_WINDOW()
    assert state.workspace_reads == 0


def fallback_focus_fakes(monkeypatch):
    """Model the reported -25204; Cocoa stays stale until its main loop runs."""
    state = native_focus_fakes(monkeypatch)
    state.app_error = -25204
    state.cached_pid, state.pumps, state.pump_threads = 11, 0, []
    state.cocoa_error = False
    apps = {pid: SimpleNamespace(processIdentifier=lambda pid=pid: pid,
                                bundleIdentifier=lambda pid=pid: f"fake.app.{pid}") for pid in (11, 22)}
    def pump(date):
        state.pump_threads.append(threading.get_ident())
        assert threading.current_thread() is threading.main_thread()
        state.pumps += 1
        if state.cocoa_error:
            raise RuntimeError("SYNTHETIC_PRIVATE_METADATA")
        state.cached_pid = state.pid
    def front():
        state.workspace_reads += 1
        return apps.get(state.cached_pid)
    sys.modules["AppKit"].NSWorkspace = SimpleNamespace(
        sharedWorkspace=lambda: SimpleNamespace(frontmostApplication=front))
    monkeypatch.setitem(sys.modules, "Foundation", SimpleNamespace(
        NSDate=SimpleNamespace(dateWithTimeIntervalSinceNow_=lambda seconds: seconds),
        NSRunLoop=SimpleNamespace(currentRunLoop=lambda: SimpleNamespace(runUntilDate_=pump))))
    return state


def test_cannot_complete_uses_fresh_cocoa_focus_and_direct_ax_window(monkeypatch):
    state = fallback_focus_fakes(monkeypatch)
    state.pid = 22  # Cocoa still says 11 until pumped.
    app, root, window = NATIVE_FRONT_WINDOW()
    assert app.processIdentifier() == 22 and root == "app-22" and window == "window-app-22"
    state.pid = 11
    assert NATIVE_FRONT_WINDOW()[0].processIdentifier() == 11
    assert state.roots == [22, 11] and state.pumps >= 4
    assert state.system_queries == 1  # no repeated slow system-wide messaging failure
    assert state.window_reads == 4
    assert all(0 < seconds <= 0.25 for _, seconds in state.timeouts)
    assert all(handle != "system" for handle, _ in state.timeouts)  # never change the global AX timeout


def test_fallback_rechecks_permission_after_the_system_route_has_failed(monkeypatch):
    state = fallback_focus_fakes(monkeypatch)
    NATIVE_FRONT_WINDOW()
    reads = state.workspace_reads
    state.trusted = False
    with pytest.raises(RuntimeError):
        NATIVE_FRONT_WINDOW()
    assert state.workspace_reads == reads and state.system_queries == 1


@pytest.mark.parametrize("change", ["app", "window"])
def test_fallback_rejects_focus_changes_during_the_window_read(monkeypatch, change):
    state = fallback_focus_fakes(monkeypatch)
    def changed(read):
        if read == 1:
            if change == "app":
                state.pid = 22
            else:
                state.window_version += 1
    state.on_window = changed
    with pytest.raises(ax.WindowChanged):
        NATIVE_FRONT_WINDOW()


@pytest.mark.parametrize("error", [-25211, -25202, -25205])
def test_other_system_ax_errors_do_not_fall_back(monkeypatch, error):
    state = fallback_focus_fakes(monkeypatch)
    state.app_error = error
    with pytest.raises(RuntimeError):
        NATIVE_FRONT_WINDOW()
    assert state.pumps == 0 and state.roots == []


@pytest.mark.parametrize("change", ["untrusted", "no_window", "window_error", "metadata", "pid", "timeout", "no_app", "cocoa_error"])
def test_fallback_fails_closed_for_unavailable_or_invalid_evidence(monkeypatch, change):
    state = fallback_focus_fakes(monkeypatch)
    if change == "untrusted":
        state.trusted = False
    elif change == "no_window":
        state.window = False
    elif change == "window_error":
        state.window_error = -25204
    elif change == "metadata":
        state.metadata = False
    elif change == "pid":
        state.root_pid = 22
    elif change == "timeout":
        state.timeout_error = -25201
    elif change == "no_app":
        state.pid = 0
    else:
        state.cocoa_error = True
    with pytest.raises(RuntimeError) as error:
        NATIVE_FRONT_WINDOW()
    assert "SYNTHETIC_PRIVATE_METADATA" not in str(error.value)
    if change == "untrusted":
        assert state.pumps == 0
    if change == "timeout":
        assert state.window_reads == 0


def test_worker_fallback_is_marshaled_to_main_thread_and_removed_on_exit(monkeypatch):
    state = fallback_focus_fakes(monkeypatch)
    async def run():
        with ax.main_thread_focus(asyncio.get_running_loop()):
            assert (await asyncio.to_thread(NATIVE_FRONT_WINDOW))[0].processIdentifier() == 11
            state.pid = 22
            assert (await asyncio.to_thread(NATIVE_FRONT_WINDOW))[0].processIdentifier() == 22
        reads = state.workspace_reads
        with pytest.raises(RuntimeError):
            await asyncio.to_thread(NATIVE_FRONT_WINDOW)
        assert state.workspace_reads == reads
    asyncio.run(run())
    assert state.pump_threads and set(state.pump_threads) == {threading.get_ident()}


@pytest.mark.parametrize("close_dispatcher", [False, True])
def test_abandoned_worker_requests_cannot_read_cocoa_later(monkeypatch, close_dispatcher):
    state = fallback_focus_fakes(monkeypatch)
    monkeypatch.setattr(ax, "FOCUS_DISPATCH_TIMEOUT_S", 0.02)
    queued, posted, errors = [], threading.Event(), []
    def enqueue(callback):
        queued.append(callback)
        posted.set()
    def read():
        try:
            NATIVE_FRONT_WINDOW()
        except RuntimeError as error:
            errors.append(str(error))
    with ax.main_thread_focus(SimpleNamespace(call_soon_threadsafe=enqueue)):
        worker = threading.Thread(target=read)
        worker.start()
        assert posted.wait(2)
        if not close_dispatcher:
            worker.join(2)
            assert not worker.is_alive()  # bounded wait, even if the loop never runs
    worker.join(2)
    assert not worker.is_alive() and len(errors) == 1
    for callback in queued:
        callback()
    assert state.pumps == 0 and state.workspace_reads == 0


def app_launch_fakes(monkeypatch):
    state = SimpleNamespace(now=0.0, focus_at=0.15, window_at=0.25, exit_at=0.10, exit_code=0,
                            cancel_at=None, killed=False, waited=False, commands=[], lookups=[],
                            path="/Applications/TextEdit.app", bundle="com.apple.TextEdit")
    workspace = SimpleNamespace(
        fullPathForApplication_=lambda name: state.lookups.append(name) or state.path,
        launchApplication_=lambda name: True)
    monkeypatch.setitem(sys.modules, "AppKit", SimpleNamespace(
        NSWorkspace=SimpleNamespace(sharedWorkspace=lambda: workspace)))
    monkeypatch.setitem(sys.modules, "Foundation", SimpleNamespace(
        NSBundle=SimpleNamespace(bundleWithPath_=lambda path: SimpleNamespace(
            bundleIdentifier=lambda: state.bundle))))
    class Process:
        def poll(self):
            return state.exit_code if state.now >= state.exit_at else None
        def kill(self):
            state.killed, state.exit_at, state.exit_code = True, 0, -9
        def wait(self):
            state.waited = True
            return self.poll()
    def launch(args, **kwargs):
        state.commands.append(args)
        return Process()
    monkeypatch.setattr(actions, "subprocess", SimpleNamespace(Popen=launch, DEVNULL=-3))
    monkeypatch.setattr(actions, "time", SimpleNamespace(monotonic=lambda: state.now), raising=False)
    monkeypatch.setattr(actions, "APP_ACTIVATION_TIMEOUT_S", 0.5, raising=False)
    def front():
        if state.now >= state.focus_at and state.now < state.window_at:
            raise RuntimeError("Target has no focused window yet")
        bundle = state.bundle if state.now >= state.focus_at else "com.apple.Terminal"
        return SimpleNamespace(bundleIdentifier=lambda: bundle), "fake-root", "fake-window"
    monkeypatch.setattr(ax, "front_window", front)
    driver = actions.DesktopActions({})
    def wait(delay):
        state.now += delay
        if state.cancel_at is not None and state.now >= state.cancel_at:
            driver.cancel()
        return driver.cancelled.is_set()
    monkeypatch.setattr(driver.cancelled, "wait", wait)
    return driver, state


def test_open_app_waits_for_target_focus_and_window_then_invalidates_old_snapshot(monkeypatch):
    driver, state = app_launch_fakes(monkeypatch)
    ax.publish(SNAPSHOT)
    driver.open_app("TextEdit")
    assert state.commands == [["/usr/bin/open", "-a", "/Applications/TextEdit.app"]]
    assert state.now >= state.window_at
    with pytest.raises(ValueError, match="stale_snapshot"):
        ax.resolve(SNAPSHOT.snapshot_id, SEND.id)


def test_open_app_never_reports_success_when_target_does_not_activate(monkeypatch):
    driver, state = app_launch_fakes(monkeypatch)
    state.focus_at = float("inf")
    with pytest.raises(ValueError, match="application_activation_timeout"):
        driver.open_app("TextEdit")
    assert state.now >= 0.5


@pytest.mark.parametrize("waiting_for_process", [False, True])
def test_open_app_stop_interrupts_launch_and_focus_waits(monkeypatch, waiting_for_process):
    driver, state = app_launch_fakes(monkeypatch)
    state.exit_at = 10 if waiting_for_process else 0
    state.focus_at, state.cancel_at = float("inf"), 0.05
    with pytest.raises(actions.ActionCancelled):
        driver.open_app("TextEdit")
    assert state.now <= 0.1
    assert state.killed is waiting_for_process
    assert state.waited is waiting_for_process


def test_open_app_kills_a_stalled_launcher_on_timeout(monkeypatch):
    driver, state = app_launch_fakes(monkeypatch)
    state.exit_at = 10
    with pytest.raises(ValueError, match="application_activation_timeout"):
        driver.open_app("TextEdit")
    assert state.killed and state.waited


@pytest.mark.parametrize("invalid", ["missing_app", "missing_bundle", "launcher_failed"])
def test_open_app_rejects_resolution_and_launch_failures(monkeypatch, invalid):
    driver, state = app_launch_fakes(monkeypatch)
    if invalid == "missing_app":
        state.path = None
    elif invalid == "missing_bundle":
        state.bundle = None
    else:
        state.exit_at, state.exit_code = 0, 1
    with pytest.raises(ValueError, match="application_"):
        driver.open_app("TextEdit")
    assert bool(state.commands) is (invalid == "launcher_failed")


def test_open_app_alias_and_already_active_open_dialog(monkeypatch):
    driver, state = app_launch_fakes(monkeypatch)
    state.focus_at, state.window_at, state.exit_at = 0, 0, 0
    driver.open_app("textedit")
    assert state.lookups == ["TextEdit"] and state.now == 0


def fake_native_screen(monkeypatch):
    """Exercise real AX/OCR/capture orchestration with fake native entry points."""
    windows = {
        "messages": {"pid": 100, "app": "Messages", "bundle": "com.apple.MobileSMS", "root": 1,
                     "window": 2, "field": 3, "number": 42, "title": "Mom", "bbox": (400, 200, 1000, 500)},
        # Same app, title and geometry: title-based checks alone cannot detect this switch.
        "other_messages": {"pid": 100, "app": "Messages", "bundle": "com.apple.MobileSMS", "root": 1,
                           "window": 6, "field": 7, "number": 43, "title": "Mom", "bbox": (400, 200, 1000, 500)},
        "mail": {"pid": 200, "app": "Mail", "bundle": "com.apple.mail", "root": 10,
                 "window": 11, "field": 12, "number": 44, "title": "Reply to Alex", "bbox": (-1200, 100, 1000, 500)},
    }
    state = SimpleNamespace(current="messages", windows=windows, captures=[], recognized=[], on_ax=None,
                            on_capture=None, on_ocr=None, now=0.0, unavailable=False)
    def front():
        if state.unavailable:
            raise RuntimeError("No accessible focused window")
        w = windows[state.current]
        app = SimpleNamespace(processIdentifier=lambda: w["pid"], localizedName=lambda: w["app"],
                              bundleIdentifier=lambda: w["bundle"])
        return app, w["root"], w["window"]
    def attribute(handle, name, default=None):
        if state.on_ax is not None:
            state.on_ax(handle, name)
        for w in windows.values():
            if handle == w["root"]:
                current = windows[state.current]
                return current["field"] if name == "AXFocusedUIElement" else default
            if handle == w["window"]:
                x, y, width, height = w["bbox"]
                return {"AXRole": "AXWindow", "AXTitle": w["title"], "AXPosition": (x, y),
                        "AXSize": (width, height), "AXChildren": [w["field"]]}.get(name, default)
            if handle == w["field"]:
                x, y, _, _ = w["bbox"]
                return {"AXRole": "AXTextArea", "AXTitle": "Message", "AXDescription": "Compose",
                        "AXPosition": (x + 20, y + 300), "AXSize": (300, 50)}.get(name, default)
        return default
    def list_windows(options, relative):
        # The other identical Messages window is hidden until selected.
        w = windows[state.current]
        return [cg_window(w["number"], pid=w["pid"], title=w["title"], bbox=w["bbox"])]
    def run(args, **kwargs):
        assert args[:4] == ["screencapture", "-x", "-o", "-l"]
        state.captures.append(int(args[4]))
        Path(args[-1]).write_bytes(b"fake-window-png")
        if state.on_capture is not None:
            state.on_capture()
    def recognize(raw, target, *, fast=False):
        state.recognized.append((target.window_id, fast))
        text = replace(SEND, id="o1", role="text", label=f"Window {target.window_id} demo", source="ocr",
                       bbox=ocr.screen_bbox((0.1, 0.2, 0.3, 0.1), target))
        if state.on_ocr is not None:
            state.on_ocr()
        return [text]
    monkeypatch.setattr(ax, "front_window", front)
    monkeypatch.setattr(ax, "attribute", attribute)
    monkeypatch.setattr(ax, "_point", lambda value, kind: value or (0, 0))
    monkeypatch.setitem(sys.modules, "Quartz", SimpleNamespace(kCGWindowListOptionOnScreenOnly=1,
        kCGNullWindowID=0, CGWindowListCopyWindowInfo=list_windows))
    monkeypatch.setattr(shot.subprocess, "run", run)
    # The OCR module retains the native capture function; its subprocess is fake above.
    monkeypatch.setattr(shot, "capture_window", ocr.capture_window)
    monkeypatch.setattr(shot, "vision_image", lambda raw: (b"fake-jpeg", (1000, 500)))
    monkeypatch.setattr(ocr, "recognize", recognize)
    monkeypatch.setattr(shot, "auto_ocr", shot.AutoOCR(clock=lambda: state.now))
    return state


@pytest.mark.parametrize("auto", [False, True], ids=["task", "auto"])
def test_native_stable_window_combines_only_its_own_ax_and_ocr(monkeypatch, auto):
    state = fake_native_screen(monkeypatch)
    result = screen.get_screen(auto=auto)
    assert result.app == "Messages" and result.window_title == "Mom"
    assert result.focused.label == "Message" and result.focused in result.elements
    assert state.captures == [42] and state.recognized == [(42, auto)]
    assert [e.label for e in result.elements if e.source == "ocr"] == ["Window 42 demo"]
    assert ax.resolve(result.snapshot_id, result.focused.id)[1] == 3


@pytest.mark.parametrize("auto", [False, True], ids=["task", "auto"])
@pytest.mark.parametrize("stage", ["ax", "before_ocr", "before_capture", "capture", "ocr"])
@pytest.mark.parametrize("destination", ["mail", "other_messages"])
def test_window_switch_rejects_read_and_invalidates_old_ids(monkeypatch, auto, stage, destination):
    state = fake_native_screen(monkeypatch)
    ax.publish(SNAPSHOT, {SEND.id: "old-handle"})
    def switch():
        state.current = destination
    if stage == "ax":
        state.on_ax = lambda handle, name: switch() if handle == 3 and name == "AXRole" else None
    elif stage == "before_ocr":
        native_read = ocr.read_ocr
        native_auto_read = shot.auto_ocr.read
        def read_ocr():
            switch()
            return native_read()
        def auto_read(key):
            switch()
            return native_auto_read(key)
        monkeypatch.setattr(ocr, "read_ocr", read_ocr)
        monkeypatch.setattr(shot.auto_ocr, "read", auto_read)
    elif stage == "before_capture":
        select = shot.select_window
        def select_then_switch(*args, **kwargs):
            target = select(*args, **kwargs)
            switch()
            return target
        monkeypatch.setattr(shot, "select_window", select_then_switch)
    elif stage == "capture":
        state.on_capture = switch
    else:
        state.on_ocr = switch
    with pytest.raises(ax.WindowChanged, match="^window_changed, re-read$"):
        screen.get_screen(auto=auto)
    assert len(state.captures) == (1 if stage in {"capture", "ocr"} else 0)
    if stage != "ocr":
        assert state.recognized == []
    with pytest.raises(ValueError, match="stale_snapshot"):
        ax.resolve(SNAPSHOT.snapshot_id, SEND.id)
    assert ax.current_read() is None
    if auto and stage in {"capture", "ocr"}:
        assert shot.auto_ocr.elements == []


@pytest.mark.parametrize("change", ["move", "resize", "title", "capture_id", "closed"])
def test_changed_geometry_title_capture_id_or_closed_window_rejects_capture(monkeypatch, change):
    state = fake_native_screen(monkeypatch)
    def change_window():
        w = state.windows["messages"]
        if change == "move":
            w["bbox"] = (450, 250, 1000, 500)
        elif change == "resize":
            w["bbox"] = (400, 200, 800, 600)
        elif change == "title":
            w["title"] = "Alex"
        elif change == "capture_id":
            w["number"] = 99
        else:
            state.unavailable = True
    state.on_capture = change_window
    with pytest.raises(ax.WindowChanged):
        screen.get_screen()
    assert state.captures == [42] and state.recognized == []


@pytest.mark.parametrize("change", ["same_title_window", "move", "resize"])
def test_auto_cache_never_adds_another_window_or_old_coordinates(monkeypatch, change):
    state = fake_native_screen(monkeypatch)
    original = screen.get_screen(auto=True)
    assert any(e.source == "ocr" for e in original.elements)
    state.now = 59
    if change == "same_title_window":
        state.current = "other_messages"
    elif change == "move":
        state.windows["messages"]["bbox"] = (-1200, 100, 1000, 500)
    else:
        state.windows["messages"]["bbox"] = (400, 200, 800, 600)
    result = screen.get_screen(auto=True)
    assert all(e.source == "ax" for e in result.elements)
    assert state.captures == [42]  # No second attempt inside the 60-second budget.
    state.now = 60
    fresh = screen.get_screen(auto=True)
    number = state.windows[state.current]["number"]
    assert state.captures == [42, number]
    text = next(e for e in fresh.elements if e.source == "ocr")
    w = state.windows[state.current]
    assert text.label == f"Window {number} demo"
    assert text.bbox == ocr.screen_bbox((0.1, 0.2, 0.3, 0.1), shot.TargetWindow(number, *w["bbox"]))


def test_auto_cache_still_reuses_same_native_window_after_counter_change(monkeypatch):
    state = fake_native_screen(monkeypatch)
    state.windows["messages"]["title"] = "Inbox (3)"
    first = screen.get_screen(auto=True)
    state.windows["messages"]["title"] = "Inbox (4)"
    state.now = 59
    second = screen.get_screen(auto=True)
    assert second.window_title == "Inbox (4)"
    assert [e for e in second.elements if e.source == "ocr"] == [e for e in first.elements if e.source == "ocr"]
    assert state.captures == [42]


def test_failed_read_can_be_followed_by_fresh_window_read(monkeypatch):
    state = fake_native_screen(monkeypatch)
    state.on_ocr = lambda: setattr(state, "current", "mail")
    with pytest.raises(ax.WindowChanged):
        screen.get_screen()
    state.on_ocr = None
    fresh = screen.get_screen()
    assert fresh.app == "Mail" and fresh.window_title == "Reply to Alex"
    assert [e.label for e in fresh.elements if e.source == "ocr"] == ["Window 44 demo"]
    assert state.captures == [42, 44]


@pytest.mark.parametrize("auto", [False, True], ids=["task", "auto"])
@pytest.mark.parametrize("switch_window", [False, True], ids=["stable", "switched"])
def test_capture_failure_only_falls_back_to_ax_when_window_is_still_same(monkeypatch, auto, switch_window):
    state = fake_native_screen(monkeypatch)
    def fail_capture():
        if switch_window:
            state.current = "mail"
        raise subprocess.CalledProcessError(1, ["fake-capture"])
    state.on_capture = fail_capture
    if switch_window:
        with pytest.raises(ax.WindowChanged):
            screen.get_screen(auto=auto)
    else:
        snapshot = screen.get_screen(auto=auto)
        assert snapshot.app == "Messages" and snapshot.focused.label == "Message"
        assert all(e.source == "ax" for e in snapshot.elements)
        assert ax.resolve(snapshot.snapshot_id, snapshot.focused.id)[1] == 3
    assert state.captures == [42] and state.recognized == []


def test_concurrent_read_contexts_keep_their_own_window_identity(monkeypatch):
    state = fake_native_screen(monkeypatch)
    async def scenario():
        first_ready, second_ready = asyncio.Event(), asyncio.Event()
        async def messages_read():
            with ax.screen_read() as read:
                snapshot, _ = ax.read_snapshot()
                assert snapshot.app == "Messages"
                first_ready.set()
                await second_ready.wait()
                # Mail became frontmost in the other context; this read must fail.
                with pytest.raises(ax.WindowChanged):
                    read.verify()
                assert ax.current_read() is read and read.identity.window == 2
        async def mail_read():
            await first_ready.wait()
            state.current = "mail"
            with ax.screen_read() as read:
                snapshot, _ = ax.read_snapshot()
                assert snapshot.app == "Mail"
                second_ready.set()
                await asyncio.sleep(0)
                read.verify()
                assert ax.current_read() is read and read.identity.window == 11
        await asyncio.gather(messages_read(), mail_read())
    asyncio.run(scenario())
    assert ax.current_read() is None and state.captures == []
