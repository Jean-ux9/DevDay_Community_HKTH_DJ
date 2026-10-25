"""Private demo provider (#5): selector, manifest validation and import safety.

Only synthetic temporary manifests and FAKE handles are used. No real profile,
.env, Application Support directory or private manifest is read.
"""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from gaze_agent import demo_config, profile
from gaze_agent.demo_config import DemoConfigError
from gaze_agent.protocol import Profile

FAKE_PERSONA = {
    "name": "Riley Example",
    "favorites": {"artist": "The Placeholder Band", "playlist": "Quiet Hours", "sites": ["tickets.example"]},
    "contacts": {"Mom": ["+1 555 0142"], "Alex": ["alex.rehearsal@example.invalid"]},
    "style": {"tone": "casual", "signature": "– Riley", "phrases": ["on my way", "sounds good"]},
    "address": {"full_name": "Riley Example", "city": "Testville", "email": "riley@example.invalid"},
}
FAKE_HANDLES = ("+1 555 0142", "alex.rehearsal@example.invalid")


def manifest_data(root: Path, **changes) -> dict:
    data = {"format": demo_config.MANIFEST_FORMAT, "config_id": "fake-demo",
            "persona": copy.deepcopy(FAKE_PERSONA),
            "approved_recipients": copy.deepcopy(FAKE_PERSONA["contacts"]),
            "data_dir": str(root / "private-data"), "cache_dir": str(root / "private-cache")}
    data.update(changes)
    return data


def write_manifest(root: Path, name: str = "demo.json", **changes) -> Path:
    path = root / "private-manifest" / name
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(manifest_data(root, **changes)))
    path.chmod(0o600)
    return path


def select_private(monkeypatch, root: Path, name: str = "demo.json", **changes):
    monkeypatch.setenv(demo_config.SELECTOR_ENV, str(write_manifest(root, name, **changes)))
    monkeypatch.setenv("DEMO_MODE", "1")
    return demo_config.selected()


@pytest.fixture(autouse=True)
def synthetic_selector_only(monkeypatch, tmp_path):
    """An inherited selector or the real default user directory must never be used."""
    monkeypatch.delenv(demo_config.SELECTOR_ENV, raising=False)
    monkeypatch.setattr(demo_config, "USER_DATA_DIR", tmp_path / "default-user-data")


def assert_sanitized(error, root: Path):
    text = str(error)
    assert text.startswith("Private demo config: ")
    assert str(root) not in text and str(root.resolve()) not in text
    assert not any(handle in text for handle in FAKE_HANDLES)


def test_unset_or_empty_selector_is_the_unchanged_public_default(tmp_path):
    assert demo_config.selected({}) is None
    assert demo_config.selected({demo_config.SELECTOR_ENV: "", "DEMO_MODE": "0"}) is None
    assert profile.DATA_DIR == Path.home() / "Library/Application Support/GazeCopilot"
    assert profile.DEMO_PROFILE == demo_config.REPO_ROOT / "fixtures/demo_profile.json"


def test_selector_requires_demo_mode_before_reading_the_manifest(tmp_path):
    absent = tmp_path / "never-created.json"
    for mode in ("0", "", None):
        env = {demo_config.SELECTOR_ENV: str(absent)} | ({"DEMO_MODE": mode} if mode is not None else {})
        with pytest.raises(DemoConfigError, match="requires DEMO_MODE=1") as error:
            demo_config.selected(env)
        assert_sanitized(error.value, tmp_path)
    with pytest.raises(DemoConfigError, match="cannot be read"):
        demo_config.selected({demo_config.SELECTOR_ENV: str(absent), "DEMO_MODE": "1"})


