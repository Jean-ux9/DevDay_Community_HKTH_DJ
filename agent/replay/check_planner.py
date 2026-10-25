"""Record/check planner prompts using only the demo fixture, without desktop access.

Run from the repository root with:
  uv run --project agent python agent/replay/check_planner.py record
  uv run --project agent python agent/replay/check_planner.py replay
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

from dotenv import load_dotenv

from gaze_agent import demo_config, llm, planner, profile
from gaze_agent.contracts import LLMError

EXPECTED = Path(__file__).with_name("planner_expected.json")


async def check(mode: str) -> dict:
    if os.environ.get(demo_config.SELECTOR_ENV):
        # Never mix private-persona state into the public synthetic recordings.
        raise LLMError(f"Synthetic checks use only the public fixture; unset {demo_config.SELECTOR_ENV}")
    demo = json.loads(llm.DEMO_PROFILE_PATH.read_text())
    # Both the planner input and recording guard see the same fixture. The
    # user's Application Support profile is never read or overwritten here.
    with patch.object(profile, "load_profile", return_value=demo):
        plans = await planner.make_plans("tickets for my favorite artist", demo, None)
        sentences = await planner.decode(["tell", "mom"], [["GHI", "ABC"]], None, demo)
    if not all("Taylor Swift" in p.label and "Ticketmaster" in p.label for p in plans[:-1]):
        raise LLMError("Favorite artist/site was not resolved in every plan")
    result = {"plans": [p.model_dump() for p in plans], "sentences": sentences}
    if mode == "record":
        EXPECTED.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    elif result != json.loads(EXPECTED.read_text()):
        raise LLMError("Replay differs from recorded planner output")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("record", "replay"))
    args = parser.parse_args()
    load_dotenv(llm.ROOT / ".env", override=False)
    if os.environ.pop(demo_config.SELECTOR_ENV, None):
        print(f"{demo_config.SELECTOR_ENV} ignored: these checks use only fixtures/demo_profile.json",
              file=sys.stderr)
    os.environ.update(REPLAY=args.mode, DEMO_MODE="1")
    if args.mode == "replay":
        os.environ.pop("OPENAI_API_KEY", None)
    try:
        # The API key is absent on replay, so any miss fails before HTTP.
        result = asyncio.run(check(args.mode))
    except (LLMError, OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"PASS planner {args.mode}" + (" (API key removed; no live fallback)" if args.mode == "replay" else ""))


if __name__ == "__main__":
    main()
