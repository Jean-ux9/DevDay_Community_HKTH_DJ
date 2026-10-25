"""P08 consumer checks: synthetic manifests, in-memory clients, no native/API work."""
import asyncio
import copy
import json
import os
import subprocess
import sys
from collections import deque
from contextlib import asynccontextmanager

import pytest

import rehearse
from gaze_agent import demo_config


TARGET_SERVER = rehearse.target_server  # Test only with a fake subprocess below.


@pytest.fixture(autouse=True)
def synthetic_selection(monkeypatch, tmp_path):
    monkeypatch.delenv(demo_config.SELECTOR_ENV, raising=False)
    monkeypatch.setattr(demo_config, "USER_DATA_DIR", tmp_path / "unused-default-store")


def manifest(tmp_path, **changes):
    persona = copy.deepcopy(rehearse.DEMO_PROFILE)
    persona["name"] = "Riley Example"
    persona["contacts"] = {"Mom": ["+1 555 0142"], "Alex": ["alex@example.invalid"]}
    persona["favorites"]["artist"] = "The Placeholder Band"
    return {
        "format": demo_config.MANIFEST_FORMAT,
        "config_id": "p08-synthetic",
        "persona": persona,
        "approved_recipients": copy.deepcopy(persona["contacts"]),
        "data_dir": str(tmp_path / "private-data"),
        "cache_dir": str(tmp_path / "private-cache"),
    } | changes


def select_manifest(monkeypatch, tmp_path, **changes):
    data = manifest(tmp_path, **changes)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    path.chmod(0o600)
    monkeypatch.setenv(demo_config.SELECTOR_ENV, str(path))
    return demo_config.selected({demo_config.SELECTOR_ENV: str(path), "DEMO_MODE": "1"})


class PlanningClient:
    """Only the transport is fake; run_demo does the validation and selection."""
    def __init__(self, profile, *, demo_mode=True, permissions=None):
        self.hello_ack = {"payload": {
            "profile": copy.deepcopy(profile), "demo_mode": demo_mode,
            "permissions": permissions or {"accessibility": True, "screen_recording": True},
        }}
        self.sent, self.replies = [], deque()
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.closed = True

    async def send(self, kind, payload, **kwargs):
        request = {"id": str(len(self.sent)), "type": kind, "payload": payload}
        self.sent.append(request)
        if kind == "decode_request":
            self.replies.append({"type": "decode_result", "payload": {"sentences": ["Tell Mom I'll be late"]}})
        elif kind == "intent_submit":
            artist = self.hello_ack["payload"]["profile"]["favorites"]["artist"]
            self.replies.append({"type": "plans", "payload": {"items": [
                {"id": "p1", "kind": "task", "label": f"Find {artist} tickets"},
                {"id": "other", "kind": "other", "label": "Something else"},
            ]}})
        elif kind == "auto_refresh":
            self.replies.append({"type": "suggestions", "payload": {
                "app": "Mail", "window_key": "com.apple.mail|inbox",
                "items": [{"id": "reply", "kind": "task", "label": "Reply: sounds good"}],
            }})
        return request

    async def next(self, *args, **kwargs):
        return self.replies.popleft()


def connector(client):
    async def connect():
        return client
    return connect


def fake_steps(monkeypatch):
    calls = []
    async def prepare(app):
        calls.append(("prepare", app))
    async def selected(client, index, demo, **kwargs):
        calls.append(("select", index))
        return "synthetic task"
    monkeypatch.setattr(rehearse, "run_selected", selected)
    return calls, prepare


@pytest.mark.parametrize("name", rehearse.DEMOS)
def test_approved_changed_persona_reaches_preparation_and_selection(monkeypatch, tmp_path, name):
    config = select_manifest(monkeypatch, tmp_path)
    client = PlanningClient(config.persona())
    calls, prepare = fake_steps(monkeypatch)
    result = asyncio.run(rehearse.run_demo(connector(client), name, prepare=prepare, config=config))
    assert result == "synthetic task"
    assert calls == [("prepare", rehearse.DEMOS[name].app), ("select", 0)]
    assert client.closed
    assert not config.data_dir.exists() and not config.cache_dir.exists()


