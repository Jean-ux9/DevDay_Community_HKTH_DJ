"""P04's exact provider consumed by real server/runtime with synthetic private data."""
import asyncio
import copy
import runpy
from contextlib import asynccontextmanager

import pytest

from gaze_agent import demo_config, server
from gaze_agent.loop import TaskLoop
from gaze_agent.profile import ProfileStore
from tests.runtime.support import (INFO, SNAPSHOT, FakeDesktop, Watcher, complete, connect,
                                   look, make_plans, select)
from tests.runtime.test_demo_config import FAKE_PERSONA, select_private
from tests.runtime.test_recipient_evidence import install_native

import rehearse


@pytest.fixture(autouse=True)
def synthetic_configuration_only(monkeypatch, tmp_path):
    monkeypatch.delenv(demo_config.SELECTOR_ENV, raising=False)
    monkeypatch.setattr(demo_config, "USER_DATA_DIR", tmp_path / "unused-user-data")


@asynccontextmanager
async def configured_server(monkeypatch, state):
    monkeypatch.setattr(server.planner, "make_plans", make_plans)
    sessions, desktops = [], []
    def desktop(profile):
        value = FakeDesktop(profile)
        desktops.append(value)
        return value
    def loop(**kwargs):
        return TaskLoop(**kwargs, complete=complete)
    def session(ws, **kwargs):
        value = server.Session(ws, **kwargs)
        sessions.append(value)
        return value
    app = server.AgentServer("test-token", session_factory=session,
        screen=lambda: copy.deepcopy(state.snapshot), info=lambda: INFO, look=look,
        watcher_factory=Watcher, desktop_factory=desktop, loop_factory=loop)
    async with app.listen(0) as listener:
        yield listener.sockets[0].getsockname()[1], sessions, desktops


@pytest.mark.parametrize("actual,expected", [("+1 555 0188", True), ("+1 555 0100", False), ("+1 555 0199", False)])
def test_private_approved_handles_are_used_by_server_and_real_loop(tmp_path, monkeypatch, actual, expected):
    persona = copy.deepcopy(FAKE_PERSONA)
    persona["contacts"]["Mom"] = ["+1 555 0188"]
    config = select_private(monkeypatch, tmp_path, persona=persona, approved_recipients=persona["contacts"])
    state = install_native(monkeypatch, SNAPSHOT, bundle=SNAPSHOT.bundle_id, handle=actual)
    async def run():
        async with configured_server(monkeypatch, state) as (port, sessions, desktops):
            async with await connect(port) as client:
                assert client.hello_ack["payload"]["demo_mode"]
                assert client.hello_ack["payload"]["profile"] == persona
                session = sessions[0]
                assert session.store.directory == config.data_dir
                assert session.log.path.parent == config.data_dir
                assert session.store.approved_contacts() == persona["contacts"]
                # A rejected profile update cannot add a destination or touch the store.
                before = (config.data_dir / "profile.json").read_bytes()
                request = await client.send("profile_update", {"patch": {"contacts": {"Outside": ["+1 555 0199"]}}})
                assert (await client.next("error", re=request["id"]))["payload"]["code"] == "bad_message"
                assert (config.data_dir / "profile.json").read_bytes() == before
                task_id = await select(client)
                if expected:
                    request = await client.next("confirm_request", task_id=task_id)
                    assert "Approved recipient: +1 555 0188" in request["payload"]["details"]
                    await client.send("confirm_response", {"task_id": task_id, "confirmed": True}, re=request["id"])
                result = await client.next("task_result", task_id=task_id)
                assert result["payload"]["ok"] is expected
                assert len(desktops[0].calls) == int(expected)
                assert not (tmp_path / "isolated-user-data").exists()
                assert not (tmp_path / "unused-user-data").exists()
    asyncio.run(run())


def test_server_pins_provider_and_shares_storage_between_connections(tmp_path, monkeypatch):
    first = select_private(monkeypatch, tmp_path)
    state = install_native(monkeypatch, SNAPSHOT, bundle=SNAPSHOT.bundle_id, handle="+1 555 0142")
    async def run():
        async with configured_server(monkeypatch, state) as (port, sessions, _):
            async with await connect(port):
                original = sessions[0].store
                original.update_profile({"favorites": {"playlist": "Synthetic update"}})
            # Invalid later selection must not be read by another connection.
            monkeypatch.setenv(demo_config.SELECTOR_ENV, str(tmp_path / "absent.json"))
            async with await connect(port) as client:
                assert sessions[-1].store is original
                assert client.hello_ack["payload"]["profile"]["favorites"]["playlist"] == "Synthetic update"
                assert original.directory == first.data_dir
                assert original.approved_contacts() == FAKE_PERSONA["contacts"]
    asyncio.run(run())


