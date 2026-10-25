"""SIGTERM ends the agent like Ctrl+C: tasks stop and held keys are released (fakes; no real signal)."""
import asyncio
import signal
import socket
import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from gaze_agent import server
from gaze_agent.loop import TaskLoop
from gaze_agent.profile import ProfileStore
from gaze_agent.screen import ax
from tests.runtime.support import (INFO, SNAPSHOT, FakeDesktop, Watcher, complete, connect, eventually, gate,
                                   look, make_plans, profile, select)


def test_sigterm_closes_sessions_stops_the_task_and_releases_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(server.planner, "make_plans", make_plans)
    store = ProfileStore(tmp_path)
    store.update_profile(profile())
    desktops, sessions = [], []

    def desktop_factory(_profile):
        desktop = FakeDesktop()
        desktop.slow = True
        desktops.append(desktop)
        return desktop

    def session_factory(ws, **kwargs):
        sessions.append(server.Session(ws, **kwargs))
        return sessions[-1]

    agent = server.AgentServer("test-token", session_factory=session_factory, store=store,
        screen=lambda: SNAPSHOT, info=lambda: INFO, look=look, desktop_factory=desktop_factory,
        watcher_factory=Watcher, loop_factory=lambda **kw: TaskLoop(**kw, complete=complete, gate=gate))

    async def run():
        loop = asyncio.get_running_loop()
        handlers = {}
        monkeypatch.setattr(loop, "add_signal_handler", lambda sig, callback: handlers.setdefault(sig, callback))
        monkeypatch.setattr(loop, "remove_signal_handler", lambda sig: handlers.pop(sig, None) is not None)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        monkeypatch.setenv("GAZE_TOKEN", "test-token")
        monkeypatch.setenv("GAZE_PORT", str(port))
        main = asyncio.create_task(server.run_server(agent))
        await eventually(lambda: signal.SIGTERM in handlers)
        assert signal.SIGTERM in handlers
        client = await connect(port)
        await select(client, "play focus")  # open_app: a slow tool, no confirm
        await eventually(lambda: desktops and desktops[0].started.is_set())
        handlers[signal.SIGTERM]()  # what the OS signal would call
        try:
            await asyncio.wait_for(main, 5)
        except asyncio.CancelledError:
            pass
        assert desktops[0].released and sessions[0].active is None and sessions[0].closed
        assert signal.SIGTERM not in handlers
        await client.close()
    asyncio.run(run())


@pytest.mark.parametrize("bind_failure", [False, True])
def test_server_dispatches_worker_focus_on_main_thread_and_cleans_up(monkeypatch, bind_failure):
    """No Cocoa import: a fake PID reader exercises actual loop/thread dispatch."""
    calls = []
    def pid():
        calls.append(threading.get_ident())
        assert threading.current_thread() is threading.main_thread()
        return 42
    monkeypatch.setattr(ax, "_cocoa_front_pid", pid)
    monkeypatch.setenv("GAZE_PORT", "0")

    async def run():
        entered = asyncio.Event()
        class Listener:
            @asynccontextmanager
            async def listen(self, port):
                entered.set()
                if bind_failure:
                    raise OSError("Synthetic listener failure")
                yield SimpleNamespace(sockets=[SimpleNamespace(getsockname=lambda: ("127.0.0.1", 0))])
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "add_signal_handler", lambda *args: None)
        monkeypatch.setattr(loop, "remove_signal_handler", lambda *args: None)
        main = asyncio.create_task(server.run_server(Listener()))
        await asyncio.wait_for(entered.wait(), 2)
        if bind_failure:
            with pytest.raises(OSError, match="Synthetic listener failure"):
                await main
        else:
            assert await asyncio.to_thread(ax._fresh_foreground_pid) == 42
            main.cancel()
            with pytest.raises(asyncio.CancelledError):
                await main
        before = len(calls)
        with pytest.raises(RuntimeError):
            await asyncio.to_thread(ax._fresh_foreground_pid)
        assert len(calls) == before
    asyncio.run(run())
    assert len(calls) == (0 if bind_failure else 1)
