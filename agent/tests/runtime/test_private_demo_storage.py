"""Private demo storage (#5): the store, approved allowlist and Send guard input.

Synthetic temporary manifests and FAKE handles only; the public fixture and the
default (test-isolated) store must behave exactly as before.
"""
import json
import uuid
from dataclasses import replace

import pytest

from gaze_agent import demo_config, profile
from gaze_agent.demo_config import DemoConfigError
from gaze_agent.loop import TaskLoop
from gaze_agent.screen import recipients
from gaze_agent.tasklog import TaskLog
from tests.runtime.support import SNAPSHOT, FakeDesktop, look, plan
from tests.runtime.test_demo_config import FAKE_PERSONA, assert_sanitized, select_private
from tests.runtime.test_recipient_evidence import install_native


@pytest.fixture(autouse=True)
def synthetic_selector_only(monkeypatch, tmp_path):
    monkeypatch.delenv(demo_config.SELECTOR_ENV, raising=False)
    monkeypatch.setattr(demo_config, "USER_DATA_DIR", tmp_path / "default-user-data")


def fixture_bytes():
    return profile.DEMO_PROFILE.read_bytes()


def test_default_store_and_allowlist_are_unchanged_without_selector(monkeypatch, tmp_path):
    public = json.loads(fixture_bytes())
    store = profile.ProfileStore.for_demo_config(None)
    assert store.demo_config is None and store.directory == tmp_path / "isolated-user-data"
    assert not store.demo and store.approved_contacts() == {}
    assert profile.load_profile() == profile.DEFAULT_PROFILE
    monkeypatch.setenv("DEMO_MODE", "1")
    demo = profile.ProfileStore.for_demo_config(demo_config.selected())
    assert demo.approved_contacts() == public["contacts"]
    # Existing public behavior: profile edits are stored, never added to the allowlist.
    demo.update_profile({"contacts": {"Boss": ["boss@example.invalid"]}})
    assert demo.approved_contacts() == public["contacts"]


def test_private_store_seeds_persona_only_in_its_private_directory(monkeypatch, tmp_path):
    before = fixture_bytes()
    config = select_private(monkeypatch, tmp_path)
    store = profile.ProfileStore.for_demo_config(config)
    assert store.demo and store.directory == config.data_dir
    assert store.load_profile() == FAKE_PERSONA
    assert profile.load_profile() == FAKE_PERSONA
    saved = config.data_dir / "profile.json"
    assert json.loads(saved.read_text()) == FAKE_PERSONA and saved.stat().st_mode & 0o777 == 0o600
    assert config.data_dir.stat().st_mode & 0o777 == 0o700
    assert store.approved_contacts() == FAKE_PERSONA["contacts"]
    assert TaskLog(store.directory).path.parent == config.data_dir
    assert not (tmp_path / "isolated-user-data").exists() and not (tmp_path / "default-user-data").exists()
    assert fixture_bytes() == before


@pytest.mark.parametrize("patch", [
    {"contacts": {"Boss": ["boss@example.invalid"]}},
    {"contacts": {"Mom": ["+1 555 0142", "+1 555 0199"]}},
    {"contacts": {"Mom": None, "Mother": ["+1 555 0142"]}},
    {"contacts": {"Alex": ["+1 555 0100"]}},
])
def test_private_profile_edits_cannot_enlarge_approved_recipients(monkeypatch, tmp_path, patch):
    store = profile.ProfileStore.for_demo_config(select_private(monkeypatch, tmp_path))
    store.load_profile()
    saved = (store.directory / "profile.json").read_bytes()
    with pytest.raises(DemoConfigError, match="not an approved recipient") as error:
        store.update_profile(patch)
    assert isinstance(error.value, ValueError)  # the server reports bad_message, nothing saved
    assert_sanitized(error.value, tmp_path)
    assert (store.directory / "profile.json").read_bytes() == saved
    assert store.approved_contacts() == FAKE_PERSONA["contacts"]


def test_private_profile_may_drop_contacts_and_edit_other_fields(monkeypatch, tmp_path):
    store = profile.ProfileStore.for_demo_config(select_private(monkeypatch, tmp_path))
    saved = store.update_profile({"contacts": {"Alex": None}, "favorites": {"playlist": "Lo-fi"}})
    assert saved["contacts"] == {"Mom": ["+1 555 0142"]} and saved["favorites"]["playlist"] == "Lo-fi"
    assert store.approved_contacts() == FAKE_PERSONA["contacts"]


