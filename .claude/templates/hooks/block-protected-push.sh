#!/usr/bin/env bash
# PreToolUse(Bash) guard — block direct `git push` to a protected branch.
# Portable, repo-agnostic version of `.claude/hooks/block-main-push.sh`: instead
# of hardcoding `main|master`, the protected list is configurable and the repo's
# default branch is auto-detected.
#
# Protected branches are resolved, in priority order:
#   1. $CLAUDE_PROTECTED_BRANCHES — space/comma-separated list (e.g. "main release").
#   2. The remote default branch (origin/HEAD), if detectable.
#   3. Fallback: "main master".
#
# Exit codes (Claude Code contract): 0 = allow, 2 = block (stderr shown to the
# agent as the reason). Any other non-zero is a non-blocking hook error.
set -uo pipefail

cmd=""
if command -v jq >/dev/null 2>&1; then
  cmd=$(jq -r '.tool_input.command // ""' 2>/dev/null || echo "")
fi

# Only inspect `git push` commands. Everything else passes straight through.
case "$cmd" in
  *"git push"*) ;;
  *) exit 0 ;;
esac

cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || true

# Resolve the protected-branch list.
branches="${CLAUDE_PROTECTED_BRANCHES:-}"
if [ -z "$branches" ]; then
  # Auto-detect the remote default branch (e.g. refs/remotes/origin/HEAD -> main).
  default_branch=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null \
    | sed 's@^origin/@@')
  [ -z "$default_branch" ] && default_branch=$(git config --get init.defaultBranch 2>/dev/null)
  branches="$default_branch main master"
fi

# Build a `branch1|branch2|...` alternation from the (comma/space) list, escaping
# regex metacharacters and de-duplicating empties.
alt=""
for b in $(printf '%s' "$branches" | tr ',' ' '); do
  [ -z "$b" ] && continue
  esc=$(printf '%s' "$b" | sed 's/[.[\*^$()+?{}|\\]/\\&/g')
  alt="${alt:+$alt|}$esc"
done
[ -z "$alt" ] && exit 0

# Block when the push refspec targets a protected branch as a whole word, e.g.
# `git push origin main`, `git push -u origin main`, `git push origin HEAD:main`.
if printf '%s' "$cmd" | grep -Eq "(^|[[:space:]:])($alt)([[:space:]]|\$)"; then
  echo "block-protected-push: direct pushes to a protected branch ($branches) are blocked." >&2
  echo "Push to a feature/integration branch and open a PR instead." >&2
  exit 2
fi

exit 0