def test_default_server_uses_provider_factory_without_private_selector(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_MODE", "0")
    app = server.AgentServer("fake-token")
    store = app.options["store"]
    assert isinstance(store, ProfileStore) and not store.demo
    assert store.demo_config is None and store.directory == tmp_path / "isolated-user-data"
    assert store.approved_contacts() == {}


@pytest.mark.parametrize("mode", ["0", "1"])
def test_invalid_selector_exits_before_listening_and_sanitizes_error(monkeypatch, tmp_path, capsys, mode):
    monkeypatch.setenv("GAZE_TOKEN", "fake-token")
    monkeypatch.setenv("DEMO_MODE", mode)
    monkeypatch.setenv(demo_config.SELECTOR_ENV, str(tmp_path / "absent-private.json"))
    def no_listener(*_):
        raise AssertionError("Invalid configuration must not listen")
    monkeypatch.setattr(server.AgentServer, "listen", no_listener)
    assert server.main() == 2
    output = capsys.readouterr().out
    assert "Private demo config:" in output
    assert str(tmp_path) not in output and "absent-private" not in output


def test_shared_isolation_clears_inherited_private_selector_before_provider_read(monkeypatch, tmp_path):
    # Both test trees have a conftest.py; use the backend guard's exact path.
    install_test_isolation = runpy.run_path(
        str(demo_config.REPO_ROOT / "agent/tests/conftest.py"))["install_test_isolation"]
    monkeypatch.setenv(demo_config.SELECTOR_ENV, str(tmp_path / "never-read.json"))
    def read_tripwire(*_):
        pytest.fail("The shared guard must clear the selector before manifest reads")
    monkeypatch.setattr(demo_config, "load_manifest", read_tripwire)
    with pytest.MonkeyPatch.context() as guarded:
        install_test_isolation(guarded, tmp_path / "guard", tmp_path)
        # Even a demo-mode test must not inherit the caller's private selector.
        guarded.setenv("DEMO_MODE", "1")
        assert demo_config.selected() is None


@pytest.mark.parametrize("case", ["approved", "unapproved", "wrong_persona"])
def test_private_rehearsal_through_combined_server_and_recipient_guard(monkeypatch, tmp_path, case):
    from tests.runtime.test_demo_config import manifest_data
    config = select_private(monkeypatch, tmp_path)
    expected = config
    if case == "wrong_persona":
        persona = config.persona()
        persona["name"] = "Different Synthetic Persona"
        expected = demo_config.parse_manifest(manifest_data(tmp_path, persona=persona))
    handle = "+1 555 0199" if case == "unapproved" else "+1 555 0142"
    state = install_native(monkeypatch, SNAPSHOT, bundle=SNAPSHOT.bundle_id, handle=handle)
    async def decode(*args, **kwargs):
        return ["Tell Mom I'll be late"]
    monkeypatch.setattr(server.planner, "decode", decode)
    async def run():
        prepared, clients = [], []
        async def prepare(app):
            prepared.append(app)  # Native preparation is deliberately fake.
        async with configured_server(monkeypatch, state) as (port, sessions, desktops):
            async def connector():
                client = await connect(port)
                clients.append(client)
                return client
            if case == "approved":
                detail = await rehearse.run_demo(connector, "D1", prepare=prepare, config=expected)
                assert "1 Send gates" in detail
                assert desktops[0].calls == [("click_element", {"id": "e1", "snapshot_id": SNAPSHOT.snapshot_id})]
                confirmations = [m for m in clients[0].sent if m["type"] == "confirm_response"]
                assert len(confirmations) == 1 and confirmations[0]["payload"]["confirmed"]
            else:
                with pytest.raises(RuntimeError, match="exact approved|outside the approved contacts"):
                    await rehearse.run_demo(connector, "D1", prepare=prepare, config=expected)
                assert not any(d.calls for d in desktops)
                assert not any(m["type"] == "confirm_response" for m in clients[0].sent)
            if case == "wrong_persona":
                assert not prepared and not desktops
                assert [m["type"] for m in clients[0].sent] == ["hello"]
            else:
                assert prepared == ["Messages"]
            assert sessions[0].store.directory == config.data_dir
            assert sessions[0].store.approved_contacts() == config.approved_contacts()
    asyncio.run(run())
