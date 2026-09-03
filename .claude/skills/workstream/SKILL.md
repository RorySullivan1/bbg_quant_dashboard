---
name: workstream
description: The bbg_quant_dashboard development workflow — take one workstream from plan to merged PR. Plan-first, then a flat-named branch off `main`, ruff/black/pytest quality gates, commit, push, and a PR into `main`. Use when starting or implementing a tracked issue, a roadmap workstream, or any v0.6.x/v0.7.0/etc. feature; or when asked to "do a workstream", "start the next item", or "ship this change the usual way".
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

### 2. Branch off `main`
- `main` is the trunk: branch from it, and land back in it by PR.
- Flat-named, prefixed with the version the work ships in:
  `X.Y.Z-<short-description>` (e.g. `0.9.14-benchmark-registry`).
- **Flat naming is required:** git cannot host nested refs like
  `v0.9.0/<type>/<desc>` while a branch literally named `v0.9.0` exists. Use
  the hyphenated form. (See CLAUDE.md "Branching".)
- **Integration branches are the exception.** Cut one — named exactly `vX.Y.Z`
  — only for a multi-PR epic whose parts are not individually shippable; it
  merges into `main` and is deleted when the epic completes. Note that a PR
  based on such a branch **runs no CI** until it is retargeted at `main` (see
  issue #202), so verify those locally before merging.
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

### 6. PR into `main`
- Open the PR with **base = `main`** — or, for one part of a multi-PR epic,
  the epic's integration branch, which itself PRs into `main`.
- In the PR body, summarize the change and close the issue with a closing
  keyword (`Closes #N`). It fires only on the merge into `main` — GitHub
  honours closing keywords against the **default** branch only — so an epic's
  sub-PRs retire their issues when the integration branch lands, not before.
- Defer `.meta/VERSION` bumps and CLAUDE.md release notes to the **end** of the
  version cycle, not per-PR.

## Target for this run

Implement: **$ARGUMENTS**

If `$ARGUMENTS` is empty, list the open issues carrying the current version
cycle's label, identify the next one to pick up, and confirm the target with the
user before proceeding.
