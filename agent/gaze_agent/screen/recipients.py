"""Internal, fail-closed evidence for a native field-backed composer.

No AX work on import, no Snapshot/protocol additions, and no title/body/alias
matching. Only English AXTitleUIElement relationships on native recipient
fields are supported. These layouts are synthetic until reviewed human
evidence is supplied; conversation headers, tokens, web apps and groups are
deliberately unsupported. A missing Cc/Bcc field in Mail also blocks Send.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from gaze_agent.screen import ax


class RecipientEvidenceError(ValueError):
    def __init__(self):
        super().__init__("Native recipient evidence is missing, ambiguous or unsupported")


@dataclass(frozen=True)
class RecipientEvidence:
    handle: str = field(repr=False)
    fields: tuple = field(repr=False)


def read(snapshot, element=None) -> RecipientEvidence:
    """Read exactly one destination from the snapshot's native composer.

    AXValue must be the complete handle, never a parsed display name. Traversal
    is bounded and only crosses native groups, so a sidebar, message body,
    search result or web page cannot supply recipient controls or the target.
    Native identity/focus and snapshot currency are checked around the read.
    """
    required = {"com.apple.mail": {"to", "cc", "bcc"}, "com.apple.MobileSMS": {"to"}}
    if snapshot.bundle_id not in required:
        raise RecipientEvidenceError()
    anchor = element or snapshot.focused
    if (anchor is None or anchor.source != "ax" or not anchor.enabled
            or anchor.role not in {"AXButton", "AXTextField", "AXTextArea", "AXComboBox"}):
        raise RecipientEvidenceError()
    try:
        ax.verify_snapshot(snapshot.snapshot_id)
        context = ax.snapshot_context(snapshot.snapshot_id)
        if context is None:
            raise RecipientEvidenceError()
        identity, _ = context
        app, _, window = ax.front_window()
        if (app.bundleIdentifier() != snapshot.bundle_id or window != identity.window
                or ax.window_identity(app, window) != identity):
            raise RecipientEvidenceError()
        resolved, target = ax.resolve(snapshot.snapshot_id, anchor.id)
        if resolved != anchor or target is None:
            raise RecipientEvidenceError()

        missing = object()
        seen, nodes, destinations = set(), [], {}
        target_found = False

        def walk(node, depth=0, hidden=False):
            nonlocal target_found
            if depth > 24 or len(seen) >= 512 or node in seen:
                raise RecipientEvidenceError()
            seen.add(node)
            role = ax.attribute(node, "AXRole", missing)
            if role is missing:
                raise RecipientEvidenceError()
            if role == "AXSheet":
                raise RecipientEvidenceError()
            hidden = hidden or bool(ax.attribute(node, "AXHidden", False))
            nodes.append(node)
            if node == target and not hidden:
                target_found = True
            if role in {"AXTextField", "AXComboBox"}:
                label = ax.attribute(node, "AXTitleUIElement")
                if label is not None:
                    label_role = ax.attribute(label, "AXRole")
                    text = ax.attribute(label, "AXValue")
                    if not isinstance(text, str):
                        text = ax.attribute(label, "AXTitle")
                    key = text.strip().casefold().removesuffix(":") if isinstance(text, str) else ""
                    if key in {"to", "cc", "bcc"}:
                        value = ax.attribute(node, "AXValue", missing)
                        if (hidden or label_role != "AXStaticText" or key in destinations
                                or not isinstance(value, str) or value != value.strip()
                                or any(ord(c) < 32 for c in value)
                                or ax.attribute(node, "AXChildren", [])
                                or ax.attribute(node, "AXEnabled", missing) is not True):
                            raise RecipientEvidenceError()
                        destinations[key] = (value, node, label)
            if role in {"AXWindow", "AXGroup"}:
                children = ax.attribute(node, "AXChildren", missing)
                if not isinstance(children, (list, tuple)):
                    raise RecipientEvidenceError()
                for child in children:
                    walk(child, depth + 1, hidden)

        if ax.attribute(window, "AXRole") != "AXWindow":
            raise RecipientEvidenceError()
        walk(window)
        if (not target_found or set(destinations) != required[snapshot.bundle_id]
                or any(label not in nodes or node == target for _, node, label in destinations.values())):
            raise RecipientEvidenceError()
        # Exactly one populated To and no other destinations, including Cc/Bcc.
        value = destinations["to"][0]
        if not value or any(v for key, (v, _, _) in destinations.items() if key != "to"):
            raise RecipientEvidenceError()
        if any(ax.attribute(node, "AXValue") != v or ax.attribute(node, "AXTitleUIElement") != label
               for v, node, label in destinations.values()):
            raise RecipientEvidenceError()
        # No list/display-name parsing or formatting normalization is safe here.
        if not (value.startswith("+") and all(c in "+0123456789 ()-" for c in value)
                and value.count("+") == 1 and sum(c.isdigit() for c in value) >= 7
                or value.count("@") == 1 and all(c not in value for c in " ,;<>\n\r\t")
                and "." in value.split("@")[1] and all(value.split("@"))):
            raise RecipientEvidenceError()
        ax.verify_snapshot(snapshot.snapshot_id)
        if ax.snapshot_context(snapshot.snapshot_id) != context:
            raise RecipientEvidenceError()
        return RecipientEvidence(value, tuple((k, n, label) for k, (_, n, label) in sorted(destinations.items())))
    except RecipientEvidenceError:
        raise
    except Exception:
        # AX failures must never leak native values/handles into task results.
        raise RecipientEvidenceError() from None
