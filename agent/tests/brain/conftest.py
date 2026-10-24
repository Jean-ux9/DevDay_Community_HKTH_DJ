"""Task C uses Task D's fake persona; no macOS capabilities are imported."""
import copy
import sys
from pathlib import Path

import pytest

from gaze_agent.contracts import Element, Snapshot

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from fake_agent import DEMO_PROFILE  # noqa: E402


@pytest.fixture
def persona():
    return copy.deepcopy(DEMO_PROFILE)


@pytest.fixture
def snap():
    field = Element("e1", "AXTextField", "Message", "Compose", True, (1, 2, 3, 4), "ax")
    return Snapshot("s1", "Messages", "com.apple.MobileSMS", "Mom", None, field, [field])


@pytest.fixture(autouse=True)
def isolated_llm_environment(monkeypatch, tmp_path):
    from gaze_agent import llm
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setenv("REPLAY", "off")
    monkeypatch.setenv("DEMO_MODE", "0")
    monkeypatch.setenv("OPENAI_MODEL_FAST", "fake-fast")
    monkeypatch.setenv("OPENAI_MODEL_AGENT", "fake-agent")
    monkeypatch.setenv("OPENAI_MODEL_VISION", "fake-vision")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
