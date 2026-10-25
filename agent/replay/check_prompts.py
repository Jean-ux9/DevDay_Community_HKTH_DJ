"""Live/replay prompt checks against synthetic demo screens; tools never execute."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from unittest.mock import patch

import jsonschema
from dotenv import load_dotenv

from gaze_agent import llm, planner, profile, safety
from gaze_agent.contracts import Element, LLMError, ProposedAction, Snapshot
from gaze_agent.loop import TOOLS

DIRECTORY = Path(__file__).resolve().parent
EXPECTED = DIRECTORY / "prompts_expected.json"


def screens() -> dict[str, Snapshot]:
    result = {}
    for name, data in json.loads((DIRECTORY / "demo_screens.json").read_text()).items():
        elements = [Element(**element) for element in data["elements"]]
        focused = next((e for e in elements if e.id == data["focused"]), None)
        result[name] = Snapshot(**{**data, "elements": elements, "focused": focused})
    return result


async def check(mode: str) -> dict:
    demo = json.loads(llm.DEMO_PROFILE_PATH.read_text())
    screen = screens()
    summary = profile.profile_summary(demo)
    with patch.object(profile, "load_profile", return_value=demo):
        response = await llm.complete("auto_suggest", "fast", {
            "profile_summary": summary, "app": screen["mail"].app,
            "window_title": screen["mail"].window_title, "screen": screen["mail"].to_prompt(),
        })
        suggestions = planner.parse_plans(response.text, minimum=3, maximum=4)
        vars = {"profile_summary": summary, "plan_label": "Tell Mom I'll be late",
                "plan_detail": "Send the existing draft to Mom.", "screen": screen["messages"].to_prompt()}
        response = await llm.complete("task_system", "agent", vars, tools=TOOLS, input_items=[])
        if len(response.tool_calls) != 1:
            raise LLMError("Expected one proposed tool call")
        call = response.tool_calls[0]
        if call.name != "click_element" or call.args.get("id") != "e2":
            raise LLMError("Expected a proposed click on the observed Send button")
        schema = next(tool["parameters"] for tool in TOOLS if tool["name"] == call.name)
        jsonschema.validate(call.args, schema)
        if call.args.get("snapshot_id") != screen["messages"].snapshot_id:
            raise LLMError("Task prompt used a stale snapshot")
        if call.args.get("requires_confirmation") is not True:
            raise LLMError("Task prompt omitted the irreversible-action flag")
        gate = safety.gate(ProposedAction("click_element", element=screen["messages"].elements[1],
                           model_flag=True, model_reason=call.args.get("confirmation_reason")), screen["messages"])
        if not gate.required or gate.action != "send" or gate.source != "both":
            raise LLMError("Expected both rule and model confirmation")
        history = [{"type": "function_call", "call_id": call.call_id, "name": call.name,
                    "arguments": json.dumps(call.args)},
                   {"type": "function_call_output", "call_id": call.call_id,
                    "output": json.dumps({"ok": False, "error": "user cancelled", "screen": vars["screen"]})}]
        cancelled = await llm.complete("task_system", "agent", vars, tools=TOOLS, input_items=history)
        if len(cancelled.tool_calls) != 1 or cancelled.tool_calls[0].name != "finish":
            raise LLMError("Task prompt did not finish after cancellation")
        jsonschema.validate(cancelled.tool_calls[0].args, next(t["parameters"] for t in TOOLS if t["name"] == "finish"))
    result = {"suggestions": [p.model_dump() for p in suggestions],
              "proposed_send": {"tool": call.name, "args": call.args},
              "after_cancel": cancelled.tool_calls[0].args}
    if mode == "record":
        EXPECTED.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    elif result != json.loads(EXPECTED.read_text()):
        raise LLMError("Replay differs from recorded prompt output")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("record", "replay"))
    args = parser.parse_args()
    load_dotenv(llm.ROOT / ".env", override=False)
    os.environ.update(REPLAY=args.mode, DEMO_MODE="1")
    if args.mode == "replay":
        os.environ.pop("OPENAI_API_KEY", None)
    try:
        result = asyncio.run(check(args.mode))
    except (LLMError, OSError, ValueError, jsonschema.ValidationError) as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"PASS synthetic prompts {args.mode}; no tools executed")


if __name__ == "__main__":
    main()
