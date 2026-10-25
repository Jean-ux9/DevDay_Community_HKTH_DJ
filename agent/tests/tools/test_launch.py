"""Fake-only launcher checks; never spawn an actual process.

Until H1 is integrated, H2_TEST_CONTRACTS may name an exact extracted copy of
H1's published contracts.py. No substitute contract implementation lives here.
"""
import asyncio
import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

try:
    from gaze_agent.tools.contracts import ActionRequest, PreparedAction
except ModuleNotFoundError as error:
    if error.name != "gaze_agent.tools.contracts" or not os.environ.get("H2_TEST_CONTRACTS"):
        raise
    spec = importlib.util.spec_from_file_location(
        "gaze_agent.tools.contracts", os.environ["H2_TEST_CONTRACTS"])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    from gaze_agent.tools.contracts import ActionRequest, PreparedAction

from gaze_agent.tools import launch
from gaze_agent.tools.launch import LaunchProvider, PROVIDER


class FakeProcess:
    def __init__(self, code=0, *, hanging=False, ignore_terminate=False):
        self.code = code
        self.ignore_terminate = ignore_terminate
        self.exited = asyncio.Event()
        self.wait_started = asyncio.Event()
        self.reaped = False
        self.terminated = 0
        self.killed = 0
        if not hanging:
            self.exited.set()

    async def wait(self):
        self.wait_started.set()
        await self.exited.wait()
        self.reaped = True
        return self.code

    def terminate(self):
        self.terminated += 1
        if not self.ignore_terminate:
            self.exited.set()

    def kill(self):
        self.killed += 1
        self.exited.set()


class FakeTransport:
    def __init__(self, process=None, error=None):
        self.process = process
        self.error = error
        self.calls = []

    async def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error:
            raise self.error
        return self.process


@pytest.fixture(autouse=True)
def forbid_real_processes(monkeypatch):
    forbidden = Mock(side_effect=AssertionError("Real subprocesses forbidden"))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", forbidden)
    monkeypatch.setattr("subprocess.Popen", forbidden)


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.mark.parametrize("operation,arguments,argv", [
    ("app.open", {"name": "sAfArI"}, ("/usr/bin/open", "-b", "com.apple.Safari")),
    ("app.open", {"name": "TextEdit"}, ("/usr/bin/open", "-b", "com.apple.TextEdit")),
    ("web.open", {"url": "https://example.com/a?q=one%20two#part"},
     ("/usr/bin/open", "https://example.com/a?q=one%20two#part")),
    ("web.open", {"url": "http://localhost:8080/"},
     ("/usr/bin/open", "http://localhost:8080/")),
    ("web.open", {"url": "https://[::1]:443/"},
     ("/usr/bin/open", "https://[::1]:443/")),
    ("web.open", {"url": "https://example.com/?q=$(fake);&x=`fake`"},
     ("/usr/bin/open", "https://example.com/?q=$(fake);&x=`fake`")),
])
def test_valid_arguments_and_honest_result(operation, arguments, argv):
    async def scenario():
        process = FakeProcess()
        transport = FakeTransport(process)
        provider = LaunchProvider(process_transport=transport)
        action = await provider.prepare(ActionRequest("r1", operation, arguments))
        assert transport.calls == []
        assert action.request_id == "r1" and action.provider == PROVIDER
        assert arguments[next(iter(arguments))] not in repr(action)
        result = await provider.execute(action)
        assert (result.status, result.code, result.receipt) == ("completed", "launcher_accepted", None)
        assert transport.calls == [(argv, dict(stdin=-3, stdout=-3, stderr=-3))]
        assert process.reaped and not process.terminated
    run(scenario())