def test_valid_manifest_yields_immutable_approved_persona_and_private_dirs(monkeypatch, tmp_path):
    shuffled = {key: FAKE_PERSONA[key] for key in ("address", "contacts", "style", "favorites", "name")}
    config = select_private(monkeypatch, tmp_path, persona=shuffled)
    assert config.config_id == "fake-demo"
    assert config.data_dir == (tmp_path / "private-data").resolve()
    assert config.cache_dir == (tmp_path / "private-cache").resolve()
    assert config.recording_dir == config.cache_dir / f"fake-demo-{config.fingerprint[:16]}"
    assert len(config.fingerprint) == 64 and int(config.fingerprint, 16) >= 0
    persona = config.persona()
    assert persona == FAKE_PERSONA and list(persona) == list(FAKE_PERSONA)
    # The stored profile is dumped in model order; summaries must compare equal.
    dumped = Profile.model_validate(persona, strict=True).model_dump(mode="json")
    assert profile.profile_summary(dumped) == profile.profile_summary(persona)
    assert config.approved_contacts() == FAKE_PERSONA["contacts"]
    persona["contacts"]["Boss"] = ["boss@example.invalid"]
    config.approved_contacts()["Mom"].append("+1 555 0199")
    assert config.persona() == FAKE_PERSONA and config.approved_contacts() == FAKE_PERSONA["contacts"]
    assert not (tmp_path / "private-data").exists() and not (tmp_path / "private-cache").exists()
    shown = repr(config) + str(config)
    assert "fake-demo" in shown and str(tmp_path) not in shown and not any(h in shown for h in FAKE_HANDLES)


def test_fingerprint_separates_personas_but_not_storage_locations(tmp_path):
    base = demo_config.parse_manifest(manifest_data(tmp_path))
    reordered = manifest_data(tmp_path, approved_recipients={"Alex": FAKE_PERSONA["contacts"]["Alex"],
                                                             "Mom": FAKE_PERSONA["contacts"]["Mom"]})
    moved = manifest_data(tmp_path, data_dir=str(tmp_path / "elsewhere-data"),
                          cache_dir=str(tmp_path / "elsewhere-cache"))
    assert demo_config.parse_manifest(reordered).fingerprint == base.fingerprint
    assert demo_config.parse_manifest(moved).fingerprint == base.fingerprint
    changed_contacts = {"Mom": ["+1 555 0177"], "Alex": FAKE_PERSONA["contacts"]["Alex"]}
    changed = manifest_data(tmp_path, persona={**FAKE_PERSONA, "contacts": changed_contacts},
                            approved_recipients=changed_contacts)
    renamed = manifest_data(tmp_path, config_id="fake-demo-2")
    style = manifest_data(tmp_path, persona={**FAKE_PERSONA, "style": {**FAKE_PERSONA["style"], "tone": "formal"}})
    for variant in (changed, renamed, style):
        other = demo_config.parse_manifest(variant)
        assert other.fingerprint != base.fingerprint and other.recording_dir != base.recording_dir


def _persona(**changes):
    return {**copy.deepcopy(FAKE_PERSONA), **changes}


