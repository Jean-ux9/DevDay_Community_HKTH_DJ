"""HUMAN-RUN, opt-in live OpenAI smoke check with synthetic input and no desktop.

Sends four uncached OPENAI_MODEL_FAST requests through the existing llm.complete
wrapper with REPLAY=off: intent planning, T9 sentence decoding, and Auto
suggestions for a synthetic English and a synthetic German Mail screen. Inputs
are the public fake persona (fixtures/demo_profile.json) and synthetic screens.
It never captures or reads the screen, loads the active profile, reads or writes
a replay cache, or runs a desktop action. A pass shows real API responses with
usage and valid output; a human still judges the English wording.

Without --live it only prints a notice: no .env read and no API call. Run from
the repository root after Stage 1 configuration passes (this spends credits):

  uv run --project agent python agent/replay/check_live_api.py --live
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import jsonschema
from dotenv import load_dotenv

from gaze_agent import demo_config, llm, planner, profile
from gaze_agent.contracts import Element, LLMError, Snapshot
from gaze_agent.tasklog import get_usage_meter

SCHEMA = json.loads((llm.ROOT / "protocol/messages.schema.json").read_text())
INTENT = "tickets for my favorite artist"
# T9 commits "ill" (the word list has no apostrophes) and leaves "late" unfinished.
WORDS, RAW_KEYS = ["tell", "mom", "ill", "be"], [["JKL", "ABC", "TUV", "DEF"]]
PROMPTS = ["plan_intent", "sentence_decode", "auto_suggest", "auto_suggest"]
# Synthetic localized screen: English suggestions must keep these native labels.
GERMAN_MAIL = {
    "snapshot_id": "synthetic-mail-de", "app": "Mail", "bundle_id": "com.apple.mail",
    "window_title": "Mittagessen am Freitag?", "url": None, "focused": None,
    "elements": [
        {"id": "e1", "role": "AXStaticText", "label": "Von: Alex <alex@example.com>",
         "description": "", "enabled": True, "bbox": [0, 0, 200, 20], "source": "ax"},
        {"id": "e2", "role": "AXStaticText", "label": "Passt dir 12 Uhr am Freitag zum Mittagessen?",
         "description": "", "enabled": True, "bbox": [0, 30, 300, 20], "source": "ax"},
        {"id": "e3", "role": "AXButton", "label": "Antworten",
         "description": "", "enabled": True, "bbox": [0, 60, 80, 20], "source": "ax"},
    ],
}


def _snapshot(data: dict) -> Snapshot:
    elements = [Element(**{**element, "bbox": tuple(element["bbox"])}) for element in data["elements"]]
    focused = next((e for e in elements if e.id == data["focused"]), None)
    return Snapshot(**{**data, "elements": elements, "focused": focused})


def screens() -> dict[str, Snapshot]:
    english = json.loads((Path(__file__).resolve().parent / "demo_screens.json").read_text())["mail"]
    return {"mail_en": _snapshot(english), "mail_de": _snapshot(GERMAN_MAIL)}


def _validate(name: str, payload: dict) -> None:
    try:
        jsonschema.Draft202012Validator({"$defs": SCHEMA["$defs"], "$ref": f"#/$defs/{name}"}).validate(payload)
    except jsonschema.ValidationError as exc:
        raise LLMError(f"{name} does not match the protocol schema: {exc.message}") from exc


def _no_active_profile():
    raise LLMError("The live check must not load the active profile")


def _usage_rows(responses: list, before: dict, after: dict) -> list[dict]:
    """Require a live, uncached response with token usage that the meter counted."""
    if [prompt for prompt, _ in responses] != PROMPTS:
        raise LLMError("Unexpected live request sequence")
    rows = []
    for prompt, response in responses:
        tokens = (getattr(response, "input_tokens", None), getattr(response, "output_tokens", None))
        if response.cached:
            raise LLMError(f"{prompt}: served from a replay cache, not a live request")
        if not response.response_id:
            raise LLMError(f"{prompt}: the API returned no response id")
        if not all(isinstance(count, int) and count > 0 for count in tokens):
            raise LLMError(f"{prompt}: the API reported no token usage")
        rows.append({"prompt": prompt, "cached": False, "response_id": response.response_id[:12] + "…",
                     "input_tokens": tokens[0], "output_tokens": tokens[1]})
    for prompt in set(PROMPTS):
        old, new = before.get(prompt, {}), after.get(prompt, {})
        mine = [row for row in rows if row["prompt"] == prompt]
        if any(new.get(field, 0) - old.get(field, 0) != expected for field, expected in (
                ("calls", len(mine)), ("input_tokens", sum(row["input_tokens"] for row in mine)),
                ("output_tokens", sum(row["output_tokens"] for row in mine)))):
            raise LLMError(f"{prompt}: the usage meter does not match the live responses")
    return rows


async def check() -> dict:
    """Make the four live requests and validate them; raise LLMError on any failure."""
    if os.getenv("REPLAY", "off") != "off":
        raise LLMError("The live check requires REPLAY=off")
    persona = json.loads(llm.DEMO_PROFILE_PATH.read_text())
    meter = get_usage_meter()
    before = meter.summary()["prompts"]
    responses = []
    complete = llm.complete

    async def measured(prompt, model, vars, **kwargs):
        response = await complete(prompt, model, vars, **kwargs)
        responses.append((prompt, response))
        return response

    suggestions = {}
    with patch.object(llm, "complete", measured), patch.object(profile, "load_profile", _no_active_profile):
        plans = await planner.make_plans(INTENT, persona, None)
        sentences = await planner.decode(WORDS, RAW_KEYS, None, persona)
        for name, screen in screens().items():
            # The same prompt variables and parser as AutoWatcher, minus the desktop.
            response = await llm.complete("auto_suggest", "fast", {
                "profile_summary": profile.profile_summary(persona), "app": screen.app,
                "window_title": screen.window_title, "screen": screen.to_prompt(),
            })
            suggestions[name] = planner.parse_plans(response.text, minimum=3, maximum=4)
    _validate("payload_plans", {"list_id": "live-check", "items": [p.model_dump() for p in plans]})
    _validate("payload_decode_result", {"sentences": sentences})
    for name, items in suggestions.items():
        _validate("payload_suggestions", {"list_id": "live-check", "window_key": name, "app": "Mail",
                                          "items": [p.model_dump() for p in items], "cached": False})
    return {"model": os.getenv("OPENAI_MODEL_FAST"),
            "effort": os.getenv("OPENAI_REASONING_EFFORT_FAST") or "API default",
            "calls": _usage_rows(responses, before, meter.summary()["prompts"]),
            "plans": [p.model_dump() for p in plans], "sentences": sentences,
            "suggestions": {name: [p.model_dump() for p in items] for name, items in suggestions.items()}}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true",
                        help="make four real, billed OpenAI requests (human-run only)")
    args = parser.parse_args(argv)
    if not args.live:
        parser.exit(2, "NOT RUN: no API call was made and .env was not read. Pass --live to run it.\n")
    load_dotenv(llm.ROOT / ".env", override=False)
    if os.environ.pop(demo_config.SELECTOR_ENV, None):
        print(f"{demo_config.SELECTOR_ENV} ignored: this check uses only the public synthetic persona",
              file=sys.stderr)
    if os.environ.get("REPLAY", "off") != "off":
        print("REPLAY set to off for this check: every request must be live and uncached", file=sys.stderr)
    os.environ["REPLAY"] = "off"
    if not os.environ.get("OPENAI_API_KEY"):
        parser.exit(1, "SETUP FAILURE: OPENAI_API_KEY is not set in the shell or .env; no request was made\n")
    print(f"Making {len(PROMPTS)} live OPENAI_MODEL_FAST requests with synthetic input; "
          "no screen, profile, cache or desktop access", file=sys.stderr)
    try:
        result = asyncio.run(check())
    except (LLMError, OSError, ValueError) as exc:
        parser.exit(1, f"FAIL: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"PASS live API check: {len(result['calls'])} uncached requests with usage and valid output. "
          "Review the English wording above; desktop behavior is not tested.")


if __name__ == "__main__":
    main()