@pytest.mark.parametrize("url", [
    "file:///tmp/test", "javascript:alert(1)", "mailto:fake@example.com",
    "custom://example.com", "ftp://example.com", "--args", "-aSafari",
    "//example.com", "https:example.com", "https:///example.com", "https://",
    "https://user:password@example.com", "https://user@example.com",
    "https://user%40example.com", "https://example.com@evil.test",
    " https://example.com", "https://example.com/\n--args", "https://example.com/\x00",
    "https://example.com/\x7f", "https://example.com/\u202e", "https://example.com/a b",
    "https://example.com/%00", "https://example.com/%0a", "https://example.com/%7f",
    "https://example.com/\\evil", "https://example.com/%5cevil",
    "https://example.com/%zz", "https://example.com/%", "https://example.com:abc/",
    "https://example.com:65536/", "https://example.com:0/", "https://example.com:/",
    "https://[::1", "https://[::1]extra/", "https://[::1]:/",
    "https://-bad.test", "https://bad-.test", "https://bad..test", "https://999.1.1.1",
    "https://example.com/" + "a" * 4096, "", None, 12, [], {},
])
def test_reject_invalid_urls_without_dispatch(url):
    transport = FakeTransport()
    provider = LaunchProvider(process_transport=transport)
    with pytest.raises(ValueError, match="^invalid_url$"):
        run(provider.prepare(ActionRequest("r1", "web.open", {"url": url})))
    assert transport.calls == []


@pytest.mark.parametrize("operation,arguments", [
    ("app.open", {"name": "Terminal"}), ("app.open", {"name": "/Applications/Safari.app"}),
    ("app.open", {"name": "-a Safari"}), ("app.open", {"name": "Safari;fake"}),
    ("app.open", {"name": "Safari\n"}), ("app.open", {"name": None}),
    ("app.open", {"name": []}), ("app.open", {}),
    ("app.open", {"name": "Safari", "args": "--fake"}),
    ("web.open", {"url": "https://example.com", "provider": "fake"}),
    ("web.open", {}), ("shell", {"name": "Safari"}),
])
def test_reject_unsupported_requests(operation, arguments):
    transport = FakeTransport()
    with pytest.raises(ValueError):
        run(LaunchProvider(process_transport=transport).prepare(
            ActionRequest("r1", operation, arguments)))
    assert transport.calls == []


def test_import_construction_prepare_have_no_side_effects(monkeypatch):
    # Compile first; execute the module with file/process/config access forbidden.
    code = compile(Path(launch.__file__).read_text(), launch.__file__, "exec")
    forbidden = Mock(side_effect=AssertionError("Preparation performed I/O"))
    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "exists", forbidden)
    monkeypatch.setattr(os, "getenv", forbidden)
    namespace = {"__name__": "gaze_agent.tools.launch", "__package__": "gaze_agent.tools"}
    exec(code, namespace)
    provider = namespace["LaunchProvider"]()
    action = run(provider.prepare(ActionRequest("r1", "app.open", {"name": "Mail"})))
    assert action.payload == {"name": "Mail"}
    forbidden.assert_not_called()


@pytest.mark.parametrize("provider,operation,payload", [
    ("other", "app.open", {"name": "Safari"}),
    (PROVIDER, "app.open", {"name": "safari"}),
    (PROVIDER, "app.open", {"name": "Terminal"}),
    (PROVIDER, "web.open", {"url": "file:///tmp/fake"}),
    (PROVIDER, "app.open", {"name": "Safari", "executable": "/fake"}),
])
def test_execute_revalidates_prepared_payload(provider, operation, payload):
    transport = FakeTransport()
    result = run(LaunchProvider(process_transport=transport).execute(
        PreparedAction("r1", operation, provider, payload)))
    assert (result.status, result.code) == ("failed", "invalid_prepared_action")
    assert transport.calls == []


@pytest.mark.parametrize("error,code,status", [
    (FileNotFoundError("PRIVATE fake account"), "launcher_unavailable", "failed"),
    (PermissionError("PRIVATE fake account"), "launcher_unavailable", "failed"),
    (RuntimeError("PRIVATE fake account"), "launcher_error", "unknown"),
])
def test_sanitized_transport_failure(error, code, status):
    async def scenario():
        provider = LaunchProvider(process_transport=FakeTransport(error=error))
        action = await provider.prepare(ActionRequest("r1", "web.open", {"url": "https://example.com"}))
        result = await provider.execute(action)
        assert (result.status, result.code) == (status, code)
        assert "PRIVATE" not in repr(result) and result.receipt is None
    run(scenario())


