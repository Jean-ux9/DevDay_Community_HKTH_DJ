"""Responses API wrapper, strict prompt rendering and demo-only replay (§8.6)."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from gaze_agent.contracts import LLMError, LLMResponse, ModelSlot, ToolCall, PROMPT_VARS
from gaze_agent.tasklog import get_usage_meter


@dataclass(frozen=True)
class MeasuredResponse(LLMResponse):
    """Usage-bearing response without changing the frozen shared contract."""
    input_tokens: int | None = 0
    output_tokens: int | None = 0

ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = ROOT / "prompts"
CACHE_DIR = ROOT / "agent" / "replay" / "cache"
DEMO_PROFILE_PATH = ROOT / "fixtures" / "demo_profile.json"
_FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.S)
_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_ELEMENT_LINE = re.compile(r'(?m)^(?:focused: )?(\S+) \| ([^|\n]+) \| "(.*)" \| (?:enabled|disabled) \| \([^\n]*\)$')
_VOLATILE = {"id", "ts", "timestamp", "timestamps", "created_at", "bbox", "point", "coordinates", "x", "y", "w", "h"}


def _body(prompt: str) -> str:
    if prompt not in PROMPT_VARS:
        raise KeyError(f"Unknown prompt: {prompt}")
    return _FRONT_MATTER.sub("", (PROMPTS_DIR / f"{prompt}.md").read_text(), count=1)


def placeholders(prompt: str) -> set[str]:
    return set(_PLACEHOLDER.findall(_body(prompt)))


def render(prompt: str, vars: dict[str, Any]) -> str:
    body = _body(prompt)
    needed = set(_PLACEHOLDER.findall(body))
    missing, extra = needed - vars.keys(), vars.keys() - needed
    if missing or extra:
        raise KeyError(f"prompt {prompt!r}: missing {sorted(missing)}, extra {sorted(extra)}")
    return _PLACEHOLDER.sub(lambda m: str(vars[m.group(1)]), body)


def normalize(value: Any) -> Any:
    """Discard volatile transport/geometry data, preserving meaningful text."""
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        if {"role", "label", "bbox"} <= value.keys():
            return {"role": value["role"], "label": value["label"]}
        return {k: normalize(v) for k, v in sorted(value.items())
                if k not in _VOLATILE and not k.endswith("_id")}
    if isinstance(value, (list, tuple)):
        return [normalize(v) for v in value]
    if isinstance(value, str):
        # Tool outputs and function arguments often carry JSON inside strings.
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            return normalize(parsed)
        value = re.sub(r"(?m)^snapshot \S+ \|", "snapshot |", value)
        return _ELEMENT_LINE.sub(lambda m: ("focused: " if m.group(0).startswith("focused: ") else "")
                                 + f'{m.group(2).strip()} | "{m.group(3)}"', value)
    return value


def cache_key(prompt: str, model: str, vars: dict[str, Any], *, tools=None,
              input_items=None, image_jpeg: bytes | None = None) -> str:
    data = {"version": 1, "prompt": prompt, "template": _body(prompt), "model": model,
            "vars": vars, "tools": tools, "input": input_items,
            "image": hashlib.sha256(image_jpeg).hexdigest() if image_jpeg is not None else None}
    encoded = json.dumps(normalize(data), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _bindings(vars: dict[str, Any]) -> tuple[str | None, dict[str, list[str]]]:
    screen = str(vars.get("screen", ""))
    snapshot = re.search(r"(?m)^snapshot (\S+) \|", screen)
    return (snapshot.group(1) if snapshot else None,
            {m.group(1): [m.group(2).strip(), m.group(3)] for m in _ELEMENT_LINE.finditer(screen)})


def _read_cache(path: Path, vars: dict[str, Any]) -> LLMResponse:
    try:
        data = json.loads(path.read_text())
        snapshot, current = _bindings(vars)
        old = data.get("bindings", {})
        calls = []
        for item in data["response"]["tool_calls"]:
            args = dict(item["args"])
            if "id" in args or "snapshot_id" in args:
                if not snapshot:
                    raise ValueError("Replay has no current snapshot")
                if "id" in args:
                    matches = [id for id, sig in current.items() if sig == old.get(args["id"])]
                    if len(matches) != 1:
                        raise ValueError("Replay target is missing or ambiguous")
                    args["id"] = matches[0]
                if "snapshot_id" in args:
                    args["snapshot_id"] = snapshot
            calls.append(ToolCall(item["call_id"], item["name"], args))
        response = data["response"]
        return MeasuredResponse(response["text"], calls, response["response_id"], True)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise LLMError("Invalid or incompatible replay entry") from exc


def _verify_recording_profile(prompt: str, vars: dict[str, Any]) -> None:
    if os.getenv("DEMO_MODE") != "1":
        raise LLMError("Recording requires DEMO_MODE=1 and the demo profile")
    try:
        from gaze_agent.profile import load_profile, profile_summary
        demo = json.loads(DEMO_PROFILE_PATH.read_text())
        if load_profile() != demo:
            raise ValueError("Active profile differs from demo fixture")
        if "profile_summary" in vars and vars["profile_summary"] not in {
            profile_summary(demo), profile_summary(demo, include_address=True)
        }:
            raise ValueError("Prompt profile differs from demo fixture")
        if prompt == "sentence_decode" and json.loads(str(vars["profile_style"])) != demo["style"]:
            raise ValueError("Prompt style differs from demo fixture")
    except (OSError, ValueError, KeyError) as exc:
        raise LLMError("Recording requires the active fixtures/demo_profile.json persona") from exc


def _write_cache(path: Path, response: LLMResponse, vars: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"response": asdict(response), "bindings": _bindings(vars)[1]}
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, suffix=".tmp") as f:
            name = f.name
            json.dump(data, f, ensure_ascii=False, sort_keys=True)
            f.write("\n")
        os.replace(name, path)
    finally:
        if name:
            Path(name).unlink(missing_ok=True)


async def _live(model: str, body: str, *, tools, input_items, image_jpeg, on_usage=None) -> LLMResponse:
    items = list(input_items or [])
    if image_jpeg is not None:
        items.append({"role": "user", "content": [{"type": "input_image", "image_url":
                      "data:image/jpeg;base64," + base64.b64encode(image_jpeg).decode()}]})
    if not items:
        items = [{"role": "user", "content": body}]
    # A client per call ensures cancelling also closes the active HTTP transport.
    async with AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"], max_retries=0, timeout=60.0) as client:
        kwargs = {"model": model, "instructions": body, "input": items, "store": False}
        if tools is not None:
            kwargs.update(tools=tools, parallel_tool_calls=False)
        response = await client.responses.create(**kwargs)
    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    if on_usage:
        on_usage(input_tokens, output_tokens)
    if getattr(response, "status", "completed") != "completed":
        raise LLMError("OpenAI returned an incomplete response")
    calls = []
    for item in response.output:
        if item.type == "function_call":
            args = json.loads(item.arguments)
            if not isinstance(args, dict):
                raise LLMError("Function arguments must be a JSON object")
            calls.append(ToolCall(item.call_id, item.name, args))
    if not response.output_text and not calls:
        raise LLMError("OpenAI returned no text or function calls")
    return MeasuredResponse(response.output_text or None, calls, response.id, False, input_tokens, output_tokens)


async def complete(prompt: str, model: ModelSlot, vars: dict[str, Any], *,
                   tools: list[dict[str, Any]] | None = None,
                   input_items: list[dict[str, Any]] | None = None,
                   image_jpeg: bytes | None = None) -> LLMResponse:
    try:
        body = render(prompt, vars)
        if model not in {"agent", "fast", "vision"}:
            raise LLMError("Unknown model slot")
        model_id = os.getenv(f"OPENAI_MODEL_{model.upper()}")
        if not model_id:
            raise LLMError(f"OPENAI_MODEL_{model.upper()} is not configured")
        mode = os.getenv("REPLAY", "off")
        if mode not in {"off", "record", "replay"}:
            raise LLMError("REPLAY must be off, record, or replay")
        path = CACHE_DIR / (cache_key(prompt, model_id, vars, tools=tools,
                                     input_items=input_items, image_jpeg=image_jpeg) + ".json")
        if mode == "replay" and path.is_file():
            return _read_cache(path, vars)
        if mode == "record":
            _verify_recording_profile(prompt, vars)
        if not os.getenv("OPENAI_API_KEY"):
            raise LLMError("Replay miss or live call without OPENAI_API_KEY")
        meter = get_usage_meter()
        tokens = (None, None)
        def on_usage(input_tokens, output_tokens):
            nonlocal tokens
            tokens = (input_tokens, output_tokens)
        try:
            response = await _live(model_id, body, tools=tools, input_items=input_items,
                                   image_jpeg=image_jpeg, on_usage=on_usage)
            tokens = (getattr(response, "input_tokens", tokens[0]),
                      getattr(response, "output_tokens", tokens[1]))
        finally:
            # Also count failed/cancelled attempts; known usage survives parse errors.
            meter.record(prompt, model, *tokens)
        if mode == "record":
            _write_cache(path, response, vars)
        return response
    except asyncio.CancelledError:
        raise
    except LLMError:
        raise
    except Exception as exc:
        # API exceptions can contain request bodies; do not propagate those to UI/logs.
        raise LLMError(f"LLM call failed ({type(exc).__name__})") from exc
