"""Native regressions: every OS entry point is replaced before use."""
import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest

from gaze_agent import actions, screen
from gaze_agent.screen import ax
from tests.runtime.test_screen_store import (
    NATIVE_DISPATCH, app_launch_fakes, fake_native_screen, native_action_fakes,
)


@pytest.fixture(autouse=True)
def block_unfaked_native_entry_points(monkeypatch):
    class Blocked:
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            raise AssertionError(f"Native test must fake {name}")
    for module in ("ApplicationServices", "AppKit", "Foundation", "Quartz", "pyautogui"):
        monkeypatch.setitem(sys.modules, module, Blocked())
    monkeypatch.setattr(actions, "subprocess", Blocked())
    ax.invalidate()
    yield
    ax.invalidate()


def typing_scene(monkeypatch, **kwargs):
    state = fake_native_screen(monkeypatch)
    snapshot = screen.get_screen()
    driver, events, board, original = native_action_fakes(monkeypatch, **kwargs)
    return state, snapshot, driver, events, board, original


def assert_invalidated(snapshot):
    assert ax.snapshot_context(snapshot.snapshot_id) is None
    with pytest.raises(ValueError, match="stale_snapshot"):
        ax.resolve(snapshot.snapshot_id, snapshot.elements[0].id)


def test_typing_without_a_focused_control_never_touches_clipboard(monkeypatch):
    state, snapshot, driver, events, board, original = typing_scene(monkeypatch)
    attribute = ax.attribute
    monkeypatch.setattr(ax, "attribute", lambda handle, name, default=None:
                        None if name == "AXFocusedUIElement" else attribute(handle, name, default))
    with pytest.raises(ValueError, match="cannot_focus_text_target"):
        driver.type_text("Synthetic text")
    assert events == [] and board.items is original
    assert_invalidated(snapshot)


def test_implicit_target_cannot_change_during_focus_lookup(monkeypatch):
    state, snapshot, driver, events, board, original = typing_scene(monkeypatch)
    front, calls = ax.front_window, []
    def delayed_front():
        calls.append(True)
        if len(calls) == 2:
            state.windows["messages"]["field"] = 99
        return front()
    monkeypatch.setattr(ax, "front_window", delayed_front)
    with pytest.raises(ax.WindowChanged):
        driver.type_text("Synthetic text", snapshot_id=snapshot.snapshot_id)
    assert events == [] and board.items is original
    assert_invalidated(snapshot)


@pytest.mark.parametrize("named", [False, True])
@pytest.mark.parametrize("value_ok,paste_ok", [(True, True), (False, True), (False, False)])
def test_stable_native_typing_preserves_clipboard_and_does_not_submit(monkeypatch, named, value_ok, paste_ok):
    _, snapshot, driver, events, board, original = typing_scene(monkeypatch, value_ok=value_ok, paste_ok=paste_ok)
    args = {"text": "Synthetic text"}
    if named:
        args.update(id=snapshot.focused.id, snapshot_id=snapshot.snapshot_id)
    assert NATIVE_DISPATCH(driver, "type_text", args, snapshot) == {"ok": True}
    assert [item.data for item in board.items] == [item.data for item in original]
    assert ("keys", ["enter"]) not in events
    if value_ok:
        assert board.items is original and not any(event[0] == "clear" for event in events)
    elif paste_ok:
        assert ("keys", ["cmd", "v"]) in events
    else:
        assert "".join(event[1] for event in events if event[0] == "key_text") == args["text"]


def test_explicit_target_can_be_focused_before_guarded_paste(monkeypatch):
    state, snapshot, driver, events, board, original = typing_scene(monkeypatch)
    context = ax.snapshot_context(snapshot.snapshot_id)
    target = replace(snapshot.focused, id="new-field", label="Other demo field")
    snapshot = replace(snapshot, elements=[*snapshot.elements, target])
    with ax.screen_read() as read:
        read.identity = context[0]
        ax.publish(snapshot, {snapshot.focused.id: 3, target.id: 99})
    set_attribute = sys.modules["ApplicationServices"].AXUIElementSetAttributeValue
    def focus_target(handle, name, value):
        if name == "AXFocused":
            state.windows["messages"]["field"] = handle
        return set_attribute(handle, name, value)
    monkeypatch.setattr(sys.modules["ApplicationServices"], "AXUIElementSetAttributeValue", focus_target)
    driver.type_text("Synthetic text", target.id, snapshot.snapshot_id)
    assert ("keys", ["cmd", "v"]) in events
    assert [item.data for item in board.items] == [item.data for item in original]


