#!/usr/bin/env bash
# PreToolUse(Bash) quality gate — block `git commit` unless ruff/black/pytest
# pass. Mirrors `.pre-commit-config.yaml` so the gate holds even when
# `pre-commit install` hasn't been run. The hook receives the tool-call JSON
# on stdin; we only act on commands that invoke `git commit`.
#
# Exit codes (Claude Code contract): 0 = allow, 2 = block (stderr shown to the
# agent as the reason). Any other non-zero is a non-blocking hook error.
set -uo pipefail

cmd=""
if command -v jq >/dev/null 2>&1; then
  cmd=$(jq -r '.tool_input.command // ""' 2>/dev/null || echo "")
fi

# Only police `git commit`. Everything else passes straight through.
case "$cmd" in
  *"git commit"*) ;;
  *) exit 0 ;;
esac

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

block() {
  echo "quality-gates: blocking commit — $1" >&2
  echo "Fix the above, then re-run the commit. (Gate mirrors .pre-commit-config.yaml.)" >&2
  exit 2
}

# Each tool is enforced only when present, so commits aren't bricked in a
# deps-less environment; when the tool exists, a failure blocks the commit.
if command -v ruff >/dev/null 2>&1; then
  ruff check src tests >&2 || block "ruff check failed"
else
  echo "quality-gates: ruff not found — skipping lint gate" >&2
fi

if command -v black >/dev/null 2>&1; then
  black --check src tests >&2 || block "black --check failed (run: black src tests)"
else
  echo "quality-gates: black not found — skipping format gate" >&2
fi

if command -v python >/dev/null 2>&1; then
  python -m pytest -q >&2 || block "pytest failed"
else
  echo "quality-gates: python not found — skipping test gate" >&2
fi

exit 0
