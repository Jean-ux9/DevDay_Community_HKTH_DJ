"""Real recipient reader + loop + policy, all AX/desktop/storage/API inputs fake."""
import asyncio
import copy
import uuid

import pytest

from gaze_agent.contracts import ToolCall
from gaze_agent.loop import TaskFailure, TaskLoop
from gaze_agent.tasklog import TaskLog
from tests.runtime.support import FakeDesktop, look, plan
from tests.runtime.test_demo_config import FAKE_PERSONA
from tests.runtime.test_recipient_evidence import install_native


@pytest.mark.parametrize("tool", ["click_element", "press_keys", "type_text"])
@pytest.mark.parametrize("case", ["approved", "unapproved", "alias", "group", "changed_approved", "changed_unapproved",
    "changed_group", "failed_recheck", "cancel", "stop", "profile_expansion", "allowlist_mutation"])
def test_recipient_enforcement_and_revalidation(tmp_path, monkeypatch, tool, case):
    async def run():
        state = install_native(monkeypatch)
        desktop, events = FakeDesktop(), []
        approved = copy.deepcopy(FAKE_PERSONA["contacts"])
        persona = copy.deepcopy(FAKE_PERSONA)
        if case in {"unapproved", "profile_expansion"}:
            state.nodes["to"]["AXValue"] = "outside@example.invalid"
        if case == "profile_expansion":
            persona["contacts"]["Outside"] = ["outside@example.invalid"]
        if case == "alias":
            state.nodes["to"]["AXValue"] = "Mom"
        if case == "group":
            state.nodes["cc"]["AXValue"] = "+1 555 0142"
        async def emit(kind, payload, **kwargs):
            events.append((kind, payload))
            if kind == "confirm_request":
                if case == "changed_approved":
                    state.nodes["to"]["AXValue"] = "+1 555 0142"
                elif case in {"changed_unapproved", "allowlist_mutation"}:
                    state.nodes["to"]["AXValue"] = "outside@example.invalid"
                    if case == "allowlist_mutation":
                        approved["Outside"] = ["outside@example.invalid"]
                elif case in {"changed_group", "cancel"}:
                    state.nodes["bcc"]["AXValue"] = "+1 555 0142"
                elif case == "failed_recheck":
                    del state.nodes["to"]["AXValue"]
                task.respond("confirm_response", task.task_id, kwargs["message_id"], {"confirmed": case != "cancel"})
                if case == "stop":
                    task.cancel()
        task = TaskLoop(task_id=str(uuid.uuid4()), plan=plan(), profile=persona, emit=emit,
            desktop=desktop, get_screen=lambda: copy.deepcopy(state.snapshot), look_at_screen=look,
            log=TaskLog(tmp_path), demo=True, demo_contacts=approved)
        task.snapshot = state.snapshot
        task._started = task.clock()
        args = {"click_element": {"id": "e1", "snapshot_id": state.snapshot.snapshot_id},
                "press_keys": {"keys": ["cmd", "enter"]},
                "type_text": {"text": "Synthetic draft", "submit": True}}[tool]
        call = ToolCall("send", tool, args)
        if case == "stop":
            with pytest.raises(asyncio.CancelledError):
                await task.execute(call)
        elif case in {"approved", "cancel"}:
            result = await task.execute(call)
            assert result["ok"] is (case == "approved")
            assert len(desktop.calls) == (case == "approved")
            if case == "cancel":
                assert task.user_cancelled
                assert not (await task.execute(ToolCall("later", "open_app", {"name": "Music"})))["ok"]
        else:
            with pytest.raises(TaskFailure, match="recipient|Recipient") as error:
                await task.execute(call)
            assert "outside@example.invalid" not in str(error.value)
        if case != "approved":
            assert desktop.calls == []
        confirms = [p for k, p in events if k == "confirm_request"]
        if case in {"unapproved", "alias", "group", "profile_expansion"}:
            assert not confirms
        elif confirms:
            assert "Approved recipient: alex.rehearsal@example.invalid" in confirms[0]["details"]
        assert "Outside" not in task.demo_contacts
    asyncio.run(run())
