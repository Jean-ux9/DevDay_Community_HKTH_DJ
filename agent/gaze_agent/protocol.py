"""Pydantic models for every WebSocket message (spec §4).

Mirrors protocol/messages.schema.json, which stays the source of truth;
tests/test_contract.py fails if the two drift apart. Frozen after Phase 0.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

PROTOCOL_VERSION = 1
UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

Uuid = Annotated[str, Field(pattern=UUID_PATTERN)]
NonEmpty = Annotated[str, Field(min_length=1)]
ErrorCode = Literal["bad_message", "version_mismatch", "unknown_plan", "stale_list", "task_busy", "no_task",
                    "llm_failed", "internal"]


class Model(BaseModel):
    """Strict base: unknown fields are rejected, and unset optional fields are left out when dumped."""

    model_config = ConfigDict(extra="forbid")

    @model_serializer(mode="wrap")
    def _drop_empty_optionals(self, handler: Any) -> Any:
        data = handler(self)
        if isinstance(data, dict):
            for name, field in type(self).model_fields.items():
                if not field.is_required() and name in data and data[name] is None:
                    del data[name]
        return data


# ---- shared shapes ----------------------------------------------------------------------------

class Plan(Model):
    id: NonEmpty
    label: Annotated[str, Field(min_length=1, max_length=40)]
    detail: str | None = None
    kind: Literal["task", "other", "recovery"]
    risky: bool


class ChoiceOption(Model):
    id: NonEmpty
    label: NonEmpty
    detail: str | None = None


class Favorites(Model):
    artist: str
    playlist: str
    sites: list[str]


class Style(Model):
    tone: str
    signature: str
    phrases: list[str]


class Address(Model):
    full_name: str
    city: str
    email: str


class Profile(Model):
    name: str
    favorites: Favorites
    contacts: dict[str, Annotated[list[str], Field(min_length=1)]]
    style: Style
    address: Address


class Settings(Model):
    dwellMs: Annotated[int, Field(ge=500, le=2000)]
    blinkSelect: bool
    density: Literal["large", "compact"]
    gazeSource: Literal["webgazer", "mouse"]
    calibrationMode: Literal["gaze", "caregiver"]


class Permissions(Model):
    accessibility: bool
    screen_recording: bool
    camera: Literal["unknown"]


class Envelope(Model):
    v: Literal[1]
    type: str
    id: Uuid
    re: Uuid | None
    ts: Annotated[int, Field(ge=0)]
    payload: dict[str, Any]


# ---- overlay -> agent -------------------------------------------------------------------------

class Hello(Model):
    client: Literal["overlay"]
    version: str


class ModeSet(Model):
    mode: Literal["auto", "type"]


class GazeContext(Model):
    dock_idle: bool
    idle_ms: Annotated[float, Field(ge=0)]


class AutoRefresh(Model):
    pass


class DecodeRequest(Model):
    words: list[str]
    raw_keys: list[Annotated[list[str], Field(min_length=1)]]
    context: str | None = None


class IntentSubmit(Model):
    text: NonEmpty


class PlanSelect(Model):
    list_id: NonEmpty
    plan_id: NonEmpty


class ChoiceResponse(Model):
    task_id: Uuid
    choice_id: str | None  # required; null = cancel


class ConfirmResponse(Model):
    task_id: Uuid
    confirmed: bool


class Stop(Model):
    reason: Literal["gaze", "hotkey", "user"]


class ProfileGet(Model):
    pass


class ProfileUpdate(Model):
    patch: dict[str, Any]


class SettingsUpdate(Model):
    patch: dict[str, Any]


class PermissionsCheck(Model):
    pass


class OpenSettingsPane(Model):
    pane: Literal["accessibility", "screen_recording", "camera"]


# ---- agent -> overlay -------------------------------------------------------------------------

class HelloAck(Model):
    version: str
    demo_mode: bool
    profile: Profile
    settings: Settings
    permissions: Permissions


class PermissionsStatus(Permissions):
    pass


class Suggestions(Model):
    list_id: NonEmpty
    window_key: str
    app: str
    items: Annotated[list[Plan], Field(min_length=3, max_length=4)]
    cached: bool


class DecodeResult(Model):
    sentences: Annotated[list[NonEmpty], Field(min_length=1, max_length=3)]


class Plans(Model):
    list_id: NonEmpty
    items: Annotated[list[Plan], Field(min_length=3, max_length=5)]  # 2-4 plans + "other"


class TaskStatus(Model):
    task_id: Uuid
    state: Literal["running", "waiting_user", "done", "failed", "stopped"]
    step: Annotated[int, Field(ge=0, le=15)]
    max_steps: Literal[15]
    message: str


class ChoiceRequest(Model):
    task_id: Uuid
    question: NonEmpty
    options: Annotated[list[ChoiceOption], Field(min_length=2, max_length=4)]


class ConfirmRequest(Model):
    task_id: Uuid
    action: Literal["send", "buy", "delete", "submit", "post", "other"]
    title: NonEmpty
    details: list[str]
    source: Literal["rule", "model", "both"]
    demo_noop: bool


class TaskResult(Model):
    task_id: Uuid
    ok: bool
    summary: str
    list_id: NonEmpty | None = None
    recovery: Annotated[list[Plan], Field(min_length=1, max_length=3)] | None = None

    @model_validator(mode="after")
    def _recovery_needs_list(self) -> TaskResult:
        if self.recovery is not None and self.list_id is None:
            raise ValueError("recovery requires list_id")
        return self


class ProfileResult(Model):
    profile: Profile


class SettingsResult(Model):
    settings: Settings


class Error(Model):
    code: ErrorCode
    message: str
    task_id: Uuid | None = None


# ---- registry ---------------------------------------------------------------------------------

O2A: dict[str, type[Model]] = {
    "hello": Hello, "mode_set": ModeSet, "gaze_context": GazeContext, "auto_refresh": AutoRefresh,
    "decode_request": DecodeRequest, "intent_submit": IntentSubmit, "plan_select": PlanSelect,
    "choice_response": ChoiceResponse, "confirm_response": ConfirmResponse, "stop": Stop,
    "profile_get": ProfileGet, "profile_update": ProfileUpdate, "settings_update": SettingsUpdate,
    "permissions_check": PermissionsCheck, "open_settings_pane": OpenSettingsPane,
}
A2O: dict[str, type[Model]] = {
    "hello_ack": HelloAck, "permissions_status": PermissionsStatus, "suggestions": Suggestions,
    "decode_result": DecodeResult, "plans": Plans, "task_status": TaskStatus, "choice_request": ChoiceRequest,
    "confirm_request": ConfirmRequest, "task_result": TaskResult, "profile_result": ProfileResult,
    "settings_result": SettingsResult, "error": Error,
}
PAYLOADS: dict[str, type[Model]] = O2A | A2O


def parse_payload(mtype: str, payload: dict[str, Any]) -> Model:
    """Validate a payload for message type `mtype`. Raises KeyError or pydantic.ValidationError."""
    return PAYLOADS[mtype].model_validate(payload)


def dump_payload(model: Model) -> dict[str, Any]:
    """JSON-ready dict that validates against the schema (unset optionals omitted)."""
    return model.model_dump(mode="json")
