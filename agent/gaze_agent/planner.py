"""Intent planning and one-call T9 sentence decode (§8.5, §6.3). No desktop IO."""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from typing import Any
from urllib.parse import urlsplit

from gaze_agent import llm
from gaze_agent.contracts import LLMError, Snapshot
from gaze_agent.profile import profile_summary
from gaze_agent.protocol import Plan
from gaze_agent.safety import classify

OTHER = Plan(id="other", label="Something else", kind="other", risky=False)


def json_items(text: str | None, name: str) -> list:
    try:
        value = json.loads(text or "")
        if isinstance(value, dict):
            value = value[name]
        if not isinstance(value, list):
            raise ValueError("Expected a JSON array")
        return value
    except (ValueError, KeyError, TypeError) as exc:
        raise LLMError(f"Invalid {name} response") from exc


def parse_plans(text: str | None, *, minimum: int = 2, maximum: int = 4) -> list[Plan]:
    items = json_items(text, "plans")
    tasks = []
    try:
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Invalid plan")
            if item.get("kind") == "other" or item.get("id") == "other":
                continue
            if item.get("kind", "task") != "task":
                raise ValueError("Unexpected plan kind")
            label = item["label"]
            detail = item.get("detail")
            if not isinstance(label, str) or not label.strip() or (detail is not None and not isinstance(detail, str)):
                raise ValueError("Invalid plan text")
            risky = item.get("risky", False)
            if not isinstance(risky, bool):
                raise ValueError("Invalid risk hint")
            label = " ".join(label.split())
            tasks.append(Plan(id=f"p{len(tasks) + 1}", label=label[:39] + "…" if len(label) > 40 else label,
                              detail=detail, kind="task", risky=risky or classify(label + " " + (detail or "")) is not None))
        if not minimum <= len(tasks) <= maximum:
            raise ValueError("Unexpected plan count")
    except (ValueError, TypeError, KeyError) as exc:
        raise LLMError("Invalid plans response") from exc
    return tasks


def _resolve_labels(plans: list[Plan], intent: str, profile: dict[str, Any]) -> list[Plan]:
    favorites = profile.get("favorites", {})
    artist = favorites.get("artist", "")
    playlist = favorites.get("playlist", "")
    sites = favorites.get("sites", [])
    for index, plan in enumerate(plans):
        label = plan.label
        for pattern, replacement in ((r"my (?:favorite )?artist", artist),
                                     (r"my (?:favorite |focus )?playlist", playlist)):
            if replacement:
                label = re.sub(pattern, lambda _: replacement, label, flags=re.I)
        if re.search(r"favorite artist", intent, re.I) and artist:
            if sites:
                host = urlsplit(sites[0] if "://" in sites[0] else "https://" + sites[0]).hostname or sites[0]
                site = host.removeprefix("www.").split(".")[0]
                site = {"ticketmaster": "Ticketmaster", "eventbrite": "Eventbrite"}.get(site, site)
                if artist.lower() not in label.lower() or site.lower() not in label.lower():
                    label = f"{('Find', 'Browse', 'Search', 'View')[index]} {artist} on {site}"
            elif artist.lower() not in label.lower():
                label = f"Find {artist} tickets"
        if len(label) > 40:
            # Do not silently cut a resolved artist/site out of a visible plan.
            raise LLMError("Resolved plan label exceeds 40 characters")
        plans[index] = plan.model_copy(update={"label": label})
    return plans


async def make_plans(text: str, profile: dict[str, Any], snapshot: Snapshot | None) -> list[Plan]:
    if not text.strip():
        raise LLMError("Intent is empty")
    response = await llm.complete("plan_intent", "fast", {
        "profile_summary": profile_summary(profile), "intent": text,
        "app_context": snapshot.to_prompt() if snapshot else "",
    })
    plans = _resolve_labels(parse_plans(response.text), text, profile)
    return plans + [OTHER.model_copy()]


async def decode(words: list[str], raw_keys: list[list[str]], context: str | None,
                 profile: dict[str, Any]) -> list[str]:
    response = await llm.complete("sentence_decode", "fast", {
        "profile_style": json.dumps(profile.get("style", {}), ensure_ascii=False, sort_keys=True),
        "words": json.dumps(words, ensure_ascii=False), "raw_keys": json.dumps(raw_keys),
        "context": context or "",
    })
    variants = json_items(response.text, "sentences")
    if not 1 <= len(variants) <= 3 or any(not isinstance(s, str) or not s.strip() for s in variants):
        raise LLMError("Invalid sentences response")
    result = []
    if words and not raw_keys:
        result.append(" ".join(words))
    for sentence in variants:
        sentence = sentence.strip()
        if sentence not in result:
            result.append(sentence)
    return result[:3]


async def _main(args: argparse.Namespace) -> None:
    from gaze_agent.profile import load_profile
    profile = load_profile()
    if args.command == "intent":
        output = [p.model_dump() for p in await make_plans(args.text, profile, None)]
    else:
        groups = [group.split(",") for group in args.raw]
        output = await decode(args.words, groups, args.context, profile)
    print(json.dumps(output, ensure_ascii=False, indent=2))


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv(llm.ROOT / ".env", override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    intent = commands.add_parser("intent")
    intent.add_argument("text")
    decode_parser = commands.add_parser("decode")
    decode_parser.add_argument("--words", nargs="*", default=[])
    decode_parser.add_argument("--raw", nargs="*", default=[])
    decode_parser.add_argument("--context")
    args = parser.parse_args()
    try:
        asyncio.run(_main(args))
    except LLMError as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
