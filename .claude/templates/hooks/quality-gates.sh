#!/usr/bin/env bash
# PreToolUse(Bash) quality gate — block `git commit` unless the project's
# configured gates pass. Portable, repo-agnostic version of
# `.claude/hooks/quality-gates.sh`: the gate list and the paths they scan are
# configurable instead of hardcoding `ruff/black/pytest` over `src tests`.
#
# Configuration (all optional; sensible defaults below):
#   - Source `.claude/hooks/quality-gates.conf` if present to override:
#       QG_GATES — newline-separated "label|binary|command" entries.
#       QG_PATHS — space-separated paths the {paths} placeholder expands to.
#     (See quality-gates.conf.example.)
#   - Each gate command may contain the literal token `{paths}`, which is
#     replaced by the *existing* members of QG_PATHS (missing paths are dropped,
#     so a repo without e.g. a tests/ dir doesn't error out).
#   - A gate is enforced only when its `binary` is on PATH; otherwise it is
#     skipped (commits aren't bricked in a deps-less environment). When the
#     binary exists, a non-zero exit blocks the commit.
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

# Defaults — match a typical ruff/black/pytest Python layout. Override in
# quality-gates.conf to retarget the gate at any toolchain.
QG_PATHS="${QG_PATHS:-src tests}"
QG_GATES="${QG_GATES:-$(cat <<'EOF'
lint|ruff|ruff check {paths}
format|black|black --check {paths}
tests|python|python -m pytest -q
EOF
)}"

# Layer in a project config if present (can set QG_GATES / QG_PATHS).
conf="${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/quality-gates.conf"
# shellcheck disable=SC1090
[ -f "$conf" ] && . "$conf"

# Keep only the QG_PATHS that actually exist, so a gate over a missing dir is a
# no-op rather than a hard error.
existing_paths=""
for p in $QG_PATHS; do
  [ -e "$p" ] && existing_paths="${existing_paths:+$existing_paths }$p"
done

block() {
  echo "quality-gates: blocking commit — $1" >&2
  echo "Fix the above, then re-run the commit." >&2
  exit 2
}

# Run each configured gate.
printf '%s\n' "$QG_GATES" | while IFS='|' read -r label binary command; do
  [ -z "${label// }" ] && continue
  command=${command//\{paths\}/$existing_paths}
  if ! command -v "$binary" >/dev/null 2>&1; then
    echo "quality-gates: $binary not found — skipping $label gate" >&2
    continue
  fi
  if ! eval "$command" >&2; then
    block "$label gate failed ($command)"
  fi
done

# `while` runs in a subshell (piped), so a block() there exits only that
# subshell with 2; surface it as the hook's exit code.
status=$?
[ "$status" -eq 2 ] && exit 2

exit 0