BAD_MANIFESTS = {
    "not an object": lambda root: ["fake"],
    "missing field": lambda root: {k: v for k, v in manifest_data(root).items() if k != "cache_dir"},
    "unknown field": lambda root: manifest_data(root, aproved_recipients={}),
    "wrong format": lambda root: manifest_data(root, format="gaze-private-demo/2"),
    "path-like id": lambda root: manifest_data(root, config_id="../escape"),
    "hidden id": lambda root: manifest_data(root, config_id=".fake"),
    "long id": lambda root: manifest_data(root, config_id="a" * 49),
    "payment field": lambda root: manifest_data(root, persona=_persona(payment={"card": "0000"})),
    "missing address": lambda root: manifest_data(
        root, persona={k: v for k, v in FAKE_PERSONA.items() if k != "address"}),
    "empty handle list": lambda root: manifest_data(
        root, persona=_persona(contacts={"Mom": []}), approved_recipients={"Mom": []}),
    "non-string handle": lambda root: manifest_data(
        root, persona=_persona(contacts={"Mom": [5550142]}), approved_recipients={"Mom": [5550142]}),
    "unapproved persona alias": lambda root: manifest_data(
        root, approved_recipients={"Mom": FAKE_PERSONA["contacts"]["Mom"]}),
    "unapproved persona handle": lambda root: manifest_data(
        root, approved_recipients={**FAKE_PERSONA["contacts"], "Mom": ["+1 555 0199"]}),
    "approved alias not in persona": lambda root: manifest_data(
        root, approved_recipients={**FAKE_PERSONA["contacts"], "Boss": ["boss@example.invalid"]}),
    "approved extra handle": lambda root: manifest_data(
        root, approved_recipients={**FAKE_PERSONA["contacts"], "Mom": ["+1 555 0142", "+1 555 0199"]}),
    "handle under two aliases": lambda root: manifest_data(
        root, persona=_persona(contacts={"Mom": ["+1 555 0142"], "Alex": ["+1 555 0142"]}),
        approved_recipients={"Mom": ["+1 555 0142"], "Alex": ["+1 555 0142"]}),
    "duplicate handle": lambda root: manifest_data(
        root, persona=_persona(contacts={"Mom": ["+1 555 0142", "+1 555 0142"]}),
        approved_recipients={"Mom": ["+1 555 0142", "+1 555 0142"]}),
    "case-duplicate alias": lambda root: manifest_data(
        root, persona=_persona(contacts={"Mom": ["+1 555 0142"], "mom": ["+1 555 0143"]}),
        approved_recipients={"Mom": ["+1 555 0142"], "mom": ["+1 555 0143"]}),
    "padded handle": lambda root: manifest_data(
        root, persona=_persona(contacts={"Mom": [" +1 555 0142"]}), approved_recipients={"Mom": [" +1 555 0142"]}),
    "control character": lambda root: manifest_data(
        root, persona=_persona(contacts={"Mom": ["+1 555\n0142"]}), approved_recipients={"Mom": ["+1 555\n0142"]}),
    "empty alias": lambda root: manifest_data(
        root, persona=_persona(contacts={"": ["+1 555 0142"]}), approved_recipients={"": ["+1 555 0142"]}),
    "relative data_dir": lambda root: manifest_data(root, data_dir="private-data"),
    "non-string cache_dir": lambda root: manifest_data(root, cache_dir=None),
    "data_dir in this checkout": lambda root: manifest_data(root, data_dir=str(demo_config.REPO_ROOT / ".private")),
    "cache_dir is the tracked cache": lambda root: manifest_data(
        root, cache_dir=str(demo_config.REPO_ROOT / "agent/replay/cache")),
    "cache_dir under the tracked cache": lambda root: manifest_data(
        root, cache_dir=str(demo_config.REPO_ROOT / "agent/replay/cache/private")),
    "data_dir in another work tree": lambda root: manifest_data(root, data_dir=str(root / "other-repo/data")),
    "cache_dir is another work tree": lambda root: manifest_data(root, cache_dir=str(root / "other-repo")),
    "same data and cache dir": lambda root: manifest_data(root, cache_dir=str(root / "private-data")),
    "cache nested in data": lambda root: manifest_data(root, cache_dir=str(root / "private-data/cache")),
    "data nested in cache": lambda root: manifest_data(root, data_dir=str(root / "private-cache/data")),
    "default user data dir": lambda root: manifest_data(root, data_dir=str(root / "default-user-data")),
    "inside default user data": lambda root: manifest_data(root, cache_dir=str(root / "default-user-data/cache")),
    "contains default user data": lambda root: manifest_data(root, data_dir=str(root)),
    "lexical escape into user data": lambda root: manifest_data(
        root, data_dir=str(root / "private-data/../default-user-data/x")),
    "filesystem root": lambda root: manifest_data(root, cache_dir="/"),
    "home directory": lambda root: manifest_data(root, data_dir=str(root / "home")),
}


@pytest.mark.parametrize("case", BAD_MANIFESTS)
def test_inconsistent_unapproved_or_unsafe_manifests_are_rejected(monkeypatch, tmp_path, case):
    (tmp_path / "other-repo").mkdir()
    (tmp_path / "other-repo/.git").write_text("gitdir: elsewhere\n")
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    with pytest.raises(DemoConfigError) as error:
        demo_config.parse_manifest(BAD_MANIFESTS[case](tmp_path))
    assert_sanitized(error.value, tmp_path)
    assert not (demo_config.REPO_ROOT / ".private").exists()


