"""Script tests use the backend guard even when collected without agent/tests."""
import os
from pathlib import Path
import runpy
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "scripts"))

# Avoid the ambiguous `tests.conftest` name when scripts/tests is collected alone.
isolate_private_storage_and_live_api = runpy.run_path(
    str(ROOT / "agent/tests/conftest.py"))["isolate_private_storage_and_live_api"]
prohibit_real_desktop = runpy.run_path(
    str(ROOT / "agent/tests/runtime/conftest.py"))["prohibit_real_desktop"]

import rehearse  # noqa: E402
from gaze_client import GazeClient  # noqa: E402


def install_script_guards(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Script tests must inject fake desktop preparation and transport")

    monkeypatch.setattr(rehearse, "activate_app", forbidden)
    monkeypatch.setattr(rehearse, "prepare_app", forbidden)
    monkeypatch.setattr(GazeClient, "connect", forbidden)
    original_target = rehearse.target_server

    def fake_target_only(target, *args, **kwargs):
        if target != "fake":
            raise AssertionError("Script tests must never start the real agent")
        return original_target(target, *args, **kwargs)

    monkeypatch.setattr(rehearse, "target_server", fake_target_only)


@pytest.fixture(autouse=True)
def isolate_script_entry_points(monkeypatch, request):
    # With rootdir=agent, pytest gives this out-of-root conftest global fixture
    # visibility. Backend integration tests use their own fake loopback server.
    if request.node.path.is_relative_to(Path(__file__).parent):
        install_script_guards(monkeypatch)


@pytest.fixture
def isolated_python(tmp_path):
    """Run Python with child-installed guards, no inherited credentials/config.

    This is not a sandbox for arbitrary code. Use it for synthetic helper tests;
    do not launch production native commands or rely on a parent's monkeypatch.
    """
    def run(source):
        child_root = tmp_path / "child"
        child_root.mkdir(exist_ok=True)
        bootstrap = f"""
import runpy
import sys
from pathlib import Path
import pytest
sys.path[:0] = [{str(ROOT / 'agent')!r}, {str(ROOT / 'scripts')!r}]
guards = runpy.run_path({str(ROOT / 'agent/tests/conftest.py')!r})
scripts = runpy.run_path({str(Path(__file__).resolve())!r})
with pytest.MonkeyPatch.context() as patch:
    root = Path({str(child_root)!r})
    guards['install_test_isolation'](patch, root, root)
    scripts['install_script_guards'](patch)
    # The reused desktop fixture is installed explicitly in this interpreter.
    scripts['prohibit_real_desktop'].__wrapped__(patch)
    exec({source!r}, {{'__name__': '__main__'}})
"""
        return subprocess.run(
            [sys.executable, "-I", "-c", bootstrap], cwd=child_root,
            env={"PATH": os.defpath, "PYTHON_DOTENV_DISABLED": "1", "UV_NO_ENV_FILE": "1"},
            capture_output=True, text=True, timeout=20, check=False,
        )
    return run