def test_window_change_while_writing_clipboard_restores_it_without_pasting(monkeypatch):
    state, snapshot, driver, events, board, original = typing_scene(monkeypatch)
    set_string = board.setString_forType_
    def write(text, kind):
        state.current = "other_messages"
        return set_string(text, kind)
    monkeypatch.setattr(board, "setString_forType_", write)
    with pytest.raises(ax.WindowChanged):
        driver.type_text("Synthetic text", snapshot.focused.id, snapshot.snapshot_id)
    assert not any(event[0] == "keys" for event in events)
    assert [item.data for item in board.items] == [item.data for item in original]
    assert_invalidated(snapshot)


def test_per_character_fallback_stops_after_context_changes(monkeypatch):
    state, snapshot, driver, events, board, original = typing_scene(monkeypatch, paste_ok=False)
    def write(text):
        events.append(("key_text", text))
        state.current = "other_messages"
    monkeypatch.setattr(sys.modules["pyautogui"], "write", write)
    with pytest.raises(ax.WindowChanged):
        driver.type_text("Synthetic text", snapshot.focused.id, snapshot.snapshot_id)
    assert [event for event in events if event[0] == "key_text"] == [("key_text", "S")]
    assert [item.data for item in board.items] == [item.data for item in original]
    assert_invalidated(snapshot)


@pytest.mark.parametrize("destination", ["other_messages", "mail", "unavailable", "moved", "resized", "focus"])
def test_clipboard_preparation_cannot_redirect_paste(monkeypatch, destination):
    state, snapshot, driver, events, board, original = typing_scene(monkeypatch)
    attribute = ax.attribute
    def change():
        if destination == "unavailable":
            state.unavailable = True
        elif destination in {"moved", "resized"}:
            state.windows["messages"]["bbox"] = ((450, 200, 1000, 500) if destination == "moved"
                                                  else (400, 200, 800, 500))
        elif destination == "focus":
            monkeypatch.setattr(ax, "attribute", lambda handle, name, default=None:
                                99 if name == "AXFocusedUIElement" else attribute(handle, name, default))
        else:
            state.current = destination
    data_for_type = original[0].dataForType_
    def copy_data(kind):
        change()
        return data_for_type(kind)
    monkeypatch.setattr(original[0], "dataForType_", copy_data)
    with pytest.raises(ax.WindowChanged):
        driver.type_text("Synthetic text", snapshot.focused.id, snapshot.snapshot_id)
    assert not any(event[0] in {"keys", "key_text", "pasteboard", "clear"} for event in events)
    assert board.items is original
    assert_invalidated(snapshot)


@pytest.mark.parametrize("destination", ["other_messages", "unavailable", "focus", "stopped"])
def test_submit_rechecks_context_and_stop_after_typing(monkeypatch, destination):
    state, snapshot, driver, events, _, _ = typing_scene(monkeypatch)
    attribute = ax.attribute
    def typed(*args):
        if destination == "stopped":
            driver.cancel()
        elif destination == "unavailable":
            state.unavailable = True
        elif destination == "focus":
            monkeypatch.setattr(ax, "attribute", lambda handle, name, default=None:
                                99 if name == "AXFocusedUIElement" else attribute(handle, name, default))
        else:
            state.current = destination
    monkeypatch.setattr(driver, "type_text", typed)
    with pytest.raises(actions.ActionCancelled if destination == "stopped" else ax.WindowChanged):
        NATIVE_DISPATCH(driver, "type_text", {"text": "Synthetic text", "submit": True}, snapshot)
    assert events == []
    if destination != "stopped":
        assert_invalidated(snapshot)


