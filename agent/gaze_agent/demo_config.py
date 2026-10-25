"""Explicit opt-in private demo persona, recipient allowlist and storage (issue #5).

Unset ``GAZE_DEMO_CONFIG`` keeps every public-fixture path unchanged: ``selected()``
returns ``None``. When it names an absolute manifest path, the manifest supplies
the approved persona, the approved recipients, and private data/cache directories
outside any Git work tree, and ``DEMO_MODE=1`` is required.

Import-safe for the harness's script environment: standard library only, no
reads of files, credentials or user data on import. Validation reads the manifest
and the frozen protocol schema (``jsonschema`` is imported only then). Error
messages name the field and reason, never paths, handles or persona values.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SELECTOR_ENV = "GAZE_DEMO_CONFIG"
MANIFEST_FORMAT = "gaze-private-demo/1"
REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_PERSONA_PATH = REPO_ROOT / "fixtures" / "demo_profile.json"
SCHEMA_PATH = REPO_ROOT / "protocol" / "messages.schema.json"
USER_DATA_DIR = Path.home() / "Library/Application Support/GazeCopilot"
MAX_MANIFEST_BYTES = 64 * 1024
_FIELDS = {"format", "config_id", "persona", "approved_recipients", "data_dir", "cache_dir"}
_CONFIG_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class DemoConfigError(ValueError):
    """Invalid or unsafe private demo configuration; the message is sanitized."""


def _fail(message: str) -> DemoConfigError:
    return DemoConfigError(f"Private demo config: {message}")


@dataclass(frozen=True, repr=False)
class PrivateDemoConfig:
    """A validated private demo configuration; accessors return fresh copies."""
    config_id: str
    data_dir: Path
    cache_dir: Path
    fingerprint: str
    _persona: str
    _approved: tuple[tuple[str, tuple[str, ...]], ...]

    def __repr__(self) -> str:
        # Logs and tracebacks must not reveal handles, persona values or paths.
        return f"PrivateDemoConfig({self.config_id!r}, fingerprint={self.fingerprint[:16]})"

    @property
    def recording_dir(self) -> Path:
        """Replay namespace: a changed persona/allowlist never reuses old recordings."""
        return self.cache_dir / f"{self.config_id}-{self.fingerprint[:16]}"

    def persona(self) -> dict[str, Any]:
        return json.loads(self._persona)

    def approved_contacts(self) -> dict[str, list[str]]:
        return {alias: list(handles) for alias, handles in self._approved}

    def check_profile(self, profile: Mapping[str, Any]) -> None:
        """Reject an active profile whose contacts are not all approved."""
        approved = dict(self._approved)
        contacts = profile.get("contacts")
        if not isinstance(contacts, Mapping):
            raise _fail("the active profile has no contacts mapping")
        for alias, handles in contacts.items():
            allowed = approved.get(alias)
            if allowed is None or not isinstance(handles, list) or not all(h in allowed for h in handles):
                raise _fail("the active profile has a contact that is not an approved recipient")


def selected(environ: Mapping[str, str] | None = None) -> PrivateDemoConfig | None:
    """The opted-in private config, or ``None`` for the unchanged public default."""
    env = os.environ if environ is None else environ
    raw = env.get(SELECTOR_ENV, "")
    if raw == "":
        return None
    if env.get("DEMO_MODE") != "1":
        raise _fail(f"{SELECTOR_ENV} requires DEMO_MODE=1")
    return load_manifest(raw)


def load_manifest(path: str | os.PathLike[str]) -> PrivateDemoConfig:
    raw = os.fspath(path)
    if not raw or "\x00" in raw or not os.path.isabs(raw):
        raise _fail(f"{SELECTOR_ENV} must be an absolute path")
    manifest = Path(raw).resolve()
    _reject_tracked(manifest, "the manifest")
    try:
        info = manifest.stat()
    except OSError:
        raise _fail("the manifest file cannot be read") from None
    if not stat.S_ISREG(info.st_mode):
        raise _fail("the manifest must be a regular file")
    if info.st_size > MAX_MANIFEST_BYTES:
        raise _fail("the manifest is too large")
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise _fail("the manifest must be owned by this user and not group/world-writable")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys,
                          parse_constant=_no_constant)
    except (OSError, UnicodeDecodeError, ValueError):
        raise _fail("the manifest is not valid JSON") from None
    return parse_manifest(data, manifest_path=manifest)


def parse_manifest(data: Any, *, manifest_path: Path | None = None) -> PrivateDemoConfig:
    if not isinstance(data, dict):
        raise _fail("the manifest must be a JSON object")
    if set(data) != _FIELDS:
        # Unknown names are manifest text, so only their number is reported.
        unknown, missing = len(set(data) - _FIELDS), sorted(_FIELDS - set(data))
        raise _fail(f"{unknown} unknown field(s), missing fields {missing}")
    if data["format"] != MANIFEST_FORMAT:
        raise _fail(f"format must be {MANIFEST_FORMAT!r}")
    config_id = data["config_id"]
    if not isinstance(config_id, str) or not _CONFIG_ID.fullmatch(config_id):
        raise _fail("config_id must be 1-48 letters, digits, '-' or '_', starting with a letter or digit")
    persona = _persona(data["persona"])
    approved = _recipients(data["approved_recipients"], "approved_recipients")
    _recipients(persona["contacts"], "persona.contacts")
    if {a: set(h) for a, h in approved.items()} != {a: set(h) for a, h in persona["contacts"].items()}:
        raise _fail("approved_recipients must list exactly the persona's contacts")
    data_dir = _private_dir(data["data_dir"], "data_dir")
    cache_dir = _private_dir(data["cache_dir"], "cache_dir")
    if _overlap(data_dir, cache_dir):
        raise _fail("data_dir and cache_dir must be separate, non-nested directories")
    if manifest_path is not None and any(manifest_path.is_relative_to(d) for d in (data_dir, cache_dir)):
        raise _fail("the manifest must not be inside data_dir or cache_dir")
    pairs = tuple((alias, tuple(handles)) for alias, handles in approved.items())
    identity = {"format": MANIFEST_FORMAT, "config_id": config_id, "persona": persona,
                "approved_recipients": sorted((a, sorted(h)) for a, h in pairs)}
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False,
                                            separators=(",", ":")).encode()).hexdigest()
    return PrivateDemoConfig(config_id, data_dir, cache_dir, fingerprint,
                             json.dumps(persona, ensure_ascii=False), pairs)


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _no_constant(_: str) -> Any:
    raise ValueError("non-finite number")


def _persona(value: Any) -> dict[str, Any]:
    """Validate against the frozen protocol Profile and return it in schema key order."""
    import jsonschema  # deferred: keeps import-time cost and dependencies at zero

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["$defs"]["Profile"]
    if not isinstance(value, dict):
        raise _fail("persona must be a profile object")
    error = jsonschema.exceptions.best_match(jsonschema.Draft202012Validator(schema).iter_errors(value))
    if error is not None:
        field = next(iter(error.absolute_path), None)
        raise _fail(f"persona.{field} is invalid" if isinstance(field, str) else "persona is not a valid profile")
    return _ordered(value, schema)


def _ordered(value: Any, schema: Mapping[str, Any]) -> Any:
    # The protocol model dumps fields in schema order; profile_summary() strings
    # built from the persona and from the stored profile must therefore match.
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        extra = schema.get("additionalProperties")
        return {key: _ordered(value[key], properties[key]) for key in properties if key in value} | {
            key: _ordered(item, extra if isinstance(extra, dict) else {})
            for key, item in value.items() if key not in properties}
    if isinstance(value, list):
        return [_ordered(item, schema.get("items", {})) for item in value]
    return value


def _recipients(value: Any, field: str) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        raise _fail(f"{field} must map aliases to handle lists")
    aliases, handles = set(), set()
    for alias, items in value.items():
        if not _clean(alias, 64) or alias.casefold() in aliases:
            raise _fail(f"{field} has an empty, padded, too long or duplicate alias")
        aliases.add(alias.casefold())
        if not isinstance(items, list) or not items:
            raise _fail(f"{field} needs at least one handle per alias")
        for handle in items:
            if not _clean(handle, 254) or handle.casefold() in handles:
                raise _fail(f"{field} has an empty, padded, too long or duplicate handle")
            handles.add(handle.casefold())
    return {alias: list(items) for alias, items in value.items()}


def _clean(text: Any, limit: int) -> bool:
    return (isinstance(text, str) and 0 < len(text) <= limit and text == text.strip()
            and not _CONTROL.search(text))


def _private_dir(value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value or not os.path.isabs(value):
        raise _fail(f"{field} must be an absolute path")
    # Check the user's default store lexically first so it is never even resolved.
    user = Path(os.path.normpath(USER_DATA_DIR))
    if _overlap(Path(os.path.normpath(value)), user):
        raise _fail(f"{field} must not overlap the default user data directory")
    path = Path(value).resolve()
    if path == Path(path.anchor) or path == Path.home().resolve():
        raise _fail(f"{field} must be a dedicated directory, not the filesystem root or home")
    if _overlap(path, user.resolve()):
        raise _fail(f"{field} must not overlap the default user data directory")
    _reject_tracked(path, field)
    return path


def _reject_tracked(path: Path, field: str) -> None:
    """Private data must never land in this checkout or any other Git work tree."""
    if path.is_relative_to(REPO_ROOT) or any((p / ".git").exists() for p in (path, *path.parents)):
        raise _fail(f"{field} must be outside every Git work tree")


def _overlap(a: Path, b: Path) -> bool:
    return a.is_relative_to(b) or b.is_relative_to(a)
