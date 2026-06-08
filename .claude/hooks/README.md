# `.claude/hooks/`

PreToolUse(Bash) hooks that **enforce** this repo's development workflow. They are
wired in [`.claude/settings.json`](../settings.json) and run on every `Bash`
tool call; each receives the tool-call JSON on stdin and inspects
`.tool_input.command`.

**Exit-code contract** (Claude Code): `0` = allow the command, `2` = block it
(stderr is shown to the agent as the reason), any other non-zero = non-blocking
hook error.

## Active hooks (this repo)

| Hook | Fires on | What it does |
| --- | --- | --- |
| `quality-gates.sh` | `git commit` | Blocks the commit unless `ruff check src tests`, `black --check src tests`, and `python -m pytest -q` pass. Each tool is enforced only when present (so a deps-less env isn't bricked). Mirrors `.pre-commit-config.yaml`. |
| `block-main-push.sh` | `git push` | Blocks a push whose refspec targets `main`/`master`. Work lands on a feature/integration branch and reaches `main` via a PR. |

These two are intentionally **hardcoded** to this project's branches
(`main`/`master`), tools (`ruff`/`black`/`pytest`), and layout (`src`/`tests`).
The prose counterpart lives in `CLAUDE.md` → "Development workflow" + "Branching";
the `workstream` skill is the playbook that ties them together.

## Portable templates

Repo-agnostic, parameterized versions of both hooks live under
[`../templates/hooks/`](../templates/hooks/) for lifting into other repos:

- **`block-protected-push.sh`** — same `git push` guard, but the protected-branch
  list comes from `$CLAUDE_PROTECTED_BRANCHES` (space/comma list), else the
  auto-detected remote default branch (`origin/HEAD`), else `main master`.
- **`quality-gates.sh`** — same `git commit` gate, but the gate list and scan
  paths are config-driven via `quality-gates.conf` (`QG_GATES` /
  `QG_PATHS`); the `{paths}` token expands to only the paths that **exist**, so a
  missing `tests/` is skipped instead of erroring. Defaults match a
  ruff/black/pytest `src tests` layout.
- **`quality-gates.conf.example`** — sample config (with flake8/unittest and
  Node/eslint variants).
- **`settings.snippet.json`** — copy-paste `hooks.PreToolUse` wiring.

To adopt in another repo: copy the two `.sh` files into its `.claude/hooks/`,
`chmod +x` them, copy `quality-gates.conf.example` to
`quality-gates.conf` and edit, then merge `settings.snippet.json` into that
repo's `.claude/settings.json`.

> The path-existence skip and the parameterization live only in the templates;
> backporting them into the two active hooks above is an optional later change.
