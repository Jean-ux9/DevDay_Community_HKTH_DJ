"""Optional standard imsg send; no contacts/history, private APIs or SMS fallback.

Reviewed upstream 41de9c8b58ffbff2beff9ce3992192d5c11a753e. The public --db
override prevents access to the default chat.db; acknowledgement is not delivery.
H1 must check per-device capability/setup, and approve the exact immutable action.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from .contracts import ActionRequest, ActionResult, PreparedAction
from .scripts.send_support import SendProcess, UncertainSend, destination, text


class MessagesProvider:
    operation = "messages.send"
    provider = "imsg.imessage"

    def __init__(self, *, transport=None):
        self._transport = transport if transport is not None else SendProcess()

    def _payload(self, arguments):
        if set(arguments) != {"recipient", "body"}:
            raise ValueError("invalid_arguments")
        return {"recipient": destination(arguments["recipient"]),
                "body": text(arguments["body"], nonempty=True)}

    async def prepare(self, request: ActionRequest) -> PreparedAction:
        if request.operation != self.operation:
            raise ValueError("unsupported_operation")
        return PreparedAction(request.request_id, self.operation, self.provider,
                              self._payload(request.arguments))

    async def execute(self, action: PreparedAction) -> ActionResult:
        await asyncio.sleep(0)
        try:
            if action.operation != self.operation or action.provider != self.provider:
                raise ValueError("invalid_action")
            payload = self._payload(action.payload)
        except (ValueError, KeyError, TypeError):
            return ActionResult("failed", "invalid_action")
        # --option=value keeps leading '-' body text as data. No shell involved.
        # An impossible child of the /dev/null device makes MessageStore creation
        # fail (plain /dev/null can look like an empty SQLite database instead).
        argv = ("imsg", "send", "--db=/dev/null/gaze-no-history", "--service=imessage",
                "--no-sms-fallback", "--json", "--to=" + payload["recipient"],
                "--text=" + payload["body"])
        try:
            reply = await self._transport.run(argv)
        except FileNotFoundError:
            return ActionResult("failed", "missing_tool")
        except PermissionError:
            return ActionResult("failed", "tool_permission_denied")
        except UncertainSend as error:
            code = str(error)
            return ActionResult("unknown", code if code in {
                "timeout_unknown", "cancelled_unknown", "output_unknown",
                "transport_unknown"} else "transport_unknown")
        except Exception:
            return ActionResult("unknown", "transport_unknown")
        # No raw output/error text or message IDs escape into ActionResult.
        if reply.returncode == 0:
            try:
                result = json.loads(reply.stdout)
                if result == {"status": "sent"}:
                    return ActionResult("completed", "provider_acknowledged")
            except (ValueError, UnicodeError):
                pass
        # Nonzero CLI exits do not establish a pre-dispatch phase. No retries.
        return ActionResult("unknown", "submission_unknown")


class MessagesScriptProvider:
    """Apple Messages scripting, pinned to the one enabled iMessage account.

    The script refuses before sending when there is no such account, or more than one,
    so the frozen payload's ``account`` ("iMessage") is the only account it can use.
    """

    operation = "messages.send"
    provider = "apple_messages"
    account = "iMessage"

    def __init__(self, *, transport=None):
        self._transport = transport if transport is not None else SendProcess()

    def _payload(self, arguments):
        if set(arguments) - {"account"} != {"recipient", "body"}:
            raise ValueError("invalid_arguments")
        return {"recipient": destination(arguments["recipient"]),
                "body": text(arguments["body"], nonempty=True), "account": self.account}

    async def prepare(self, request: ActionRequest) -> PreparedAction:
        if request.operation != self.operation or "account" in request.arguments:
            raise ValueError("unsupported_operation")
        return PreparedAction(request.request_id, self.operation, self.provider,
                              self._payload(request.arguments))

    async def execute(self, action: PreparedAction) -> ActionResult:
        await asyncio.sleep(0)
        try:
            if (action.operation != self.operation or action.provider != self.provider
                    or set(action.payload) != {"recipient", "body", "account"}
                    or action.payload["account"] != self.account):
                raise ValueError("invalid_action")
            payload = self._payload(action.payload)
        except (ValueError, KeyError, TypeError):
            return ActionResult("failed", "invalid_action")
        script = str(Path(__file__).with_name("scripts") / "messages_send.applescript")
        argv = ("/usr/bin/osascript", script, payload["recipient"], payload["body"])
        try:
            reply = await self._transport.run(argv)
        except FileNotFoundError:
            return ActionResult("failed", "missing_tool")
        except PermissionError:
            return ActionResult("failed", "tool_permission_denied")
        except UncertainSend as error:
            code = str(error)
            return ActionResult("unknown", code if code in {
                "timeout_unknown", "cancelled_unknown", "output_unknown",
                "transport_unknown"} else "transport_unknown")
        except Exception:
            return ActionResult("unknown", "transport_unknown")
        # Only the static script's markers prove non-submission. No retries.
        if reply.returncode == 0:
            if reply.stdout == b"GAZE_MSG_ACK\n":
                return ActionResult("completed", "provider_acknowledged")
            failures = {b"GAZE_MSG_NO_ACCOUNT\n": "no_imessage_account",
                        b"GAZE_MSG_PERMISSION\n": "automation_permission_denied",
                        b"GAZE_MSG_PRE_SEND_FAILED\n": "prepare_failed"}
            if reply.stdout in failures:
                return ActionResult("failed", failures[reply.stdout])
        return ActionResult("unknown", "submission_unknown")