@pytest.mark.parametrize("mismatch", ["public persona", "unapproved handle", "missing contact", "style", "favorite", "demo off", "permissions"])
def test_wrong_handshake_fails_before_preparation_or_requests(monkeypatch, tmp_path, mismatch):
    config = select_manifest(monkeypatch, tmp_path)
    actual = config.persona()
    options = {}
    if mismatch == "public persona":
        actual = rehearse.DEMO_PROFILE
    elif mismatch == "unapproved handle":
        actual["contacts"]["Mom"] = ["+1 555 0199"]
    elif mismatch == "missing contact":
        del actual["contacts"]["Mom"]
    elif mismatch == "style":
        actual["style"]["tone"] = "formal"
    elif mismatch == "favorite":
        actual["favorites"]["artist"] = "Another Synthetic Band"
    elif mismatch == "demo off":
        options["demo_mode"] = False
    else:
        options["permissions"] = {"accessibility": True, "screen_recording": False}
    client = PlanningClient(actual, **options)
    calls, prepare = fake_steps(monkeypatch)
    with pytest.raises(RuntimeError):
        asyncio.run(rehearse.run_demo(connector(client), "D1", prepare=prepare, config=config))
    assert calls == [] and client.sent == [] and client.closed
    assert not config.data_dir.exists() and not config.cache_dir.exists()


def test_unset_selector_preserves_public_fixture_guard():
    rehearse.verify_demo(PlanningClient(rehearse.DEMO_PROFILE))
    changed = copy.deepcopy(rehearse.DEMO_PROFILE)
    changed["name"] = "Unapproved Synthetic Persona"
    with pytest.raises(RuntimeError, match="exact fixtures"):
        rehearse.verify_demo(PlanningClient(changed))


@pytest.mark.parametrize("bad", ["allowlist", "storage", "missing file"])
def test_bad_selection_fails_before_server_or_app_preparation(monkeypatch, tmp_path, bad):
    data = manifest(tmp_path)
    if bad == "allowlist":
        data["approved_recipients"]["Mom"] = ["+1 555 0199"]
    elif bad == "storage":
        data["cache_dir"] = str(rehearse.ROOT / "agent/replay/cache")
    path = tmp_path / "bad-manifest.json"
    if bad != "missing file":
        path.write_text(json.dumps(data), encoding="utf-8")
        path.chmod(0o600)
    monkeypatch.setenv(demo_config.SELECTOR_ENV, str(path))
    calls = []
    def forbidden_server(*args):
        calls.append("server")
        pytest.fail("Invalid config reached server startup")
    monkeypatch.setattr(rehearse, "target_server", forbidden_server)
    with pytest.raises(demo_config.DemoConfigError) as error:
        asyncio.run(rehearse.rehearse("real", 0))
    assert calls == []
    assert str(path) not in str(error.value) and "+1 555" not in str(error.value)
    assert not (tmp_path / "private-data").exists() and not (tmp_path / "private-cache").exists()


@pytest.mark.parametrize("target", ["real", "fake"])
def test_rehearse_passes_selected_config_only_to_real(monkeypatch, tmp_path, target):
    config = select_manifest(monkeypatch, tmp_path)
    # Fake mode must not attempt even to open an inherited, missing selector.
    if target == "fake":
        monkeypatch.setenv(demo_config.SELECTOR_ENV, str(tmp_path / "not-readable.json"))
    seen = []
    @asynccontextmanager
    async def server(*args):
        yield 12345, "synthetic-token"
    async def run_demo(connect, name, **kwargs):
        seen.append((name, kwargs))
        return "synthetic"
    monkeypatch.setattr(rehearse, "target_server", server)
    monkeypatch.setattr(rehearse, "run_demo", run_demo)
    monkeypatch.setattr(rehearse, "FAKE_EXTRA_FLOWS", ())
    assert asyncio.run(rehearse.rehearse(target, 0))
    assert [name for name, _ in seen] == list(rehearse.DEMOS)
    for _, kwargs in seen:
        expected = kwargs["config"]
        assert (expected.fingerprint if expected else None) == (config.fingerprint if target == "real" else None)
        assert kwargs["prepare"] == (rehearse.prepare_app if target == "real" else None)