def test_stop_during_clipboard_copy_does_not_clear_or_replace_it(monkeypatch):
    _, snapshot, driver, events, board, original = typing_scene(monkeypatch)
    data_for_type = original[0].dataForType_
    def copy_data(kind):
        driver.cancel()
        return data_for_type(kind)
    monkeypatch.setattr(original[0], "dataForType_", copy_data)
    with pytest.raises(actions.ActionCancelled):
        driver.type_text("Synthetic text", snapshot.focused.id, snapshot.snapshot_id)
    assert not any(event[0] in {"keys", "pasteboard", "clear"} for event in events)
    assert board.items is original


def test_cancelled_click_does_not_resolve_native_snapshot(monkeypatch):
    driver = actions.DesktopActions({})
    driver.cancel()
    def forbidden(*args):
        raise AssertionError("Stopped action must not read AX")
    monkeypatch.setattr(ax, "resolve", forbidden)
    with pytest.raises(actions.ActionCancelled):
        driver.click_element("e1", "old")


def test_failed_ax_press_cannot_redirect_coordinate_fallback(monkeypatch):
    state, snapshot, driver, events, _, _ = typing_scene(monkeypatch)
    def press(handle, name):
        state.current = "other_messages"
        return 1
    monkeypatch.setattr(sys.modules["ApplicationServices"], "AXUIElementPerformAction", press)
    with pytest.raises(ax.WindowChanged):
        driver.click_element(snapshot.focused.id, snapshot.snapshot_id)
    assert events == []
    assert_invalidated(snapshot)


def test_stop_while_constructing_key_event_never_posts_key_down(monkeypatch):
    driver, events = actions.DesktopActions({}), []
    def create(source, code, down):
        driver.cancel()
        return {"code": code, "down": down}
    monkeypatch.setitem(sys.modules, "Quartz", SimpleNamespace(
        kCGEventFlagMaskCommand=1, kCGHIDEventTap=0,
        CGEventCreateKeyboardEvent=create,
        CGEventSetFlags=lambda event, flags: event.update(flags=flags),
        CGEventPost=lambda tap, event: events.append(event.copy())))
    with pytest.raises(actions.ActionCancelled):
        driver.press_keys(["cmd", "v"])
    assert events == [] and not driver.held


@pytest.mark.parametrize("stopped", [False, True])
def test_launcher_exit_race_during_cleanup_still_reaps_child(monkeypatch, stopped):
    driver, state = app_launch_fakes(monkeypatch)
    state.exit_at = float("inf")
    state.cancel_at = 0.05 if stopped else None
    create = actions.subprocess.Popen
    def launch(*args, **kwargs):
        process = create(*args, **kwargs)
        def already_exited():
            state.exit_at = 0
            raise ProcessLookupError("Synthetic child exited before kill")
        process.kill = already_exited
        return process
    monkeypatch.setattr(actions.subprocess, "Popen", launch)
    with pytest.raises(actions.ActionCancelled if stopped else ValueError,
                       match="task stopped" if stopped else "application_activation_timeout"):
        driver.open_app("TextEdit")
    assert state.waited


def test_no_window_times_out_even_after_successful_launch(monkeypatch):
    driver, state = app_launch_fakes(monkeypatch)
    state.window_at = float("inf")
    with pytest.raises(ValueError, match="^application_activation_timeout$"):
        driver.open_app("TextEdit")
    assert state.now == pytest.approx(0.5)


def test_already_running_app_can_become_ready_after_delayed_window(monkeypatch):
    driver, state = app_launch_fakes(monkeypatch)
    state.focus_at = state.exit_at = 0
    state.window_at = 0.3
    driver.open_app("TextEdit")
    assert state.window_at <= state.now < 0.5


def test_cancelled_launch_does_no_resolution_or_process_work(monkeypatch):
    driver, state = app_launch_fakes(monkeypatch)
    driver.cancel()
    with pytest.raises(actions.ActionCancelled):
        driver.open_app("TextEdit")
    assert state.lookups == state.commands == []
