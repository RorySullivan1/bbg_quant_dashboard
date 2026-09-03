---
name: skill-distiller
description: >-
  Spot reusable know-how produced during a plan or conversation and decide whether to
  promote it into a new skill. Use whenever you've just worked out a non-obvious,
  repeatable procedure, settled a recurring design pattern, or finished a plan that
  encodes a reusable workflow — and whenever the user asks to "turn this into a skill",
  capture/save this as a skill, or check whether something is skill-worthy. Runs a
  significance gate and a redundancy check before anything is built, and prefers folding
  into an existing skill over creating a new one. Trigger even if the user doesn't say
  "skill": a freshly-derived reusable procedure is the signal.
---

# Skill Distiller

This decides whether material you just generated should become a skill — it does **not**
author the skill itself (hand that to the `/add-skill` command / `author-asset` workflow).
Two failure modes govern the whole design, and every rule below exists to fight them:
**over-flagging** (most things feel reusable in the moment; few are) and **skill
proliferation** (many narrow, overlapping skills make triggering *worse*, because their
descriptions collide and each under-fires). So the bar is high, flagging is cheap, and the
default verdict on overlap is "extend what exists," not "create."

Pipeline: **flag → assess significance → check redundancy → refine → emit.** Don't
interrupt active work to run it end-to-end; flagging to the queue (Step 5) is the
in-the-moment action, and real authoring happens deliberately later.

## 1. Flag — is there a candidate at all?

A candidate is a *procedure or pattern*, not a fact or a one-off answer. Good raw
material: a multi-step workflow you reconstructed, a set of gotchas you had to discover,
a domain convention you pinned down, an approved plan that you'd run again. Not
candidates: a single factual answer (that's a `knowledge-router` reference note or
memory), a value that will change, or anything you produced in one obvious step (if you
do it well by default, a skill adds nothing).

## 2. Significance gate (hard filter)

A candidate must clear **all three** of these or it is not a skill:

- **Recurrence** — it will plausibly come up again. If it won't recur, it's a note for
  memory, not a skill.
- **Non-obviousness** — it encodes procedure, gotchas, or domain specifics you would not
  reliably reproduce from scratch. Trivial procedures don't even trigger skills.
- **Generality** — it transfers beyond this exact instance; the specifics can be
  templated away.

Then sanity-check two more: **durability** (stable over time, not pinned to something
that changes weekly) and **payoff vs. cost** (saves enough future effort to justify the
standing cost — every skill's description sits in context permanently). If it fails any
of the three hard criteria, stop: either drop it or, if it's a worth-remembering one-off,
record it as memory instead.

## 3. Redundancy check (prefer extending)

Before proposing anything new, compare the scoped candidate against existing skills:

```bash
python .claude/skills/skill-distiller/scripts/skills.py list
python .claude/skills/skill-distiller/scripts/skills.py similar "<candidate description>"
```

`similar` ranks existing skills by lexical overlap and flags likely targets. It's a
prompt to look, not a verdict — read the top matches, then choose an outcome:

- **Duplicate** — an existing skill already covers it → drop.
- **Overlap / extends** — meaningful shared ground → **fold the material into that skill**
  (update its SKILL.md). This is the default whenever overlap is real; resist spawning a
  sibling.
- **Adjacent but distinct** — make the trigger boundary crisp so its description doesn't
  collide with the neighbor's (collision makes both under-fire).
- **Net-new** — nothing close → a new skill is justified.

## 4. Refine — scope it before building

Turn the raw material into a clean spec: write a tight trigger boundary (the description
is the routing surface — precise, not vague), strip instance-specifics, generalize the
examples, and decide what's SKILL.md body versus a reference file. Keep the scope to one
coherent job; a skill that tries to cover two loosely-related things triggers poorly.

## 5. Emit — author now, or enqueue

Choose based on confidence and timing:

- **Author now** when significance is clearly high, the outcome is net-new or a clean
  extension, and you're at a natural stopping point. Hand the refined spec to the
  **`/add-skill`** command (via the **`author-asset`** workflow), which scaffolds the
  SKILL.md and frontmatter; for an extension, edit the existing skill directly. (The
  planned `skill-authoring` meta-skill will own description optimization.)
- **Enqueue** when it's plausible but borderline, when you're mid-task and shouldn't
  break flow, or when one more occurrence would confirm it recurs. Append a stub and
  move on:
  ```bash
  python .claude/skills/skill-distiller/scripts/skills.py add-candidate \
    --name proposed-name --desc "one-line trigger description" \
    --why "why it clears the significance gate" --source "this plan/session"
  ```
  Review the queue (`skills.py candidates`) deliberately later and build the survivors.
- **Drop** when it failed Step 2 or is a duplicate. Dropping is the common, correct
  outcome — most candidates shouldn't become skills.

## Guardrails

- Hold the significance bar high. When unsure, enqueue rather than author — a stub is
  cheap, a half-useful skill is permanent context cost and triggering noise.
- Prefer extending an existing skill over creating a new one whenever overlap is real.
- Never interrupt active work to author a full skill; flag to the queue instead.
- The redundancy script is lexical, so it can miss a semantic duplicate — when a
  candidate is conceptually close to something you recall, check it by hand even at a low
  overlap score.

## Relationship to knowledge-router

`knowledge-router` is the front door for *all* durable knowledge and routes the
"procedure that will recur" case here; this skill owns just the skill-promotion decision
(the gate, the dedupe, the queue) and then hands authoring to `/add-skill`. Facts,
decisions, and reference notes stay with `knowledge-router` / `session-memory`.

## Optional: plan-approval hook

The `post-tool-use-plan-nudge` hook fragment runs `scripts/plan_nudge.py` on `PostToolUse`
for `ExitPlanMode` — a clean deterministic moment when reusable workflows often
crystallize — and emits a factual nudge to consider this skill. The free-conversation case
is handled by this skill's own description (self-flag). A more aggressive `Stop`-prompt
hook that checks every turn is possible but taxes the whole session for an occasional
payoff, so it's not shipped on by default.
