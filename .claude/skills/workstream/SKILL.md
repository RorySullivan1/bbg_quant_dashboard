---
name: workstream
description: The bbg_quant_dashboard development workflow — take one workstream from plan to merged PR. Plan-first, then a flat-named sub-branch off the version integration branch, ruff/black/pytest quality gates, commit, push, and a PR into the integration branch. Use when starting or implementing a tracked issue, a roadmap workstream, or any v0.6.x/v0.7.0/etc. feature; or when asked to "do a workstream", "start the next item", or "ship this change the usual way".
argument-hint: [workstream / issue number to implement]
---

# /workstream — the project development loop

This skill encodes how work ships in `bbg_quant_dashboard`. Follow it for every
roadmap item so branches, gates, and PRs stay consistent. Scope lives in
**GitHub issues**, labelled per version cycle (e.g. `v0.9.13-perf`). Read the
issue before doing anything — it carries the problem statement, the proposed
fix, and the acceptance criteria that define the workstream.

> **Guidance, not magic.** The CLAUDE.md "Development workflow" + "Branching"
> sections say the same thing in prose; the `.claude/settings.json` PreToolUse
> hooks *enforce* the quality gates and the no-push-to-main rule. This skill is
> the playbook that ties them together.

## The loop

### 1. Plan first
- If you are **not** already in plan mode, ask the user to enter it
  (`Shift+Tab` twice, or relaunch with `claude --permission-mode plan`).
  There is **no** setting that auto-starts plan mode — it is a per-session
  choice, so prompt for it explicitly.
- Read the target issue; explore the code paths it names; design the change;
  surface open questions; get the plan approved before editing.

### 2. Branch off the integration branch
- Each version has one integration branch named exactly `vX.Y.Z` (e.g.
  `v0.6.5`), cut from `main`.
- Each workstream gets its **own flat-named sub-branch** off that integration
  branch: `vX.Y.Z-<short-description>` (e.g.
  `v0.6.5-dark-design-tokens-and-global-css`).
- **Flat naming is required:** git cannot host nested refs like
  `v0.6.5/<type>/<desc>` while a branch literally named `v0.6.5` exists. Use
  the hyphenated form. (See CLAUDE.md "Branching".)
- One workstream per branch, one issue per branch — keep PRs small and
  reviewable.

### 3. Implement
- Make only the changes the workstream calls for; respect the stub's non-goals
  (e.g. "no analytics/behavior change").
- Add or update tests in `tests/` for new behavior.
- Keep all colors/sizes/HTML in their canonical homes (`src/style.py` tokens,
  `data/templates/*.html` via `render_template`) — see CLAUDE.md "Conventions".

### 4. Quality gates (must be green before committing)
```
ruff check src tests
black --check src tests
python -m pytest -q
```
The `.claude/hooks/quality-gates.sh` PreToolUse hook re-runs these on every
`git commit` and **blocks** the commit if any fail — so run them yourself first
to avoid a blocked commit. (`black src tests` to auto-fix formatting.)

### 5. Commit & push
- Commit with a clear, descriptive message in the repo's style (a summary line
  plus a body explaining the *why*; see existing history).
- `git push -u origin <branch>`. **Never push to `main`/`master`** — the
  `block-main-push.sh` hook blocks it; open a PR instead.

### 6. PR into the integration branch
- Open the PR with **base = the version integration branch** (`vX.Y.Z`), not
  `main`.
- In the PR body, summarize the change and close the issue with a closing
  keyword (`Closes #N`), so merging the PR retires the workstream.
- Defer `.meta/VERSION` bumps and CLAUDE.md release notes to the **end** of the
  version cycle, not per-PR.

## Target for this run

Implement: **$ARGUMENTS**

If `$ARGUMENTS` is empty, list the open issues carrying the current version
cycle's label, identify the next one to pick up, and confirm the target with the
user before proceeding.
