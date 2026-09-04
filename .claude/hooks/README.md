# `.claude/hooks/`

Two kinds of hook, both wired in [`.claude/settings.json`](../settings.json):
**PreToolUse(Bash) gates** that enforce this repo's development workflow (each
receives the tool-call JSON on stdin and inspects `.tool_input.command`), and
**PostToolUse advisories** that shape what the model sees without ever blocking.

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

## Advisory hooks (this repo)

Vendored from `RorySullivan1/claudebrain` (`example-project/.claude/hooks/`). Both are
Python, non-mutating, and fail safe: on any unexpected payload they print nothing and
the call proceeds. Neither can veto anything.

| Hook | Fires on | What it does |
| --- | --- | --- |
| `post_bash_filter.py` | `PostToolUse` (Bash) | Strips ANSI codes and, when a command's output exceeds 200 lines / 12 000 chars, keeps the first 80 and last 40 lines with an elision marker — so a full `pytest` run or `git log` doesn't flood the context. The command already ran; only what the model sees changes. |
| `prose_budget.py` | `PostToolUse` (Edit/Write/MultiEdit) | Measures the edited file's docstrings/comment runs against the per-scope caps in [`../prose-budget.json`](../prose-budget.json) (the shipped defaults: module 20, class 30, function 15, comment run 5, attribute 30 lines) and reports overruns as advice pointing at the `coding-standards` skill § *How much, by scope*. Python only (`ast` + `tokenize`). |

`prose_budget.py` is opt-in by the presence of `.claude/prose-budget.json` — delete that
file and it goes silent. The 54 overruns that existed when the check was adopted (v0.9.14)
are grandfathered in [`../prose-baseline.json`](../prose-baseline.json), keyed by qualified
name (comment runs by a content hash) so an unrelated edit above them doesn't churn the
key. The baseline is meant to shrink, never grow: when you right-size a grandfathered
docstring, remove its entry. The same measurer is importable (`scan_source`, `scan_tree`),
which is what the `prose-auditor` agent and `/prose-review` run.

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
