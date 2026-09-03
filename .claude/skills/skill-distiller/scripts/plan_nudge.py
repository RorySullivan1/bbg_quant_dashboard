#!/usr/bin/env python3
"""Emit a PostToolUse additionalContext nudge after a plan is approved.

Wired to ExitPlanMode via the post-tool-use-plan-nudge fragment. Reads the hook JSON on
stdin (unused here; the model already has the plan in context) and prints a factual
nudge. Phrased as a statement of fact + an available capability, not an imperative
command, so it doesn't trip prompt-injection defenses.
"""
import json
import sys

sys.stdin.read()  # drain stdin; the plan is already in the model's context

nudge = (
    "A plan was just approved. If it captures a reusable, generalizable procedure worth "
    "repeating, the skill-distiller skill can assess whether to save it as a new skill or "
    "fold it into an existing one. Skip this for one-off or trivial plans."
)

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": nudge,
    }
}))
