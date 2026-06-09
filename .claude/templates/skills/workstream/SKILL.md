---
name: workstream
description: A project-agnostic development loop — take one roadmap item from plan to merged PR. Plan-first, then a feature branch off the integration branch, the project's quality gates, commit, push, and a PR into the integration branch. Use when starting or implementing a roadmap/dev-map item, or when asked to "do a workstream", "start the next item", or "ship this change the usual way".
argument-hint: [workstream / roadmap item to implement]
---

# /workstream — the project development loop

A portable playbook for shipping one roadmap item cleanly. Drop this into any
repo's `.claude/skills/workstream/` and adapt the bracketed `[…]` spots to that
project. It assumes a roadmap (a `README.md` index plus per-item stubs), an
integration branch per release, and commit/push gates — but names none of the
specific tools, so it travels between projects.

> **Guidance, not magic.** The repo's `CONTRIBUTING` / `CLAUDE.md` say the same
> thing in prose; `.claude/settings.json` PreToolUse hooks (see
> `.claude/hooks/`) *enforce* the quality gates and the no-push-to-protected
> rule. This skill is the playbook that ties them together.

## The loop

### 1. Plan first
- If you are **not** already in plan mode, ask the user to enter it
  (`Shift+Tab` twice, or relaunch with `claude --permission-mode plan`).
  There is **no** setting that auto-starts plan mode — prompt for it explicitly.
- Read the roadmap stub for the target item; explore the code paths it names;
  design the change; surface open questions; get the plan approved before
  editing.

### 2. Branch off the integration branch
- Cut work from the release's **integration branch**, not the protected default
  branch (`main`/`master`). [Name the integration-branch convention here, e.g.
  `vX.Y.Z`.]
- Give each workstream its **own feature branch** off that integration branch,
  named with the project's convention. [e.g. `vX.Y.Z-<short-description>`.]
  - **Flat-naming caveat:** if the integration branch is named exactly `vX.Y.Z`,
    git can't also host nested refs like `vX.Y.Z/<type>/<desc>` (a ref can't be
    both a file and a directory) — use a hyphenated form (`vX.Y.Z-<desc>`).
- One workstream per branch — keep PRs small and reviewable (mirror the
  roadmap's "Suggested PR sequencing").

### 3. Implement
- Make only the changes the workstream calls for; respect the stub's non-goals.
- Add or update tests for new behavior.
- Keep things in their canonical homes per the project's conventions (see
  `CLAUDE.md` / `CONTRIBUTING`). [List the key ones here, e.g. style tokens,
  templates.]

### 4. Quality gates (must be green before committing)
- Run the project's configured gates — lint, format-check, and tests — before
  committing. [Spell out the exact commands here, e.g.
  `ruff check . && black --check . && pytest -q`.]
- The `.claude/hooks/quality-gates.sh` PreToolUse hook re-runs these on every
  `git commit` and **blocks** the commit if any fail — so run them yourself
  first to avoid a blocked commit.

### 5. Commit & push
- Commit with a clear, descriptive message in the repo's style (a summary line
  plus a body explaining the *why*; see existing history).
- `git push -u origin <branch>`. **Never push to the protected branch**
  (`main`/`master`) — the `block-*-push.sh` hook blocks it; open a PR instead.

### 6. PR into the integration branch
- Open the PR with **base = the integration branch**, not the protected default.
- In the PR body, summarize the change and link the roadmap item.
- Tick the workstream's checkbox in the roadmap's PR-sequencing list.
- Defer version bumps and release-note edits to the **end** of the release cycle
  (per each stub's acceptance criteria), not per-PR.

## Target for this run

Implement: **$ARGUMENTS**

If `$ARGUMENTS` is empty, read the roadmap index, identify the current in-flight
release and its next unchecked workstream, and confirm the target with the user
before proceeding.
