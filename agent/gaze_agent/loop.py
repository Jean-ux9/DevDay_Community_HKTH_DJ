"""Bounded, cancellable tool loop behind the frozen B/C interfaces (spec §8)."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
import time
from dataclasses import dataclass, replace
from typing import Callable

from gaze_agent import llm, safety
from gaze_agent.contracts import ProposedAction
from gaze_agent.profile import profile_summary
from gaze_agent.protocol import ChoiceOption, Plan
from gaze_agent.screen import ax, recipients
from gaze_agent.tools.contracts import ActionResult
from gaze_agent.tools.registry import ActionRegistry, ActionSetupError, OPERATIONS, SEND


def _tool(name, properties, required):
    # Descriptions/instructions belong to task_system.md, not inline prompt text.
    return {"type": "function", "name": name, "strict": False,
            "parameters": {"type": "object", "properties": properties,
                           "required": required, "additionalProperties": False}}


S = {"type": "string"}
B = {"type": "boolean"}
CONFIRM = {"requires_confirmation": B, "confirmation_reason": S}
TOOLS = [
    _tool("click_element", {"id": S, "snapshot_id": S, **CONFIRM}, ["id", "snapshot_id"]),
    _tool("type_text", {"text": S, "id": S, "snapshot_id": S, "submit": B, **CONFIRM}, ["text"]),
    _tool("press_keys", {"keys": {"type": "array", "items": S, "minItems": 1}, **CONFIRM}, ["keys"]),
    _tool("open_app", {"name": S}, ["name"]),
    _tool("open_url", {"url": S, **CONFIRM}, ["url"]),
    _tool("look_at_screen", {"question": S}, ["question"]),
    _tool("native_screen", {}, []),
    _tool("ask_user", {"question": S, "options": {"type": "array", "minItems": 2, "maxItems": 4,
          "items": {"type": "object", "properties": {"id": S, "label": S, "detail": S},
                    "required": ["id", "label"], "additionalProperties": False}}}, ["question", "options"]),
    _tool("finish", {"ok": B, "summary": S}, ["ok", "summary"]),
    _tool("action_capabilities", {}, []),
]
TOOLS += [_tool(name, {field: S for field in fields}, list(fields))
          for name, (_, fields) in OPERATIONS.items()]
TOOL_SCHEMAS = {tool["name"]: tool["parameters"] for tool in TOOLS}


def recovery_plans(*, screen: bool = True) -> list[Plan]:
    ids = [("retry", "Try again")]
    if screen:
        ids.append(("show_screen", "Show me the screen"))
    ids.append(("cancel", "Cancel"))
    return [Plan(id="recovery:" + key, label=label, kind="recovery", risky=False) for key, label in ids]


@dataclass
class Outcome:
    ok: bool
    summary: str
    recovery: list[Plan] | None = None


class TaskFailure(Exception):
    pass


class TaskLoop:
    def __init__(self, *, task_id, plan, profile, emit, desktop, get_screen, look_at_screen,
                 log, demo=False, demo_contacts=None, complete=None, gate=None,
                 max_steps=15, max_seconds=90, clock: Callable = time.monotonic,
                 action_registry=None, approval_source=None, action_claims=None, profile_source=None):
        self.task_id, self.plan, self.profile = task_id, plan, copy.deepcopy(profile)
        self.emit, self.desktop, self.get_screen = emit, desktop, get_screen
        self.look_at_screen, self.log = look_at_screen, log
        self.complete, self.gate = complete or llm.complete, gate or safety.gate
        self.demo, self.demo_contacts = demo, copy.deepcopy(demo_contacts or {})
        self.max_steps, self.max_seconds, self.clock = max_steps, max_seconds, clock
        self.step = 0
        self.alive = True
        self.pending = None
        self.snapshot = None
        self.history = []
        self.failures = {}
        self.user_cancelled = False
        self._timeout = None
        self._started = 0
        self._paused = 0
        self.action_registry = action_registry if action_registry is not None else ActionRegistry()
        self.structured_mode = action_registry is not None
        self.approval_source = approval_source
        self.profile_source = profile_source
        self.action_claims = action_claims if action_claims is not None else {}
        self.structured_outcome = None
        self.send_uncertain = False
        self._provider_task = None
        self._send_dispatched = False

    def cancel(self):
        self.alive = False
        if self._send_dispatched:
            self.structured_result("mail.send", ActionResult("unknown", "submission_uncertain"))
        self.desktop.cancel()
        if self._provider_task is not None:
            self._provider_task.cancel()
        if self.pending and not self.pending[2].done():
            self.pending[2].cancel()

    def ensure_alive(self):
        if not self.alive:
            raise asyncio.CancelledError

    async def status(self, state, message):
        self.ensure_alive()
        await self.emit("task_status", {"task_id": self.task_id, "state": state, "step": self.step,
                                        "max_steps": 15, "message": message})

    async def wait_user(self, kind, payload):
        self.ensure_alive()
        future = asyncio.get_running_loop().create_future()
        request_id = self.pending = None
        started = self.clock()
        remaining = self.max_seconds - (started - self._started - self._paused)
        if remaining <= 0:
            raise TaskFailure("Task time limit reached")
        if self._timeout:
            self._timeout.reschedule(None)
        await self.status("waiting_user", "Waiting for your choice" if kind == "choice_request" else "Waiting for confirmation")
        # Reserve an id before send; a response can arrive as soon as send yields.
        import uuid
        request_id = str(uuid.uuid4())
        self.pending = (kind, request_id, future, payload)
        try:
            await self.emit(kind, {"task_id": self.task_id, **payload}, message_id=request_id)
            value = await future
            self.ensure_alive()  # STOP wins even if a confirmation completed the future.
            return value
        finally:
            self.pending = None
            self._paused += self.clock() - started
            if self._timeout:
                self._timeout.reschedule(asyncio.get_running_loop().time() + remaining)
            if self.alive:
                await self.status("running", "Continuing")

    def respond(self, kind, task_id, re, payload):
        if not self.alive or task_id != self.task_id or not self.pending:
            return False
        expected, request_id, future, request = self.pending
        if kind != expected.replace("request", "response") or re != request_id or future.done():
            return False
        if kind == "choice_response":
            value = payload["choice_id"]
            if value is not None and value not in {option["id"] for option in request["options"]}:
                return False
        else:
            value = payload["confirmed"]
        future.set_result(value)
        return True

    async def resolve_contacts(self):
        text = self.plan.label + " " + (self.plan.detail or "")
        for alias, handles in self.profile["contacts"].items():
            if len(handles) <= 1 or not re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", text, re.I):
                continue
            offset = 0
            while True:
                remaining = handles[offset:]
                page = remaining[:3] if len(remaining) > 4 else remaining
                options = [{"id": str(offset + i), "label": alias, "detail": handle} for i, handle in enumerate(page)]
                if len(remaining) > 4:
                    options.append({"id": "next", "label": "More contacts"})
                selected = await self.wait_user("choice_request", {"question": f"Which {alias}?", "options": options})
                if selected is None:
                    raise TaskFailure("Contact choice cancelled")
                if selected == "next":
                    offset += 3
                    continue
                self.profile["contacts"][alias] = [handles[int(selected)]]
                break

    def element(self, args):
        element_id = args.get("id")
        if "snapshot_id" in args and args["snapshot_id"] != self.snapshot.snapshot_id:
            raise ValueError("stale_snapshot, re-read")
        if element_id:
            if not args.get("snapshot_id"):
                raise ValueError("stale_snapshot, re-read")
            element = next((e for e in self.snapshot.elements if e.id == element_id), None)
            if element is None:
                raise ValueError("unknown_element")
            if not element.enabled:
                raise ValueError("element_disabled")
            return element
        return self.snapshot.focused

    def demo_send_allowed(self, evidence=None):
        # The manifest/fixture grants approval; the editable profile cannot.
        # Titles and aliases are not recipient evidence, even if exactly equal.
        return isinstance(evidence, recipients.RecipientEvidence) and any(
            evidence.handle in handles and evidence.handle in self.demo_contacts.get(alias, [])
            for alias, handles in self.profile["contacts"].items())

    async def approved_recipient(self, element):
        self.ensure_alive()
        try:
            evidence = await asyncio.to_thread(recipients.read, self.snapshot, element)
        except Exception:
            raise TaskFailure("Demo send blocked: native recipient could not be verified") from None
        self.ensure_alive()
        if not self.demo_send_allowed(evidence):
            raise TaskFailure("Demo send blocked: recipient is outside the approved contacts")
        return evidence

    def confirmation_context(self, snapshot):
        """Keep native field values internal; compact labels can hide AXValue."""
        try:
            ax.verify_snapshot(snapshot.snapshot_id)
            context = ax.snapshot_context(snapshot.snapshot_id)
            if context is None:
                raise ValueError("missing native identity")
            values = []
            fields = list(snapshot.elements)
            if snapshot.focused and snapshot.focused not in fields:
                fields.append(snapshot.focused)
            for item in fields:
                if item.source == "ax" and item.role in {"AXTextField", "AXTextArea", "AXComboBox"}:
                    _, handle = ax.resolve(snapshot.snapshot_id, item.id)
                    value = ax.attribute(handle, "AXValue") if handle is not None else None
                    if not isinstance(value, str):
                        raise ValueError("unreadable native field")
                    values.append((item.role, item.label, item.description, item.bbox, value))
            ax.verify_snapshot(snapshot.snapshot_id)
            if ax.snapshot_context(snapshot.snapshot_id) != context:
                raise ValueError("native context changed")
            return context, sorted(values)
        except Exception:
            raise TaskFailure("Could not recheck confirmation context; no action executed") from None

    async def refresh_confirmation(self, args, element, native_context):
        """An approval applies only to the context actually displayed to the user."""
        def signature(item):
            return (item.role, item.label, item.description, item.enabled, item.bbox, item.source) if item else None
        def context(snapshot):
            return (snapshot.app, snapshot.bundle_id, snapshot.window_title, snapshot.url,
                    signature(snapshot.focused), sorted(signature(e) for e in snapshot.elements))
        previous = self.snapshot
        self.ensure_alive()
        try:
            fresh = await asyncio.to_thread(self.get_screen)
            fresh_native_context = await asyncio.to_thread(self.confirmation_context, fresh)
        except Exception as error:
            raise TaskFailure("Could not recheck confirmation context; no action executed") from error
        self.ensure_alive()
        if (native_context is None or context(previous) != context(fresh)
                or native_context != fresh_native_context):
            raise TaskFailure("Screen changed during confirmation; no action executed")
        args = dict(args)
        if element is not None:
            matches = [e for e in fresh.elements if signature(e) == signature(element)]
            if len(matches) != 1:
                raise TaskFailure("Confirmation target is ambiguous; no action executed")
            if args.get("id"):
                args["id"] = matches[0].id
        if "snapshot_id" in args:
            args["snapshot_id"] = fresh.snapshot_id
        self.snapshot = fresh
        return args

    def approved_structured_contacts(self):
        # The callback belongs to the already selected store. Never select/read
        # another private config, and never derive approvals from model input.
        approved = self.approval_source() if self.approval_source else self.demo_contacts
        if self.profile_source:
            contacts = self.profile_source().get("contacts", {})
            return {alias: [handle for handle in handles if handle in contacts.get(alias, ())]
                    for alias, handles in approved.items()}
        return approved

    async def execute_structured(self, call):
        self.ensure_alive()
        if self.user_cancelled or self.send_uncertain:
            return {"ok": False, "status": "cancelled", "code": "dispatch_blocked"}
        # Fingerprints stay internal and task-scoped. New model call ids do not
        # authorize a second dispatch of the same exact action within this task.
        digest = hashlib.sha256(json.dumps([call.name, call.args], sort_keys=True,
                                          ensure_ascii=False).encode()).hexdigest()
        key, call_key = (self.task_id, digest), (self.task_id, call.call_id)
        if key in self.action_claims or call_key in self.action_claims:
            return {"ok": False, "status": "cancelled", "code": "duplicate_request"}
        # Reserve before any await, including preparation/confirmation.
        self.action_claims[key] = self.action_claims[call_key] = "reserved"
        dispatched = False
        operation = OPERATIONS[call.name][0]
        try:
            self.action_registry.ensure_dispatch_allowed()
            request = self.action_registry.resolve(f"{self.task_id}:{call.call_id}", call.name, call.args,
                                                   self.profile, self.approved_structured_contacts())
            provider = self.action_registry.provider_for(operation)
            self._provider_task = asyncio.create_task(provider.prepare(request))
            action = await self._provider_task
            self.ensure_alive()
            self.action_registry.validate_prepared(request, action)
            decision = safety.structured_gate(action)
            if decision.required:
                confirmed = await self.wait_user("confirm_request", {
                    "action": decision.action, "title": decision.title, "details": decision.details,
                    "source": decision.source, "demo_noop": self.demo and decision.action == "buy"})
                self.ensure_alive()
                if not confirmed:
                    self.user_cancelled = True
                    result = ActionResult("cancelled", "user_cancelled")
                    return self.structured_result(operation, result)
                # Re-resolve approvals and exact request after the wait. Prepare
                # again without side effects to recheck selected account/provider.
                fresh_request = self.action_registry.resolve(request.request_id, call.name, call.args,
                    self.profile, self.approved_structured_contacts())
                if fresh_request != request or self.action_registry.provider_for(operation) is not provider:
                    raise ActionSetupError("Action changed during confirmation; no action executed")
                self._provider_task = asyncio.create_task(provider.prepare(fresh_request))
                fresh = await self._provider_task
                self.ensure_alive()
                self.action_registry.validate_prepared(fresh_request, fresh)
                # Approvals can change while preparation yields as well.
                final_request = self.action_registry.resolve(request.request_id, call.name, call.args,
                    self.profile, self.approved_structured_contacts())
                if (fresh != action or final_request != request
                        or self.action_registry.provider_for(operation) is not provider
                        or safety.structured_gate(fresh) != decision):
                    raise ActionSetupError("Action changed during confirmation; no action executed")
                if self.demo and decision.action == "buy":
                    self.structured_outcome = Outcome(True, "Demonstration only; purchase action was not executed")
                    return {"ok": True, "demo_noop": True}
            self.ensure_alive()
            async def dispatch():
                nonlocal dispatched
                # This runs in the provider task itself, closing the scheduling
                # gap between the caller's checks and the first transport call.
                self.ensure_alive()
                self.action_registry.ensure_dispatch_allowed()
                self.action_registry.validate_prepared(request, action)
                current = self.action_registry.resolve(request.request_id, call.name, call.args,
                    self.profile, self.approved_structured_contacts())
                if current != request or self.action_registry.provider_for(operation) is not provider:
                    raise ActionSetupError("Action changed before dispatch; no action executed")
                self.action_claims[key] = self.action_claims[call_key] = "dispatched"
                dispatched = True
                self._send_dispatched = operation in SEND
                self.snapshot = None
                return await provider.execute(action)
            self._provider_task = asyncio.create_task(dispatch())
            result = await self._provider_task
            self.ensure_alive()
            if not isinstance(result, ActionResult):
                result = ActionResult("unknown", "invalid_acknowledgement")
            self._send_dispatched = False
            return self.structured_result(operation, result)
        except asyncio.CancelledError:
            if dispatched and operation in SEND:
                self.structured_result(operation, ActionResult("unknown", "submission_uncertain"))
            raise
        except Exception:
            # Neither provider exceptions nor result codes/receipts are public.
            status = "unknown" if dispatched else "failed"
            return self.structured_result(operation, ActionResult(status, "provider_error"))
        finally:
            self._provider_task = None
            self._send_dispatched = False

    def structured_result(self, operation, result):
        if result.status == "cancelled":
            self.user_cancelled = True
        if result.status == "unknown" and operation in SEND:
            self.send_uncertain = True
        summary = {
            "completed": ("Provider acknowledged submission; recipient delivery is not verified"
                          if operation in SEND else "Launcher accepted the request; opening is not observed"),
            "failed": "Structured action failed; check provider setup and approved destination",
            "unknown": "Submission outcome unknown; do not retry automatically",
            "cancelled": "Action cancelled; no further actions will be dispatched",
        }[result.status]
        if not self.send_uncertain or result.status == "unknown":
            self.structured_outcome = Outcome(result.status == "completed", summary)
        return {"ok": result.status == "completed", "status": result.status,
                "code": {"completed": "provider_acknowledged", "failed": "setup_or_action_failed",
                         "unknown": "submission_uncertain", "cancelled": "action_cancelled"}[result.status],
                "summary": summary}

    async def execute(self, call):
        name, args = call.name, call.args
        from jsonschema import validate
        if name not in TOOL_SCHEMAS:
            raise ValueError("unknown_tool")
        validate(args, TOOL_SCHEMAS[name])
        self.ensure_alive()
        if name == "finish":
            if self.structured_outcome is not None:
                if self.structured_outcome.ok and (not args["ok"] or self.user_cancelled):
                    return Outcome(False, "Task did not finish; an earlier provider request was acknowledged")
                return self.structured_outcome
            return Outcome(args["ok"], args["summary"], None if args["ok"] else recovery_plans())
        if name in OPERATIONS:
            return await self.execute_structured(call)
        if name == "action_capabilities":
            result = {"available": list(self.action_registry.capabilities())}
            if self.action_registry.unavailable:
                result["unavailable"] = dict(self.action_registry.unavailable)
            return result
        if self.send_uncertain:
            return {"ok": False, "error": "Submission outcome unknown; further actions blocked"}
        if self.user_cancelled:
            return {"ok": False, "error": "user cancelled"}
        if name == "ask_user":
            options = [ChoiceOption.model_validate(o, strict=True).model_dump(mode="json") for o in args["options"]]
            if len({o["id"] for o in options}) != len(options):
                raise ValueError("duplicate_choice_id")
            choice = await self.wait_user("choice_request", {"question": args["question"], "options": options})
            return {"choice_id": choice}
        if name == "look_at_screen":
            result = await self.look_at_screen(args["question"])
            return {"answer": result.answer, "point": result.point}
        if name == "native_screen":
            self.snapshot = await asyncio.to_thread(self.get_screen)
            self.ensure_alive()
            return {"screen": self.snapshot.to_prompt()}
        if self.snapshot is None:
            self.snapshot = await asyncio.to_thread(self.get_screen)
            self.ensure_alive()
        if name in {"click_element", "press_keys", "type_text", "open_url"}:
            element = self.element(args)
            proposed = ProposedAction(name, element=element, keys=args.get("keys"), text=args.get("text"),
                                      submit=args.get("submit", False), url=args.get("url"),
                                      model_flag=args.get("requires_confirmation", False),
                                      model_reason=args.get("confirmation_reason"))
            decision = self.gate(proposed, self.snapshot)
            if decision.required:
                recipient = await self.approved_recipient(element) if self.demo and decision.action == "send" else None
                noop = self.demo and decision.action == "buy"
                native_context = await asyncio.to_thread(self.confirmation_context, self.snapshot) if not noop else None
                confirmed = await self.wait_user("confirm_request", {
                    "action": decision.action, "title": decision.title,
                    "details": decision.details + ([f"Approved recipient: {recipient.handle}"] if recipient else []),
                    "source": decision.source, "demo_noop": noop})
                self.ensure_alive()
                if not confirmed:
                    self.user_cancelled = True
                    return {"ok": False, "error": "user cancelled"}
                if noop:
                    return {"ok": True, "demo_noop": True}
                args = await self.refresh_confirmation(args, element, native_context)
                element = self.element(args)
                if self.gate(replace(proposed, element=element), self.snapshot) != decision:
                    raise TaskFailure("Confirmation policy changed; no action executed")
                if recipient is not None and await self.approved_recipient(element) != recipient:
                    raise TaskFailure("Recipient changed during confirmation; no action executed")
        self.ensure_alive()
        return await self.desktop.run(name, args, self.snapshot)

    async def run(self, *, show_screen=False):
        self._started = self.clock()
        try:
            async with asyncio.timeout(self.max_seconds) as self._timeout:
                if show_screen:
                    self.step = 1
                    result = await self.look_at_screen("What is on screen and what went wrong?")
                    return Outcome(True, result.answer, recovery_plans(screen=False))
                await self.resolve_contacts()
                if not self.structured_mode:
                    self.snapshot = await asyncio.to_thread(self.get_screen)
                include_address = bool(re.search(r"\b(fill|form|address|shipping|billing)\b",
                                                  self.plan.label + " " + (self.plan.detail or ""), re.I))
                while True:
                    self.ensure_alive()
                    if self.step >= self.max_steps:
                        raise TaskFailure("15 tool-call limit reached")
                    response = await self.complete("task_system", "agent", {
                        "profile_summary": profile_summary(self.profile, include_address),
                        "plan_label": self.plan.label, "plan_detail": self.plan.detail or "",
                        "screen": self.snapshot.to_prompt() if self.snapshot else ""},
                        tools=TOOLS, input_items=copy.deepcopy(self.history))
                    self.ensure_alive()
                    if not response.tool_calls:
                        raise TaskFailure("Model returned no finish or tool call")
                    # Echo all calls before returning their outputs (Responses API).
                    self.history.extend({"type": "function_call", "call_id": c.call_id,
                                         "name": c.name, "arguments": json.dumps(c.args)} for c in response.tool_calls)
                    for call in response.tool_calls:
                        if self.step >= self.max_steps:
                            raise TaskFailure("15 tool-call limit reached")
                        self.step += 1
                        await self.status("running", {"click_element": "Selecting an item", "type_text": "Entering text",
                            "open_app": "Opening an app", "open_url": "Opening a page", "press_keys": "Pressing keys",
                            "look_at_screen": "Looking at the window", "ask_user": "Checking a choice",
                            "finish": "Finishing"}.get(call.name, "Working"))
                        started = self.clock()
                        try:
                            result = await self.execute(call)
                        except TaskFailure:
                            raise
                        except Exception as error:
                            # Never automatically repeat an action that may have executed.
                            if call.name in OPERATIONS:
                                result = self.structured_result(OPERATIONS[call.name][0],
                                                                ActionResult("failed", "invalid_arguments"))
                            else:
                                key = (call.name, call.args.get("id", ""))
                                self.failures[key] = self.failures.get(key, 0) + 1
                                if self.failures[key] > 2:
                                    raise TaskFailure("Tool failed after two retries") from error
                                result = {"ok": False, "error": str(error)[:500]}
                        if (call.name in OPERATIONS and not result.get("ok")
                                and result.get("code") in {"setup_or_action_failed", "duplicate_request"}):
                            key = (call.name, "")
                            self.failures[key] = self.failures.get(key, 0) + 1
                            if self.failures[key] > 2:
                                raise TaskFailure("Tool failed after two retries")
                        self.log.event(task_id=self.task_id, plan_label=self.plan.label, tool=call.name,
                                       outcome="done" if isinstance(result, Outcome) or result.get("ok", True) else "failed",
                                       latency_ms=(self.clock() - started) * 1000)
                        if isinstance(result, Outcome):
                            return result
                        if call.name not in {*OPERATIONS, "native_screen"} and self.snapshot is not None:
                            self.snapshot = await asyncio.to_thread(self.get_screen)
                        self.ensure_alive()
                        if call.name not in OPERATIONS and self.snapshot is not None:
                            result["screen"] = self.snapshot.to_prompt()
                        self.history.append({"type": "function_call_output", "call_id": call.call_id,
                                             "output": json.dumps(result, ensure_ascii=False)})
        except (TaskFailure, TimeoutError) as error:
            if self.send_uncertain:
                return self.structured_outcome
            return Outcome(False, str(error) or "90 second task limit reached", recovery_plans())
