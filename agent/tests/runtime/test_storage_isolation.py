"""Storage tripwires run before a read even if the suite guard regresses."""
import os
from pathlib import Path

import pytest

from gaze_agent import profile, tasklog


def test_default_stores_and_profile_helper_are_temporary(monkeypatch, tmp_path):
    original_load = profile.ProfileStore._load
    original_prune = tasklog.TaskLog.prune

    def checked_load(store, *args):
        assert store.directory.is_relative_to(tmp_path), "storage read tripwire"
        return original_load(store, *args)

    def checked_prune(log):
        assert log.path.is_relative_to(tmp_path), "storage read tripwire"
        return original_prune(log)

    monkeypatch.setattr(profile.ProfileStore, "_load", checked_load)
    monkeypatch.setattr(tasklog.TaskLog, "prune", checked_prune)
    assert profile.load_profile() == profile.DEFAULT_PROFILE
    store = profile.ProfileStore()
    assert store.load_settings() == profile.DEFAULT_SETTINGS
    log = tasklog.TaskLog()
    log.event(task_id="synthetic", plan_label="", tool="test", outcome="done")
    assert (store.directory / "profile.json").is_file()
    assert log.path.is_file()


@pytest.mark.parametrize("store_class", [profile.ProfileStore, tasklog.TaskLog])
@pytest.mark.parametrize("suffix", ["", "nested", "../GazeCopilot/nested", "-backup"])
def test_private_paths_fail_before_constructor_io(monkeypatch, store_class, suffix):
    # Only construct names: do not stat/resolve/read the actual private tree.
    directory = (Path(str(profile.DATA_DIR) + suffix) if suffix == "-backup"
                 else profile.DATA_DIR / suffix)
    touched = []

    def tripwire(*args, **kwargs):
        touched.append(True)
        raise AssertionError("storage IO tripwire")

    monkeypatch.setattr(profile.ProfileStore, "_load", tripwire)
    monkeypatch.setattr(tasklog.TaskLog, "prune", tripwire)
    monkeypatch.setattr(Path, "resolve", tripwire)
    with pytest.raises(AssertionError, match="private user storage"):
        store_class(directory)
    assert touched == []


@pytest.mark.parametrize("store_class", [profile.ProfileStore, tasklog.TaskLog])
def test_temporary_symlink_cannot_escape_storage_root(monkeypatch, tmp_path, store_class):
    # A dangling synthetic target models a private tree without touching one.
    target = Path("/gaze-isolation-nonexistent-private")
    link = tmp_path / "escape"
    link.symlink_to(target, target_is_directory=True)
    touched = []

    def tripwire(*args, **kwargs):
        touched.append(True)
        raise AssertionError("storage IO tripwire")

    monkeypatch.setattr(tasklog.TaskLog, "prune", tripwire)
    monkeypatch.setattr(Path, "resolve", tripwire)
    with pytest.raises(AssertionError, match="private user storage"):
        store_class(link / "nested")
    assert touched == []


def test_explicit_temporary_stores_still_work(tmp_path):
    directory = tmp_path / "explicit"
    store = profile.ProfileStore(directory, demo=False)
    assert store.update_profile({"name": "Synthetic test persona"})["name"] == "Synthetic test persona"
    assert tasklog.TaskLog(directory).path.parent == directory


def test_root_guard_strips_credentials_and_isolates_cache(tmp_path):
    from gaze_agent import llm

    assert not any(name in os.environ for name in (
        "OPENAI_API_KEY", "OPENAI_ADMIN_KEY", "AZURE_OPENAI_API_KEY"))
    assert os.environ["PYTHON_DOTENV_DISABLED"] == "1"
    assert llm.CACHE_DIR.is_relative_to(tmp_path)
