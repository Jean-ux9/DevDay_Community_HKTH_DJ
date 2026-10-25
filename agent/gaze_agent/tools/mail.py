"""Apple Mail scripting provider. H1 alone resolves recipients and approves sends."""
from __future__ import annotations

import asyncio
from pathlib import Path

from .contracts import ActionRequest, ActionResult, PreparedAction
from .scripts.send_support import SendProcess, UncertainSend, mailbox, text


class MailProvider:
    operation = "mail.send"
    provider = "apple_mail"

    def __init__(self, *, sender: str, transport=None):
        # Trusted runtime setup, never a model argument or profile read here.
        self._sender = mailbox(sender)
        self._transport = transport if transport is not None else SendProcess()

    def _payload(self, arguments):
        if set(arguments) != {"recipient", "subject", "body"}:
            raise ValueError("invalid_arguments")
        return {
            "recipient": mailbox(arguments["recipient"]),
            "subject": text(arguments["subject"], limit=4096, single_line=True),
            "body": text(arguments["body"]),
            "sender": self._sender,
        }

    async def prepare(self, request: ActionRequest) -> PreparedAction:
        if request.operation != self.operation:
            raise ValueError("unsupported_operation")
        return PreparedAction(request.request_id, self.operation, self.provider,
                              self._payload(request.arguments))

    async def execute(self, action: PreparedAction) -> ActionResult:
        await asyncio.sleep(0)
        try:
            if (action.operation != self.operation or action.provider != self.provider
                    or set(action.payload) != {"recipient", "subject", "body", "sender"}
                    or action.payload["sender"] != self._sender):
                raise ValueError("invalid_action")
            payload = self._payload({k: action.payload[k] for k in ("recipient", "subject", "body")})
        except (ValueError, KeyError, TypeError):
            return ActionResult("failed", "invalid_action")
        script = str(Path(__file__).with_name("scripts") / "mail_send.applescript")
        argv = ("/usr/bin/osascript", script, payload["recipient"],
                payload["subject"], payload["body"], payload["sender"])
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
        # Only this static script's allowlisted phase markers prove non-submission.
        if reply.returncode == 0:
            if reply.stdout == b"GAZE_MAIL_ACK\n":
                return ActionResult("completed", "provider_acknowledged")
            failures = {
                b"GAZE_MAIL_NO_ACCOUNT\n": "missing_account",
                b"GAZE_MAIL_PERMISSION\n": "automation_permission_denied",
                b"GAZE_MAIL_PRE_SEND_FAILED\n": "prepare_failed",
            }
            if reply.stdout in failures:
                return ActionResult("failed", failures[reply.stdout])
        return ActionResult("unknown", "submission_unknown")
