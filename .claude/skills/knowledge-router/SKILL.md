---
name: knowledge-router
description: >-
  When durable, reusable knowledge surfaces in a conversation — a concept, a key fact, a
  domain or system model, a decision, a procedure, a hard-won codebase insight — decide
  where to store it so it compounds across sessions. Use whenever the user says to
  remember/note/capture/learn something, or when you recognize something worth keeping
  past this session. Routes each item to the right home (skill, project memory, CLAUDE.md,
  a reference note, or a docstring on the code itself) rather than dumping everything in
  one place, names where knowledge must not go, and defaults to
  dropping low-value observations. Trigger even if no keyword is used: a reusable insight
  is the signal.
---

# Knowledge Router

This is the front door for capturing durable knowledge. Its job is **classification, not
storage of everything**: most of what passes through a conversation is not worth keeping,
and the homes for what *is* worth keeping already exist. Route to them; don't duplicate
them. Nothing here "learns" — it externalizes notes to disk for a future cold-start
instance, so the bar is high and **drop is the default outcome.**

## Classify, then route

Identify what *kind* of knowledge it is and send it to the matching home:

- **A procedure that will recur** (a repeatable how-to, a workflow, a fix pattern) →
  hand to **skill-distiller**: it runs the significance + redundancy gate, then either
  folds the material into an existing skill or authors a new one (via `/add-skill` /
  `author-asset`). Don't write skills inline from here.
- **Evolving project state or a decision** (where the project is, what was chosen and
  why, an open thread) → **session-memory**. Update its `INDEX.md` / write a session log.
  This is trajectory, and it belongs in one place.
- **A short, always-relevant convention or fact** ("format with ruff before commit",
  "Office is Click-to-Run") → **`CLAUDE.md`** (the session contract that loads every
  time). Native, no note needed.
- **Durable, non-path-scoped reference** (a cross-cutting concept, an external-system
  fact, a schema, a glossary term, design rationale) → a **reference note** (below).
  This is the gap the other homes don't cover. A longer, stack-wide operating brief is a
  flat `context/<name>.md` doc instead (see `context/README.md`).
- **A candidate worker role** (you keep wanting a specialist with specific tools) →
  *note it for review*, don't auto-create an agent. Agents grant tools and run
  autonomously; their creation stays deliberate (use the `add-agent` command when a human
  decides to).
- **A mistake worth never repeating** (a correction you were given, a trap you fell into)
  → a **reference note of type `lesson`** (`context.py new --type lesson`, same tier and
  catalog as the notes below). Write the *rule*, not the story: "don't X, because Y" in one
  line. Lessons share the notes' plumbing but not their content rules — a lesson is a
  standing instruction, not a fact — and they stay free of design decisions and
  specifications, or the tier degenerates into a diary nobody reads.
- **Reasoning about one piece of code** (why this function guards that case, why the
  obvious implementation was rejected here, a trap the next editor will hit) → **the
  code itself**, as a docstring or a comment on the thing it concerns. The only home
  that is read at the moment it is needed, because the reader is already looking at
  the file. Scope it as `coding-standards` does — a design decision belongs on a
  class, a contract or a surprise on a function, a trap inline.
- **None of the above / a one-off / already captured** → **drop it.** Most observations
  land here.

## Choosing between homes

- **Memory or a note?** Memory is for things that *change* (state, decisions); a note is
  for things that are *stable* (facts, concepts).
- **A note or `CLAUDE.md`?** Short and consulted every session → `CLAUDE.md`. Larger and
  consulted occasionally → a note.
- **The code or somewhere shared?** Ask how far it reads: *would someone editing this one
  file need it, and would someone editing a sibling need it too?* One yes routes it to the
  code. **Two yeses route it away** — see the anti-destination below.

### Not the source, when it is cross-cutting

The first anti-destination: a rule holding across many files belongs in **none** of them.
Written into the file you had open, it is invisible from the other nineteen and the copies
drift — a palette comment in one template of a set did exactly that, naming a colour the
code had stopped using, and no reader of the other files could have caught it.

