"""Prompts and their callers must agree on placeholders (Phase 0 §5).

contracts.PROMPT_VARS is what callers pass; each prompts/*.md must use exactly those
placeholders and list them in its front matter.
"""
import re

import pytest

from gaze_agent import llm
from gaze_agent.contracts import PROMPT_VARS


def test_no_unlisted_prompt_files():
    assert {p.stem for p in llm.PROMPTS_DIR.glob("*.md")} == set(PROMPT_VARS)


@pytest.mark.parametrize("name", sorted(PROMPT_VARS))
def test_placeholders_match_callers(name):
    text = (llm.PROMPTS_DIR / f"{name}.md").read_text()
    listed = re.search(r"^placeholders:\s*\[(.*)\]\s*$", text, re.M)
    assert listed, f"{name}.md has no `placeholders: [...]` front matter"
    assert {s.strip() for s in listed.group(1).split(",") if s.strip()} == PROMPT_VARS[name]
    assert llm.placeholders(name) == PROMPT_VARS[name]


@pytest.mark.parametrize("name", sorted(PROMPT_VARS))
def test_render(name):
    out = llm.render(name, {v: f"<{v}>" for v in PROMPT_VARS[name]})
    assert "{{" not in out and "placeholders:" not in out
    with pytest.raises(KeyError):
        llm.render(name, {})
    with pytest.raises(KeyError):
        llm.render(name, {v: "" for v in PROMPT_VARS[name]} | {"unexpected": ""})
