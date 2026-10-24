---
name: task_system
model: agent
placeholders: [profile_summary, plan_label, plan_detail, screen]
---
STUB (Phase 0). Task C writes the real system prompt for the task tool loop (spec §8.2).
Rules, tool usage and the confirmation policy are static text here, not placeholders.

User profile:
{{profile_summary}}

Chosen plan: {{plan_label}}
{{plan_detail}}

Current screen:
{{screen}}
