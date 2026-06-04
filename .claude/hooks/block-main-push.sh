#!/usr/bin/env bash
# PreToolUse(Bash) guard — block direct `git push` to main/master. Work lands on
# a flat-named integration/feature branch and reaches main via a PR (see the
# "Development workflow" + "Branching" sections in CLAUDE.md).
#
# Exit codes: 0 = allow, 2 = block (stderr shown to the agent).
set -uo pipefail

cmd=""
if command -v jq >/dev/null 2>&1; then
  cmd=$(jq -r '.tool_input.command // ""' 2>/dev/null || echo "")
fi

# Only inspect `git push` commands.
case "$cmd" in
  *"git push"*) ;;
  *) exit 0 ;;
esac

# Block when the push refspec targets main or master (as a whole word), e.g.
# `git push origin main`, `git push -u origin main`, `git push origin HEAD:main`.
if printf '%s' "$cmd" | grep -Eq '(^|[[:space:]:])(main|master)([[:space:]]|$)'; then
  echo "block-main-push: direct pushes to main/master are blocked." >&2
  echo "Push to a feature/integration branch and open a PR instead." >&2
  exit 2
fi

exit 0
