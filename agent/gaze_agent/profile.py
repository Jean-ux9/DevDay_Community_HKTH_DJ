"""Validated atomic profile/settings storage (spec §10)."""
from __future__ import annotations
import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from gaze_agent.protocol import Profile, Settings

DATA_DIR = Path.home() / "Library/Application Support/GazeCopilot"
DEMO_PROFILE = Path(__file__).resolve().parents[2] / "fixtures/demo_profile.json"
DEFAULT_PROFILE = {"name": "", "favorites": {"artist": "", "playlist": "", "sites": []},
                   "contacts": {}, "style": {"tone": "casual", "signature": "", "phrases": []},
                   "address": {"full_name": "", "city": "", "email": ""}}
DEFAULT_SETTINGS = {"dwellMs": 800, "blinkSelect": False, "density": "large",
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
                 demo_profile: Path = DEMO_PROFILE):
        self.directory = Path(directory)
        self.demo = os.getenv("DEMO_MODE") == "1" if demo is None else demo
        self.demo_profile = demo_profile

    def _load(self, name: str, model: type, default: dict) -> dict:
        path = self.directory / f"{name}.json"
        if path.exists():
            data = json.loads(path.read_text())
        elif name == "profile" and self.demo:
            data = json.loads(self.demo_profile.read_text())
        else:
            data = copy.deepcopy(default)
        result = model.model_validate(data, strict=True).model_dump(mode="json")
        if not path.exists():
            atomic_json(path, result)
        return result

    def load_profile(self) -> dict:
        return self._load("profile", Profile, DEFAULT_PROFILE)

    def load_settings(self) -> dict:
        return self._load("settings", Settings, DEFAULT_SETTINGS)

    def _update(self, name: str, patch: dict, model: type, old: dict) -> dict:
        value = model.model_validate(merge_patch(old, patch), strict=True).model_dump(mode="json")
        atomic_json(self.directory / f"{name}.json", value)
        return value

    def update_profile(self, patch: dict) -> dict:
        return self._update("profile", patch, Profile, self.load_profile())

    def update_settings(self, patch: dict) -> dict:
        return self._update("settings", patch, Settings, self.load_settings())


def load_profile() -> dict[str, Any]:
    return ProfileStore().load_profile()


def profile_summary(profile: dict[str, Any], include_address: bool = False) -> str:
    public = {key: profile[key] for key in ("name", "favorites", "contacts", "style")}
    if include_address:
        public["address"] = profile["address"]
    return json.dumps(public, ensure_ascii=False)
