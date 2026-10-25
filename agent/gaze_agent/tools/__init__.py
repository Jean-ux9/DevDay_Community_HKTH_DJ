"""Structured action interfaces; importing this package performs no I/O."""

from .contracts import ActionProvider, ActionRequest, ActionResult, PreparedAction

__all__ = ["ActionProvider", "ActionRequest", "ActionResult", "PreparedAction"]
