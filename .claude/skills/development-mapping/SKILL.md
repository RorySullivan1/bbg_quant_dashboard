---
name: development-mapping
description: >
  Expert at turning a whole-project objective into a **development map** — an ordered
  plan of stages → versions → milestones that drives iterative delivery. Use this skill
  whenever the user wants to plan a project's trajectory above the level of a single
  change: laying out a roadmap, breaking an objective into phases/stages, slicing work
  into shippable versions, defining milestones and acceptance criteria, sequencing by
  dependency and risk, or deciding what the next version should be. Trigger on "plan the
  project", "lay out a roadmap", "break this objective into stages", "what should the
  versions be", "development plan", "milestones", "what do we build first", "sequence
  this work". Authors/maintains `.meta/roadmap/` (via the `/roadmap-set` command). This
  is the *sequence/scope-over-time* altitude — it sits ABOVE `software-architect`
  (which designs structure, not order) and ABOVE `.meta/version` (one current unit of
  work); each version it plans is executed by the `advance-roadmap-step` workflow.
---

# Development Mapping Skill

You convert a fuzzy "build this whole thing" into a **map you can walk**: an ordered
sequence of versions, each a single shippable increment, each with an acceptance bar.
The map is the contract the rest of the flow executes against — get the *sequence* and
the *slicing* right and the iterative engine downstream just turns the crank.

## Where this sits (don't blur the altitudes)
- **This skill (roadmap / sequence over time):** what gets built, in what order, grouped
  into versions and stages, with milestones and acceptance. It owns `.meta/roadmap/`.
- **`software-architect` (structure):** how the code is laid out — components, boundaries,
  where things live. The map says *what version 0.3 delivers*; the architect says *how
  it's structured*. Hand structural questions to it.
- **`.meta/version` (the cursor):** the single version currently in flight. The map is the
  whole route; `.meta/version` is "you are here." A version card graduates into
  `.meta/version` when work on it starts.

## The artifact — `.meta/roadmap/`
A directory of nested markdown. Keep `INDEX.md` small and current (it's auto-surfaced at
session start); push detail down into the stage/version files.

> **See `EXAMPLE.md`** (beside this skill) for a complete, illustrative map of a hypothetical
> project — INDEX + a stage + a version card, with the reasoning behind the sequence. The
> `.meta/roadmap/` in this repo is a trimmed *showcase sample* (see its banner), not a plan
> this repo executes — your project replaces it with a real one.

```
.meta/roadmap/
├── INDEX.md                 # objective · ordered stages · per-version status table (the dashboard)
└── stages/
    ├── 01-<theme>/
    │   ├── STAGE.md         # stage goal, the versions in it, the stage exit (milestone) criteria
    │   ├── v0.1.0.md        # one version card: goals + acceptance (the source for /version-set)
    │   └── v0.2.0.md
    └── 02-<theme>/
        ├── STAGE.md
        └── v0.3.0.md
```

- **INDEX.md** = the dashboard: the overall objective, the stage list, and a status table
  (`planned` / `in-progress` / `shipped`) with the active cursor marked. One screen, no more.
- **STAGE.md** = a coherent phase (a theme or capability), its versions, and the
  **milestone** that means the stage is done.
- **Version card** (`vX.Y.Z.md`) = one shippable increment: **Goals** (what it delivers)
  and **Objectives / acceptance** (how you know it's done). This file is exactly the shape
  `/version-set` writes into `.meta/version`, so the card *is* the version contract.

## How to decompose (objective → stages → versions → milestones)

1. **Anchor on the objective and constraints.** Read them from `CLAUDE.md`/brief — don't
   invent scope. The objective is the destination; everything below serves it.
2. **Find the stages.** Group the work into a handful of phases by capability or theme
   (foundation → core → polish; or by subsystem). A stage ends at a **milestone** — a
   demonstrable capability, not a date.
3. **Slice stages into versions.** Each version is **one coherent increment that ships as
   one PR**. Right-size: big enough to be worth a release, small enough to review and
   revert as a unit. If a version can't be described in 2–4 goals, split it.
4. **Sequence by dependency and risk.** Order so each version stands on shipped ground:
   - **Walking skeleton first** — a thin end-to-end slice that proves the architecture
     before breadth.
   - **De-risk early** — pull the uncertain/expensive/likely-to-change work forward so a
     wrong assumption is cheap to fix.
   - **Vertical over horizontal** — prefer thin full-stack slices that deliver user-visible
     value each version over building entire layers no one can exercise yet.
5. **Write acceptance per version.** Each card's Objectives are the *testable* bar a step
   must clear before it ships ("X covered by tests; Y validated against Z; no regression in
   W"). These become the goal-auditor's checklist downstream — make them checkable, not
   aspirational.
6. **Assign semver labels.** Map the sequence onto semver by *nature*: breaking →
   major, new capability → minor, fix/hardening → patch. Pre-1.0 projects often run the
   whole early roadmap as `0.y` minors. Keep labels monotonic.

## Keep the map alive (it's a plan, not a monument)
- Mark status honestly: `planned` → `in-progress` (the cursor) → `shipped` (PR merged).
- **Re-plan when reality diverges.** Discovering a version was mis-sized or a dependency
  flipped is a signal to re-slice the *remaining* map, not to force the old plan. Past
  (shipped) versions are immutable history; the future is editable.
- Don't over-plan the far future. Detail the next 1–2 stages; keep later stages as
  one-line intentions until they're next.

## Handoff (how the map drives the flow)
- The map is authored/updated through **`/roadmap-set`** (this skill supplies the thinking;
  the command writes the files).
- When a version starts, its card feeds **`/version-set`** → `.meta/version`.
- The **`advance-roadmap-step`** workflow then implements → reviews → reiterates → has the
  **`goal-auditor`** check the result against the card's acceptance → stops for approval →
  ships via `ship-version`, then steps the cursor and updates `INDEX.md`.

## Watch Out
1. **A roadmap is a sequence, not a backlog.** A flat list of everything you might do isn't
   a map. The value is the *order* and the *slicing* — what's first, what each version
   delivers, what "done" means for each.
2. **Oversized versions stall the engine.** If a version can't ship as one reviewable PR,
   the reiterate/assess loop downstream never converges. Split before you start.
3. **Acceptance must be checkable.** "Make it better" can't be audited. Each version's
   Objectives have to be something the goal-auditor can verify against the diff.
4. **Don't decide the objective.** Like `software-architect`, you design *toward* the
   objective; you don't set product scope. Surface scope questions to the user, don't
   quietly choose.
5. **Plan the next stage in detail, sketch the rest.** Over-specifying version 9 before
   version 2 ships is waste — the map will change by then.
