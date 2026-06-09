# `.claude/templates/`

Portable, repo-agnostic copies of this project's agent-config layer, kept here so
they can be lifted into **other** repositories without dragging in
bbg_quant_dashboard specifics. The project's own *active* config (the wired hooks
in `.claude/hooks/`, the `workstream` skill in `.claude/skills/`) stays
unchanged; these are the generic siblings.

| Path | What it is | Adopt by |
| --- | --- | --- |
| `hooks/block-protected-push.sh` | `git push` guard with a configurable/auto-detected protected-branch list (vs. the active hook's hardcoded `main`/`master`). | Copy into the target repo's `.claude/hooks/`, `chmod +x`. |
| `hooks/quality-gates.sh` | `git commit` gate driven by `quality-gates.conf` (`QG_GATES`/`QG_PATHS`); skips scan paths that don't exist. | Copy into `.claude/hooks/`, `chmod +x`, add a `quality-gates.conf`. |
| `hooks/quality-gates.conf.example` | Sample gate config (ruff/black/pytest default + flake8/unittest, Node variants). | Copy to `.claude/hooks/quality-gates.conf` and edit. |
| `hooks/settings.snippet.json` | Copy-paste `hooks.PreToolUse` wiring for `.claude/settings.json`. | Merge into the target repo's settings. |
| `skills/workstream/SKILL.md` | Project-agnostic version of the `/workstream` development loop, with `[…]` spots to fill in per project. | Copy into `.claude/skills/workstream/` and adapt the bracketed spots. |

See [`../hooks/README.md`](../hooks/README.md) for how the active hooks and these
templates relate, and [`../dev_map/TEMPLATE.md`](../dev_map/TEMPLATE.md) for the
reusable roadmap-stub skeleton.
