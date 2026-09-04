---
description: Audit comments and docstrings against the prose scope discipline — dispatches the prose-auditor agent over the named paths (default — the branch's changed files) and relays its findings.
argument-hint: [paths or globs to audit — omit for the branch's changed files] [--apply]
---

You are running a prose audit: comments and docstrings judged against the agreed
discipline (`coding-standards` § *How much, by scope*), by the agent built for it.

## 1. Resolve the scope

- If `$ARGUMENTS` names paths/globs (ignoring a trailing `--apply`), those are the scope.
- Otherwise: the branch's changed files (`git diff --name-only origin/main...HEAD`,
  falling back to uncommitted changes via `git status`).
- If that resolves to nothing, say so and stop — don't silently audit the whole tree;
  a tree-wide sweep is something the user asks for by passing `.` explicitly.

## 2. Dispatch the auditor

Delegate to the **`prose-auditor`** agent (do not inline the audit in this session — the
read-heavy pass belongs in its context, and the agent's mandate carries the discipline):
hand it the resolved file list and any focus the user stated. It runs the project's
`prose_budget` measurer plus the semantic pass, and returns findings with dispositions
(**trim / move → where / add / keep — justified**). It never edits.

## 3. Relay, then stop — unless `--apply`

Report the agent's verdict, findings table, and "fix first" item as given — don't
re-litigate its judgments, and keep its check-the-check notes (a finding against the
*measurement* is routed to the hook's maintainer, not applied to code).

- **Default (no `--apply`):** stop after relaying. The audit is the deliverable;
  applying it is a separate decision.
- **With `--apply`:** apply the findings in disposition order — *add* the missing floor
  docs, *trim* the dead prose, and for every *move*, place the reasoning in the named
  destination **before** removing it from the code (route-then-trim, never
  delete-then-hope). Skip anything marked *keep — justified*. Then re-dispatch the
  auditor over the same scope to confirm the findings cleared, and report the before/after.