@pytest.mark.parametrize("target,selector", [("fake", "synthetic-path"), ("real", "synthetic-path"), ("real", None)])
def test_child_selector_and_modes_with_fake_process(monkeypatch, tmp_path, target, selector):
    synthetic_env = {"REPLAY": "replay"}
    if selector is not None:
        synthetic_env[demo_config.SELECTOR_ENV] = selector
    monkeypatch.setattr(rehearse.os, "environ", synthetic_env)
    monkeypatch.setattr(rehearse, "ROOT", tmp_path)  # Never inspect this checkout's .env.
    captured = {}
    class Process:
        returncode = None
        def terminate(self):
            captured["terminated"] = True
            self.returncode = 0
        async def wait(self):
            return self.returncode
    async def launch(*command, **kwargs):
        captured.update(command=command, **kwargs)
        return Process()
    async def listening(proc, port):
        captured["port"] = port
    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    monkeypatch.setattr(rehearse, "wait_until_listening", listening)
    monkeypatch.setattr(rehearse.shutil, "which", lambda _: "/synthetic/uv")
    async def run():
        async with TARGET_SERVER(target, 0) as (port, token):
            assert 0 < port < 65536 and len(token) == 64
    asyncio.run(run())
    env = captured["env"]
    assert env["DEMO_MODE"] == "1" and env["REPLAY"] == "replay" and env["GAZE_AUTO_AMBIENT"] == "0"
    assert env["GAZE_PORT"] == str(captured["port"]) and captured["terminated"]
    if target == "fake":
        assert demo_config.SELECTOR_ENV not in env
        assert captured["command"][1] == str(rehearse.FAKE_AGENT)
    else:
        # An explicit empty value prevents uv --env-file from selecting a private
        # config invisible to the parent validator. Export the selector in shell.
        assert env[demo_config.SELECTOR_ENV] == (selector or "")


@pytest.mark.parametrize("failure", ["startup", "cancellation", "slow exit"])
def test_child_cleanup_with_fake_process(monkeypatch, failure):
    calls = []
    class Process:
        returncode = None
        def terminate(self):
            calls.append("terminate")
            if failure != "slow exit":
                self.returncode = 0
        def kill(self):
            calls.append("kill")
            self.returncode = 0
        async def wait(self):
            if self.returncode is None:
                raise TimeoutError
            return self.returncode
    async def launch(*args, **kwargs):
        return Process()
    async def listening(*args):
        if failure == "startup":
            raise TimeoutError("Synthetic startup timeout")
    monkeypatch.setattr(rehearse.os, "environ", {})
    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    monkeypatch.setattr(rehearse, "wait_until_listening", listening)
    async def run():
        async with TARGET_SERVER("fake", 0):
            if failure == "cancellation":
                raise asyncio.CancelledError
    if failure == "slow exit":
        asyncio.run(run())
        assert calls == ["terminate", "kill"]
    else:
        with pytest.raises(TimeoutError if failure == "startup" else asyncio.CancelledError):
            asyncio.run(run())
        assert calls == ["terminate"]


def test_configuration_import_and_validation_need_only_harness_dependencies(tmp_path):
    data = manifest(tmp_path)
    source = r'''
import importlib.abc
import json
from pathlib import Path
import sys

root, temporary, data = Path(sys.argv[1]), Path(sys.argv[2]), json.loads(sys.argv[3])
class LimitedEnvironment(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'AppKit', 'Quartz', 'ApplicationServices', 'Vision',
                                     'pyautogui', 'openai', 'dotenv', 'pydantic'}:
            raise AssertionError('non-harness import: ' + fullname)
        if fullname.startswith('gaze_agent.') and fullname != 'gaze_agent.demo_config':
            raise AssertionError('backend import: ' + fullname)
sys.meta_path.insert(0, LimitedEnvironment())
def audit(event, args):
    if event == 'open':
        path = args[0]
        if isinstance(path, (str, bytes)):
            path = Path(path).absolute()
            assert path.is_relative_to(root) or path.is_relative_to(Path(sys.base_prefix)) or path.is_relative_to(Path(sys.prefix)), 'unexpected file read'
            assert path.name != '.env' and path.name not in {'profile.json', 'settings.json'}
    assert event not in {'subprocess.Popen', 'socket.connect', 'socket.bind'}, 'unexpected dispatch'
sys.addaudithook(audit)
sys.path.insert(0, str(root / 'scripts'))
import rehearse
rehearse.demo_config.USER_DATA_DIR = temporary / 'unused-default-store'
config = rehearse.demo_config.parse_manifest(data)
assert config.persona() == data['persona']
assert not config.data_dir.exists() and not config.cache_dir.exists()
assert 'OPENAI_API_KEY' not in __import__('os').environ
print('HARNESS CONFIG PASS')
'''
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", source, str(rehearse.ROOT), str(tmp_path), json.dumps(data)],
        cwd=tmp_path, env={"PATH": os.defpath, "PYTHON_DOTENV_DISABLED": "1", "UV_NO_ENV_FILE": "1"},
        capture_output=True, text=True, timeout=20, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "HARNESS CONFIG PASS"
