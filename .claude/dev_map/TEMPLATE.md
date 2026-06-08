# vX.Y.Z — <Release title>

<!--
  Reusable skeleton for a roadmap/dev-map stub. Copy to `vX.Y.Z.md` and fill in.
  `TEMPLATE.md` is ignored by the README roadmap list (it isn't named `vX.Y.Z`).
  Keep the section order; drop sections that don't apply (e.g. a hardening
  release may replace the lettered workstreams with a flat checklist). Checkbox
  convention: `[ ]` not started · `[ ]` + _(in progress)_ underway · `[x]` shipped.
-->

> **Status:** Not started. Documentation only — the roadmap the vX.Y.Z cycle is
> executed against. <!-- On ship: "Shipped. Delivered across PRs #.. into the
> `vX.Y.Z` integration branch; `.meta/VERSION` → X.Y.Z." -->
> **Depends on:** <prior versions whose code/patterns this builds on, or "none">.
> **Theme:** <one sentence: what this release turns the product into>.

## 1. Summary & non-goals

<Prose overview of what ships in this release — the 1–N concrete changes.>

**Non-goals (hard constraints):**

- <What must NOT change — untouched areas, invariants to preserve.>
- <e.g. "No new runtime dependencies", "No behavior change to X", performance budgets.>

## 2. Motivation

<Why now — the current-state problem(s) this addresses, from the user's view.>

## 3. Current state (grounded, with refs)

<Where the relevant code lives today, with `file:line` refs and the existing
helpers/patterns to reuse. Anchors the workstreams below.>

## 4. Workstream A — <name>

<Concrete unit of work: scope, deliverables, and the functions/files involved.
Repeat as Workstream B, C, … for each reviewable chunk. A hardening release may
instead use a flat checklist of areas (Testing / Docs / …) here.>

## 5. Data-layer / config changes (if any)

<New config constants, schema/column additions, new external inputs.>

## 6. Files touched (when implemented)

- `<path>` — <what changes>.

## 7. Suggested PR sequencing

Feature branches into the `vX.Y.Z` integration branch, in dependency order:

- [ ] **1.** `vX.Y.Z-<short-description>` (Workstream A).
- [ ] **2.** `vX.Y.Z-<short-description>` (Workstream B).

## 8. Acceptance criteria

- [ ] <Testable, user-facing exit condition.>
- [ ] <Invariants hold: prior releases unaffected; no unintended external calls.>
- [ ] Quality gates green (lint / format / tests).
- [ ] `.meta/VERSION` → `X.Y.Z` at release; index README + this file updated with
  the shipped PR list.