def test_symlink_into_the_checkout_is_rejected(tmp_path):
    (tmp_path / "link").symlink_to(demo_config.REPO_ROOT / "agent/replay", target_is_directory=True)
    with pytest.raises(DemoConfigError, match="outside every Git work tree"):
        demo_config.parse_manifest(manifest_data(tmp_path, cache_dir=str(tmp_path / "link/private")))


BAD_FILES = {
    "relative selector": lambda root, path: "private-manifest/demo.json",
    "missing file": lambda root, path: str(root / "absent.json"),
    "directory": lambda root, path: str(path.parent),
    "group writable": lambda root, path: (path.chmod(0o620), str(path))[1],
    "world writable": lambda root, path: (path.chmod(0o602), str(path))[1],
    "too large": lambda root, path: (path.write_text(" " * (demo_config.MAX_MANIFEST_BYTES + 1)), str(path))[1],
    "invalid JSON": lambda root, path: (path.write_text("{"), str(path))[1],
    "duplicate key": lambda root, path: (path.write_text(
        path.read_text()[:-1] + ', "config_id": "other"}'), str(path))[1],
    "non-finite number": lambda root, path: (path.write_text('{"format": NaN}'), str(path))[1],
    "inside a work tree": lambda root, path: str(write_manifest(root / "other-repo")),
    "inside data_dir": lambda root, path: str(write_manifest(
        root, data_dir=str(root / "private-manifest"))),
}


@pytest.mark.parametrize("case", BAD_FILES)
def test_manifest_file_must_be_private_valid_and_outside_work_trees(tmp_path, case):
    (tmp_path / "other-repo").mkdir()
    (tmp_path / "other-repo/.git").mkdir()
    path = write_manifest(tmp_path)
    selector = BAD_FILES[case](tmp_path, path)
    with pytest.raises(DemoConfigError) as error:
        demo_config.selected({demo_config.SELECTOR_ENV: selector, "DEMO_MODE": "1"})
    assert_sanitized(error.value, tmp_path)


def test_check_profile_allows_subsets_and_rejects_enlargement(tmp_path):
    config = demo_config.parse_manifest(manifest_data(tmp_path))
    config.check_profile(FAKE_PERSONA)
    config.check_profile({**FAKE_PERSONA, "contacts": {"Mom": ["+1 555 0142"]}})
    config.check_profile({**FAKE_PERSONA, "contacts": {}})
    for contacts in ({**FAKE_PERSONA["contacts"], "Boss": ["boss@example.invalid"]},
                     {**FAKE_PERSONA["contacts"], "Mom": ["+1 555 0142", "+1 555 0199"]},
                     {"Mother": ["+1 555 0142"]},
                     {"Mom": ["+1 555 0100"]}):
        with pytest.raises(DemoConfigError, match="not an approved recipient") as error:
            config.check_profile({**FAKE_PERSONA, "contacts": contacts})
        assert_sanitized(error.value, tmp_path)


def test_import_is_stdlib_only_and_reads_nothing(tmp_path):
    """The harness imports this parser without agent dependencies or side effects."""
    code = r"""
import json, sys
opened = []
def hook(event, args):
    if event == "open" and args and isinstance(args[0], str) and not args[0].endswith((".py", ".pyc")):
        opened.append(args[0])
sys.addaudithook(hook)
sys.path.insert(0, sys.argv[1])
from gaze_agent import demo_config
assert demo_config.selected() is None
heavy = sorted(m for m in sys.modules if m.split(".")[0] in {
    "pydantic", "openai", "jsonschema", "dotenv", "objc", "AppKit", "Quartz", "ApplicationServices",
    "Vision", "Foundation", "pyautogui", "websockets", "httpx", "httpx2"}
    or m in {"gaze_agent.profile", "gaze_agent.protocol", "gaze_agent.llm", "gaze_agent.contracts"})
print(json.dumps({"opened": opened, "heavy": heavy}))
"""
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "DEMO_MODE": "1"}
    # -S: no site-packages at all, so a third-party import would fail outright.
    result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", code, str(demo_config.REPO_ROOT / "agent")],
                            capture_output=True, text=True, env=env, timeout=30, check=True)
    assert json.loads(result.stdout) == {"opened": [], "heavy": []}
    assert not any(tmp_path.iterdir())
