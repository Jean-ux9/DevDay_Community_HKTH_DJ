"""Validated atomic profile/settings storage (spec §10)."""
from __future__ import annotations
import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from gaze_agent.demo_config import (PUBLIC_PERSONA_PATH, USER_DATA_DIR, DemoConfigError,
                                    PrivateDemoConfig, selected)
from gaze_agent.protocol import Profile, Settings

DATA_DIR = USER_DATA_DIR
DEMO_PROFILE = PUBLIC_PERSONA_PATH
DEFAULT_PROFILE = {"name": "", "favorites": {"artist": "", "playlist": "", "sites": []},
                   "contacts": {}, "style": {"tone": "casual", "signature": "", "phrases": []},
                   "address": {"full_name": "", "city": "", "email": ""}}
DEFAULT_SETTINGS = {"dwellMs": 1300, "blinkSelect": False, "density": "large",
                    "gazeSource": "webgazer", "calibrationMode": "gaze"}


def merge_patch(target: Any, patch: Any) -> Any:
    """RFC 7386 without mutating the caller's value."""
    if not isinstance(patch, dict):
        return copy.deepcopy(patch)
    result = copy.deepcopy(target) if isinstance(target, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = merge_patch(result.get(key), value)
    return result


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class ProfileStore:
    def __init__(self, directory: Path = DATA_DIR, *, demo: bool | None = None,
                 demo_profile: Path = DEMO_PROFILE, demo_config: PrivateDemoConfig | None = None):
        self.directory = Path(directory)
        self.demo = os.getenv("DEMO_MODE") == "1" if demo is None else demo
        self.demo_profile = demo_profile
        self.demo_config = demo_config
        if demo_config is not None and (not self.demo or self.directory.resolve() != demo_config.data_dir):
            raise DemoConfigError("Private demo config: its store must use demo mode and its own data_dir")

    @classmethod
    def for_demo_config(cls, config: PrivateDemoConfig | None) -> ProfileStore:
        """The store for ``demo_config.selected()``; ``None`` is the unchanged default."""
        if config is None:
            return cls()
        return cls(config.data_dir, demo=True, demo_config=config)

    def approved_contacts(self) -> dict[str, list[str]]:
        """Demo Send allowlist. Never derived from the editable active profile."""
        if self.demo_config is not None:
            return self.demo_config.approved_contacts()
        if self.demo and self.demo_profile.exists():
            return json.loads(self.demo_profile.read_text()).get("contacts", {})
        return {}

    def _load(self, name: str, model: type, default: dict) -> dict:
        path = self.directory / f"{name}.json"
        if path.exists():
            data = json.loads(path.read_text())
        elif name == "profile" and self.demo_config is not None:
            data = self.demo_config.persona()
        elif name == "profile" and self.demo:
            data = json.loads(self.demo_profile.read_text())
        else:
            data = copy.deepcopy(default)
        result = model.model_validate(data, strict=True).model_dump(mode="json")
        if name == "profile" and self.demo_config is not None:
            self.demo_config.check_profile(result)
        if not path.exists():
            atomic_json(path, result)
        return result

    def load_profile(self) -> dict:
        return self._load("profile", Profile, DEFAULT_PROFILE)

    def load_settings(self) -> dict:
        return self._load("settings", Settings, DEFAULT_SETTINGS)

    def _update(self, name: str, patch: dict, model: type, old: dict) -> dict:
        value = model.model_validate(merge_patch(old, patch), strict=True).model_dump(mode="json")
        if name == "profile" and self.demo_config is not None:
            # A profile edit must not silently enlarge the approved recipients.
            self.demo_config.check_profile(value)
        atomic_json(self.directory / f"{name}.json", value)
        return value

    def update_profile(self, patch: dict) -> dict:
        return self._update("profile", patch, Profile, self.load_profile())

    def update_settings(self, patch: dict) -> dict:
        return self._update("settings", patch, Settings, self.load_settings())


def load_profile() -> dict[str, Any]:
    return ProfileStore.for_demo_config(selected()).load_profile()


def profile_summary(profile: dict[str, Any], include_address: bool = False) -> str:
    public = {key: profile[key] for key in ("name", "favorites", "contacts", "style")}
    if include_address:
        public["address"] = profile["address"]
    return json.dumps(public, ensure_ascii=False)