def test_tampered_private_profile_file_is_rejected_without_rewrite(monkeypatch, tmp_path):
    config = select_private(monkeypatch, tmp_path)
    tampered = {**FAKE_PERSONA, "contacts": {**FAKE_PERSONA["contacts"], "Boss": ["boss@example.invalid"]}}
    config.data_dir.mkdir()
    (config.data_dir / "profile.json").write_text(json.dumps(tampered))
    before = (config.data_dir / "profile.json").read_bytes()
    with pytest.raises(DemoConfigError, match="not an approved recipient"):
        profile.ProfileStore.for_demo_config(config).load_profile()
    with pytest.raises(DemoConfigError):
        profile.load_profile()
    assert (config.data_dir / "profile.json").read_bytes() == before


def test_private_config_binds_to_its_own_directory_and_demo_mode(monkeypatch, tmp_path):
    config = select_private(monkeypatch, tmp_path)
    with pytest.raises(DemoConfigError, match="own data_dir"):
        profile.ProfileStore(tmp_path / "elsewhere", demo=True, demo_config=config)
    with pytest.raises(DemoConfigError, match="demo mode"):
        profile.ProfileStore(config.data_dir, demo=False, demo_config=config)
    monkeypatch.setenv("DEMO_MODE", "0")
    with pytest.raises(DemoConfigError, match="requires DEMO_MODE=1"):
        profile.load_profile()
    assert not config.data_dir.exists()


def send_guard(tmp_path, active_profile, approved, title, evidence=None):
    task = TaskLoop(task_id=str(uuid.uuid4()), plan=plan(), profile=active_profile, emit=None,
        desktop=FakeDesktop(), get_screen=None, look_at_screen=look, log=TaskLog(tmp_path),
        demo=True, demo_contacts=approved)
    task.snapshot = replace(SNAPSHOT, window_title=title)
    return task.demo_send_allowed(evidence)


@pytest.mark.parametrize("title", ["Mom", "To: Mom", "+1 555 0142", "alex.rehearsal@example.invalid"])
def test_send_guard_rejects_title_only_even_for_approved_contacts(monkeypatch, tmp_path, title):
    store = profile.ProfileStore.for_demo_config(select_private(monkeypatch, tmp_path))
    assert not send_guard(tmp_path, store.load_profile(), store.approved_contacts(), title)


@pytest.mark.parametrize("handle", ["+1 555 0142", "alex.rehearsal@example.invalid"])
def test_send_guard_accepts_approved_changed_handles_with_native_evidence(monkeypatch, tmp_path, handle):
    store = profile.ProfileStore.for_demo_config(select_private(monkeypatch, tmp_path))
    state = install_native(monkeypatch, handle=handle)
    evidence = recipients.read(state.snapshot)
    assert send_guard(tmp_path, store.load_profile(), store.approved_contacts(), "Unrelated title", evidence)


@pytest.mark.parametrize("handle", ["+1 555 0100", "alex@example.com", "boss@example.invalid"])
def test_send_guard_rejects_unapproved_native_handles_even_if_profile_is_widened(monkeypatch, tmp_path, handle):
    store = profile.ProfileStore.for_demo_config(select_private(monkeypatch, tmp_path))
    state = install_native(monkeypatch, handle=handle)
    evidence = recipients.read(state.snapshot)
    widened = {**store.load_profile(), "contacts": {**FAKE_PERSONA["contacts"], "Outside": [handle]}}
    assert not send_guard(tmp_path, widened, store.approved_contacts(), "Mom", evidence)


@pytest.mark.parametrize("title", ["+1 555 0100", "alex@example.com", "Boss", "boss@example.invalid"])
def test_send_guard_rejects_public_placeholders_and_unapproved_contacts(monkeypatch, tmp_path, title):
    store = profile.ProfileStore.for_demo_config(select_private(monkeypatch, tmp_path))
    # Even an active profile that somehow lists Boss cannot widen the allowlist.
    widened = {**store.load_profile(), "contacts": {**FAKE_PERSONA["contacts"], "Boss": ["boss@example.invalid"]}}
    assert not send_guard(tmp_path, widened, store.approved_contacts(), title)
