"""Additive, transport-independent action contracts for H1/H2/H3.

Providers prepare without side effects and execute only the supplied frozen
payload. Construction/import must perform no native, process, profile or network
I/O. Cancellation must terminate and reap any subprocess owned by the provider.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Protocol


def freeze(value):
    """Copy JSON-shaped inputs recursively; reject mutable/opaque leaf objects."""
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("Action mapping keys must be strings")
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    if value is None or type(value) in (str, bool, int, float):
        return value
    raise ValueError("Unsupported action value")


@dataclass(frozen=True)
class ActionRequest:
    request_id: str
    operation: str
    arguments: Mapping = field(repr=False)

    def __post_init__(self):
        if not isinstance(self.arguments, Mapping):
            raise ValueError("Action arguments must be a mapping")
        object.__setattr__(self, "arguments", freeze(self.arguments))


@dataclass(frozen=True)
class PreparedAction:
    request_id: str
    operation: str
    provider: str
    payload: Mapping = field(repr=False)

    def __post_init__(self):
        if not isinstance(self.payload, Mapping):
            raise ValueError("Action payload must be a mapping")
        object.__setattr__(self, "payload", freeze(self.payload))


@dataclass(frozen=True)
class ActionResult:
    status: Literal["completed", "failed", "unknown", "cancelled"]
    code: str
    receipt: str | None = field(default=None, repr=False)

    def __post_init__(self):
        if self.status not in {"completed", "failed", "unknown", "cancelled"}:
            raise ValueError("Invalid action result status")


class ActionProvider(Protocol):
    async def prepare(self, request: ActionRequest) -> PreparedAction: ...

    async def execute(self, action: PreparedAction) -> ActionResult: ...
