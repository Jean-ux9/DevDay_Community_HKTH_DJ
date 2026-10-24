# Protocol

`messages.schema.json` is the single source of truth for every WebSocket message between the overlay and the agent (JSON Schema draft 2020-12).

- Validate a message of type `T`: the envelope against `#/$defs/Envelope`, the payload against `#/$defs/payload_T`.
- `x-messages` maps each type to its direction: `o2a` (overlay → agent) or `a2o` (agent → overlay).
- Python models: `agent/gaze_agent/protocol.py` (kept in sync by `agent/tests/test_contract.py`). TypeScript types are generated from this file by the overlay (`pnpm gen:protocol`).

**Rules both sides must implement** (spec `.plans/gaze-copilot-spec.md`):
- **§4.1:** `re` correlation (always a message id), versioning, error codes.
- **§4.4:** task lifecycle and races: one task at a time, stop wins, disconnect = stop, `list_id` staleness.

These are where the overlay and the agent are most likely to diverge.

**Executable check:** `uv run scripts/fake_overlay.py demo --spawn` runs every flow against the mock agent. Point it at the real agent with `GAZE_TOKEN`/`GAZE_PORT` (without `--spawn`).

The protocol is **frozen**: a change needs one PR that updates this schema, `protocol.py`, both mocks (`scripts/fake_agent.py`, `scripts/gaze_client.py`) and the overlay.
