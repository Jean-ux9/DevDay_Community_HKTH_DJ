"""Exercise isolation in this interpreter and in an independently guarded child."""
import asyncio
import os

import httpx2
import pytest

from gaze_agent import llm, profile, tasklog
from gaze_client import GazeClient
import fake_overlay
import gaze_client
import rehearse


def test_script_defaults_use_temporary_storage(monkeypatch, tmp_path):
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
    assert tasklog.TaskLog().path.is_relative_to(tmp_path)
    assert "OPENAI_API_KEY" not in os.environ
    assert llm.CACHE_DIR.is_relative_to(tmp_path)


@pytest.mark.parametrize("asynchronous", [False, True])
def test_default_http_transport_fails_before_network(monkeypatch, asynchronous):
    # A second tripwire makes this regression safe if the transport guard goes.
    import socket

    def network_tripwire(*args, **kwargs):
        pytest.fail("network tripwire reached")

    monkeypatch.setattr(socket, "getaddrinfo", network_tripwire)
    monkeypatch.setattr(socket.socket, "connect", network_tripwire)
    with pytest.raises(AssertionError, match="fake HTTP transport"):
        if asynchronous:
            async def request():
                async with httpx2.AsyncClient(trust_env=False) as client:
                    await client.get("https://isolation.invalid")
            asyncio.run(request())
        else:
            with httpx2.Client(trust_env=False) as client:
                client.get("https://isolation.invalid")


def test_mock_transport_is_still_available():
    seen = []
    def respond(request):
        seen.append(request.url.path)
        return httpx2.Response(200, json={"synthetic": True})
    with httpx2.Client(transport=httpx2.MockTransport(respond)) as client:
        assert client.get("https://isolation.invalid/fake").json() == {"synthetic": True}
    assert seen == ["/fake"]


def test_script_native_and_connection_helpers_fail_before_dispatch(monkeypatch):
    # Removing an outer guard must fail this test without launching or connecting.
    def dispatch_tripwire(*args, **kwargs):
        pytest.fail("native/connection dispatch tripwire reached")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", dispatch_tripwire)
    monkeypatch.setattr(gaze_client, "connect", dispatch_tripwire)
    for operation in (lambda: rehearse.activate_app("Synthetic app"),
                      lambda: rehearse.prepare_app("Synthetic app"),
                      lambda: GazeClient(1, "synthetic-token").connect()):
        with pytest.raises(AssertionError, match="inject fake"):
            asyncio.run(operation())
    with pytest.raises(AssertionError, match="never start the real agent"):
        rehearse.target_server("real", 0)
    with pytest.raises(AssertionError, match="fake OpenAI client"):
        llm.AsyncOpenAI(api_key="synthetic-key")


def test_cli_helper_uses_in_memory_transport():
    sent = []
    class Socket:
        async def send(self, frame):
            sent.append(frame)
    client = GazeClient(1, "synthetic-token")
    client.ws = Socket()
    asyncio.run(fake_overlay.command(client, {}, "stop"))
    assert len(sent) == 1


def test_child_installs_guards_and_strips_parent_credentials(monkeypatch, isolated_python):
    # Reintroduce synthetic parent values: the helper must not copy os.environ.
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-parent-key")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "synthetic-parent-key")
    monkeypatch.setenv("P01_PARENT_ONLY", "must-not-inherit")
    monkeypatch.setattr(profile, "load_profile", lambda: pytest.fail("parent patch used"))
    result = isolated_python('''
import asyncio
import os
from pathlib import Path
import pytest
from gaze_agent import llm, profile, tasklog
import rehearse

def dispatch_tripwire(*args, **kwargs):
    pytest.fail('native dispatch tripwire reached')
asyncio.create_subprocess_exec = dispatch_tripwire
assert 'OPENAI_API_KEY' not in os.environ
assert 'AZURE_OPENAI_API_KEY' not in os.environ
assert 'P01_PARENT_ONLY' not in os.environ
root = Path.cwd()
original_load = profile.ProfileStore._load
original_prune = tasklog.TaskLog.prune
def checked_load(store, *args):
    assert store.directory.is_relative_to(root), 'storage read tripwire'
    return original_load(store, *args)
def checked_prune(log):
    assert log.path.is_relative_to(root), 'storage read tripwire'
    return original_prune(log)
profile.ProfileStore._load = checked_load
tasklog.TaskLog.prune = checked_prune
assert profile.load_profile() == profile.DEFAULT_PROFILE
assert tasklog.TaskLog().path.is_relative_to(root)
with pytest.raises(AssertionError, match='private user storage'):
    profile.ProfileStore(profile.DATA_DIR / 'nested')
with pytest.raises(AssertionError, match='fake OpenAI client'):
    llm.AsyncOpenAI(api_key='synthetic-key')
with pytest.raises(AssertionError, match='inject fake'):
    asyncio.run(rehearse.prepare_app('Synthetic app'))
print('CHILD ISOLATION PASS')
''')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "CHILD ISOLATION PASS"