The notes tier already gates on this from the other side ("not tied to one file path"); the
anti-destination is that gate made two-way, so path-scoped knowledge has somewhere to go
and cross-cutting knowledge has somewhere it may not.

The trap is that it looks correct as you write it: the open file is always a plausible home
for what you just learned. Reach is the test, not convenience.

### When it belongs in two homes

The common case, not the edge — a cross-cutting rule usually has a local consequence. The
guardrail against storing one thing twice still holds, because you do not: **the rule goes
to the shared home in full, and the code carries a different sentence** — the local
consequence, or a one-line pointer naming where the rule lives. Never a second copy of the
rule, which is the thing that drifts.

## Separate the *why* from the *what*

Two kinds of durable knowledge get merged constantly, and the merge is what makes both
useless. Keep them apart even when they concern the same change:

- **Why it was decided** — the alternatives considered, the trade-off accepted, the
  constraint that forced it. Valuable to the next person facing the same fork, and it
  stays true even after the code changes.
- **What is now true** — the rule, the contract, the validated constraint, the interface.
  Valuable to anyone working today, and it goes stale the moment the thing changes.

Rationale filed as a spec reads as a rule nobody can safely change; a rule filed as
rationale gets skimmed as history and ignored. When one item contains both, split it and
route each half.

## What's worth keeping at all

Keep the bar concrete. Preserve knowledge that:

- explains a decision someone will otherwise re-litigate,
- names the alternative that was rejected and why,
- states a permanent rule established by a review, an incident, or a failure,
- documents a contract, validation requirement, or compatibility guarantee,
- explains why a specific regression guard exists — the case where forgetting the
  reason is how the bug comes back.

Discard, without ceremony:

- single-step task notes,
- hypotheses you abandoned and intermediate reasoning,
- progress logs that lost their value the moment the work finished,
- bare procedure lists with no reasoning attached — those are either a skill or noise.

## The reference-notes tier (`.claude/context/`)

For the one home that's genuinely new. It mirrors the memory pattern: a tiny always-loaded
`INDEX.md` (the discovery catalog) plus `notes/<topic>.md` files read **on demand**. The
index exists so you know a note is there to read; without it, on-demand notes are never
found and become dead weight. (It sits alongside the flat project-instruction briefs
already in `context/` — the INDEX catalogs the `notes/`, not the briefs.)

**Significance gate for a note** — it must be:
- **Durable** — a stable fact/concept, not session state (that's memory).
- **Declarative** — a thing that *is true*, not a how-to (that's a skill).
- **Cross-cutting** — not tied to one file path, and bigger than a one-line `CLAUDE.md` rule.
- **Worth more than one future consult**, and not already in `CLAUDE.md` or a skill.

**Write a note:**

```bash
python .claude/skills/knowledge-router/scripts/context.py new \
  --slug clickonce-trust-prompt --title "ClickOnce trust-prompt behavior" --type domain-fact
```

Fill the template's sections (what it is / key points / where it shows up / source), then
the catalog is regenerated automatically. Keep notes factual and tight — a reference card,
not an essay.

**Read a note:** the `INDEX.md` catalog is already in context (SessionStart hook), so when
a note's topic is relevant, read that one file. Use `context.py search "term"` to locate
one; `context.py list` to see all.

**Keep it honest:** the catalog is auto-generated from the notes (`context.py reindex`), so
it can't drift — but *content* can go stale. When a note becomes false, fix or delete it;
a confidently-wrong reference is worse than a missing one.

## Guardrails

- Hold the bar high. A sprawling knowledge store is standing cost (the index loads every
  session) and retrieval noise. When unsure, drop it — re-capturing later is cheap.
- Route to the *narrowest correct* home; don't store the same thing in two places.
- Never auto-author an agent from a captured pattern; queue the idea for human review.
- Don't bloat `CLAUDE.md` with reference that belongs in an on-demand note.

## SessionStart loading

The context index is surfaced at session start by `context-start.json`, which runs
`context.py index` (prints `INDEX.md` to stdout) — the exec-form sibling of the
session-memory SessionStart hook. Both indexes load each session; the catalog is what
makes on-demand notes discoverable. Keep both indexes tiny.
