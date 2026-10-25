"""Suite-wide isolation, including tests outside the runtime/brain directories."""
from pathlib import Path

import pytest

from gaze_agent import llm, profile, tasklog


@pytest.fixture(autouse=True)
def isolate_private_storage_and_live_api(monkeypatch, tmp_path):
    """Default stores must never read/create the user's Application Support data.

    Explicit test directories still work; narrower tests may inject their own
    fake API client after this guard. No real profile contents are needed.
    """
    for store_class in (profile.ProfileStore, tasklog.TaskLog):
        original = store_class.__init__
        def isolated_init(self, directory=None, *, _original=original, **kwargs):
            if directory is None:
                directory = tmp_path / "isolated-user-data"
            if Path(directory).resolve() == profile.DATA_DIR.resolve():
                raise AssertionError("Tests must not access private user storage")
            _original(self, directory, **kwargs)
        monkeypatch.setattr(store_class, "__init__", isolated_init)

    def forbidden_client(*args, **kwargs):
        raise AssertionError("Tests must inject a fake OpenAI client")
    monkeypatch.setattr(llm, "AsyncOpenAI", forbidden_client)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("DEMO_MODE", "0")
    monkeypatch.setenv("REPLAY", "off")
