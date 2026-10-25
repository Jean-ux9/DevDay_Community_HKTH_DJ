"""Suite-wide isolation, also reused by script tests and guarded child helpers."""
import os
from pathlib import Path

import httpx2
import pytest

from gaze_agent import llm, profile, tasklog


def install_test_isolation(monkeypatch, tmp_path, storage_root):
    """Install guards in this interpreter; subprocesses must install their own.

    Reject paths outside pytest's temporary tree before resolving them or
    calling a constructor (TaskLog.__init__ immediately reads/prunes its log).
    Tests may replace the SDK with a fake or inject a mock HTTP transport.
    """
    storage_root = storage_root.resolve()
    for store_class in (profile.ProfileStore, tasklog.TaskLog):
        original = store_class.__init__
        def isolated_init(self, directory=None, *, _original=original, **kwargs):
            if directory is None:
                directory = tmp_path / "isolated-user-data"
            directory = Path(os.path.abspath(directory))
            if not directory.is_relative_to(storage_root):
                raise AssertionError("Tests must not access private user storage")
            parent = storage_root
            for component in directory.relative_to(storage_root).parts:
                parent /= component
                if parent.is_symlink():
                    raise AssertionError("Tests must not access private user storage through symlinks")
            _original(self, directory, **kwargs)
        monkeypatch.setattr(store_class, "__init__", isolated_init)

    def forbidden_client(*args, **kwargs):
        raise AssertionError("Tests must inject a fake OpenAI client")
    monkeypatch.setattr(llm, "AsyncOpenAI", forbidden_client)

    def forbidden_http(*args, **kwargs):
        raise AssertionError("Tests must inject a fake HTTP transport")
    async def forbidden_async_http(*args, **kwargs):
        forbidden_http()
    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", forbidden_http)
    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", forbidden_async_http)
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path / "cache")
    for name in ("OPENAI_API_KEY", "OPENAI_ADMIN_KEY", "AZURE_OPENAI_API_KEY",
                 "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("UV_NO_ENV_FILE", "1")
    monkeypatch.setenv("DEMO_MODE", "0")
    monkeypatch.setenv("REPLAY", "off")


@pytest.fixture(autouse=True)
def isolate_private_storage_and_live_api(monkeypatch, tmp_path, tmp_path_factory):
    install_test_isolation(monkeypatch, tmp_path, tmp_path_factory.getbasetemp())