def test_nonzero_exit_is_sanitized():
    async def scenario():
        process = FakeProcess(code=1)
        provider = LaunchProvider(process_transport=FakeTransport(process))
        result = await provider.execute(await provider.prepare(
            ActionRequest("r1", "app.open", {"name": "Messages"})))
        assert (result.status, result.code) == ("failed", "launcher_rejected")
        assert process.reaped
    run(scenario())


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.parametrize("ignore_terminate", [False, True])
def test_timeout_or_cancel_terminates_kills_and_reaps(cancel, ignore_terminate):
    async def scenario():
        process = FakeProcess(hanging=True, ignore_terminate=ignore_terminate)
        provider = LaunchProvider(process_transport=FakeTransport(process),
                                  timeout=0.02, cleanup_timeout=0.01)
        action = await provider.prepare(ActionRequest("r1", "app.open", {"name": "Notes"}))
        task = asyncio.create_task(provider.execute(action))
        await process.wait_started.wait()
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            result = await task
            assert (result.status, result.code) == ("unknown", "launcher_timeout")
        assert process.terminated == 1
        assert process.killed == int(ignore_terminate)
        assert process.reaped
    run(scenario())


@pytest.mark.parametrize("late", [False, True])
def test_cancel_during_spawn_owns_eventual_child(late):
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        process = FakeProcess(hanging=True)
        async def transport(*args, **kwargs):
            started.set()
            await release.wait()
            return process
        provider = LaunchProvider(process_transport=transport, cleanup_timeout=0.01)
        action = await provider.prepare(ActionRequest("r1", "app.open", {"name": "Calendar"}))
        task = asyncio.create_task(provider.execute(action))
        await started.wait()
        task.cancel()
        if not late:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 0.2)
        release.set()
        await asyncio.wait_for(process.exited.wait(), 0.2)
        for _ in range(5):
            await asyncio.sleep(0)
        assert process.terminated == 1 and process.reaped
    run(scenario())


def test_repeated_cancellation_cannot_interrupt_cleanup():
    async def scenario():
        terminated = asyncio.Event()
        class SlowProcess(FakeProcess):
            def terminate(self):
                super().terminate()
                terminated.set()
        process = SlowProcess(hanging=True, ignore_terminate=True)
        provider = LaunchProvider(process_transport=FakeTransport(process), cleanup_timeout=0.01)
        action = await provider.prepare(ActionRequest("r1", "app.open", {"name": "Safari"}))
        task = asyncio.create_task(provider.execute(action))
        await process.wait_started.wait()
        task.cancel()
        await terminated.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert process.terminated == 1 and process.killed == 1 and process.reaped
    run(scenario())


def test_wait_and_cleanup_errors_never_expose_transport_diagnostics():
    async def scenario():
        class BrokenProcess(FakeProcess):
            async def wait(self):
                raise OSError("PRIVATE fake process diagnostic")
            def terminate(self):
                raise OSError("PRIVATE fake process diagnostic")
            def kill(self):
                raise OSError("PRIVATE fake process diagnostic")
        provider = LaunchProvider(process_transport=FakeTransport(BrokenProcess()))
        action = await provider.prepare(ActionRequest("r1", "app.open", {"name": "Safari"}))
        result = await provider.execute(action)
        assert (result.status, result.code, result.receipt) == ("unknown", "launcher_error", None)
        assert "PRIVATE" not in repr(result)
    run(scenario())


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), True, 11])
def test_timeouts_must_be_bounded(timeout):
    with pytest.raises(ValueError, match="invalid_launch_timeout"):
        LaunchProvider(timeout=timeout)
