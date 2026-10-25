"""Small explicit provider composition and runtime-owned request validation.

No provider discovery, configuration reads or transport calls occur on import.
The selected store supplies contacts/approvals to the loop, never to providers.
"""
from __future__ import annotations

from collections.abc import Mapping
from importlib import import_module
import os

from .contracts import ActionProvider, ActionRequest, PreparedAction

OPERATIONS = {
    "app_open": ("app.open", ("name",)),
    "web_open": ("web.open", ("url",)),
    "mail_send": ("mail.send", ("recipient_alias", "subject", "body")),
    "messages_send": ("messages.send", ("recipient_alias", "body")),
}
SEND = {"mail.send", "messages.send"}


class ActionSetupError(ValueError):
    """Only fixed, runtime-owned error messages cross this boundary."""


class ActionRegistry:
    def __init__(self, providers: Mapping[str, ActionProvider] | None = None, *,
                 accounts=None, external=False, unavailable=None):
        self.providers = dict(providers or {})
        self.accounts = dict(accounts or {})
        self.external = external
        self.unavailable = dict(unavailable or {})

    def ensure_dispatch_allowed(self):
        # Default transports are real OS processes. Preview and replay never
        # authorize them; injected doubles do not need a live launcher setting.
        if self.external and (os.getenv("GAZE_AGENT_MODE") != "live"
                              or os.getenv("REPLAY", "off") != "off"):
            raise ActionSetupError("Structured native dispatch requires live mode with replay off")

    def capabilities(self):
        return tuple(op for op in sorted(self.providers) if op in {v[0] for v in OPERATIONS.values()})

    def provider_for(self, operation):
        provider = self.providers.get(operation)
        if provider is None:
            raise ActionSetupError("Structured provider unavailable; setup required")
        return provider

    def resolve(self, request_id, tool, arguments, profile, approved):
        operation, fields = OPERATIONS[tool]
        if set(arguments) != set(fields) or any(not isinstance(arguments[k], str) for k in fields):
            raise ActionSetupError("Invalid structured action arguments")
        if any("\x00" in value for value in arguments.values()):
            raise ActionSetupError("Invalid structured action arguments")
        if any(len(value) > 20000 for value in arguments.values()):
            raise ActionSetupError("Structured action is too large")
        values = dict(arguments)
        if operation in SEND:
            alias = values.pop("recipient_alias")
            handles = profile.get("contacts", {}).get(alias, [])
            if (not isinstance(handles, (list, tuple)) or len(handles) != 1
                    or not isinstance(handles[0], str) or not handles[0]
                    or handles[0] not in approved.get(alias, ())):
                raise ActionSetupError("Send blocked: one approved recipient must be selected")
            values["recipient"] = handles[0]
            if not values["body"]:
                raise ActionSetupError("Send blocked: content is empty")
        return ActionRequest(request_id, operation, values)

    def validate_prepared(self, request, action):
        if (not isinstance(action, PreparedAction) or action.request_id != request.request_id
                or action.operation != request.operation or not isinstance(action.provider, str)
                or not action.provider):
            raise ActionSetupError("Provider preparation did not match the request")
        # An adapter may resolve app aliases/URL normalization. Send contents may
        # never be rewritten, expanded to groups or redirected by preparation.
        if request.operation in SEND:
            if action.provider == "imsg.imessage":
                raise ActionSetupError("Messages unavailable: provider cannot pin an outgoing account")
            account_field = "sender" if action.provider == "apple_mail" else "account"
            if (set(action.payload) != set(request.arguments) | {account_field}
                    or any(action.payload.get(k) != value for k, value in request.arguments.items())
                    or not isinstance(action.payload.get(account_field), str) or not action.payload[account_field]):
                raise ActionSetupError("Send preparation must preserve exact content and selected account")
            if (action.provider == "apple_mail"
                    and action.payload["sender"] != self.accounts.get("mail.send")):
                raise ActionSetupError("Mail sender does not match trusted setup")
            if action.provider == "apple_messages" and action.payload["account"] != "iMessage":
                raise ActionSetupError("Messages account does not match trusted setup")
        elif set(action.payload) != set(request.arguments):
            raise ActionSetupError("Launch preparation contains unexpected fields")


def default_registry(*, trusted_sender=None):
    """Compose the three sprint adapters when published; no fallback on Send.

    The sender comes only from the already selected private persona's existing
    address.email field. It is not the editable/model-supplied profile address.
    Standard imsg cannot pin its outgoing account; Messages uses Apple's scripting
    instead, pinned to the single enabled iMessage account (the script refuses
    otherwise, before sending). No native account discovery here.
    """
    providers, accounts = {}, {}
    unavailable = {}
    for module, name, operations, kwargs in (
        ("launch", "LaunchProvider", ("app.open", "web.open"), {}),
        ("mail", "MailProvider", ("mail.send",), {"sender": trusted_sender}),
        ("messages", "MessagesScriptProvider", ("messages.send",), {}),
    ):
        if module == "mail" and not trusted_sender:
            unavailable["mail.send"] = "trusted_sender_required"
            continue
        try:
            cls = getattr(import_module(f"gaze_agent.tools.{module}"), name)
            provider = cls(**kwargs)
        except (ImportError, AttributeError, TypeError, ValueError):
            unavailable.update({operation: "provider_setup_required" for operation in operations})
            continue
        providers.update({operation: provider for operation in operations})
        if module == "mail":
            accounts["mail.send"] = trusted_sender
    return ActionRegistry(providers, accounts=accounts, external=True, unavailable=unavailable)
