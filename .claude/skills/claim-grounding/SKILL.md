---
name: claim-grounding
description: >-
  Establish whether a factual claim is actually true, and record the judgment so it isn't
  re-litigated or silently eroded. Use when authoring or reviewing any asset that asserts
  facts about an external system (API signatures, control properties, language constants,
  platform limits, tool behavior), when a claim's provenance is unclear ("is this actually
  true", "where did this fact come from", "verify this against the docs"), or when curating
  a corpus of findings — triaging true/false positives, updating a snapshot or lint
  baseline, explaining a baseline delta, or deciding whether evidence supports a fix.
  Trigger even if nobody says "verify": an unsourced factual assertion in a durable asset
  is the signal. For whether a skill *triggers and performs* well, use skill-creator; this
  skill is about whether its content is *true*.
---

# Claim Grounding

A durable asset's authority rests on its factual claims. Two things quietly destroy that
authority, and they need different remedies:

- The claim was **never checked** against the system it describes — it is plausible, it is
  stated confidently, and nobody ever asked the system.
- The claim was checked once and **the judgment was lost** — so it gets re-litigated, or
  worse, silently overwritten by whatever output is convenient today.

This skill covers both halves: **ground** a claim against an authority, then **record** the
judgment as evidence. Grounding without a ledger is work you'll redo; a ledger without
grounding is bookkeeping over guesses.

## Core principles

- **Evidence outranks plausibility.** A claim that sounds right and matches the general
  shape of the technology is not thereby true. Most wrong facts in a skill are plausible.
- **The authority is the system, not opinions about the system.** When docs and runtime can
  disagree, name which one governs the claim *before* you check.
- **Absence of a judgment is not a judgment.** Unreviewed is a state, not a verdict.
- **Never edit the evidence to make a claim pass.** If the check fails, the claim is wrong
  — not the check.

## Triage first: what would settle this claim?

Before verifying anything, classify each factual assertion by what could actually settle
it. The tier determines both the effort and, crucially, **how the claim must be labeled**:

| Tier | Settled by | Record |
|---|---|---|
| **Authority-settled** | A live system answers definitively (runtime, API, compiler, app) | The probe + its result (see *Grounding*) |
| **Doc-settled** | Vendor documentation is the governing spec (Microsoft Learn, an RFC, a language spec) | The URL **and the date retrieved** |
| **Experience-settled** | Only observed behavior in one project supports it; no doc, no probe | Say so, in the asset itself |
| **Not a claim** | Judgment, preference, house style | Nothing — don't dress it as fact |

The failure this prevents is **tier laundering**: an experience-settled observation gets
copied into a skill, loses its origin, and is then read with the same confidence as a
vendor-documented rule. A claim you cannot ground is not forbidden — it is *required to be
labeled*. "Observed in <project>, not confirmed in vendor docs" is an honest, useful
sentence. Silence in its place is not.

Ground what is **load-bearing and falsifiable**: the claims a reader will act on and that
could be wrong. Don't re-verify arithmetic or restate the obvious.

## Grounding against a live authority

When the answer depends on a real system's behavior rather than a document, build the
smallest probe that asks it. The discipline matters more than the harness:

1. **Run known controls first.** Probe one case whose answer you already know should pass
   and one that should fail, *before* the case in question. If a control disagrees with its
   recorded outcome, your harness is broken — stop. You have learned nothing about the new
   case, and any result it produced is void.
2. **Round-trip the input.** Read back what you submitted. If the system normalized,
   reformatted, or rewrote it, your evidence describes *the rewritten input*, not yours.
   Discard it rather than attributing the behavior to what you meant to send.
3. **Serialize when the resource is exclusive.** A stateful, single-user authority — a
   running desktop app, one license seat, a browser profile, a shared sandbox — cannot be
   probed concurrently. Concurrent probes produce interference, not evidence.
4. **Stop the line on infrastructure failure.** A timeout, an unexpected dialog, a crashed
   worker, or a cleanup you could not confirm is a **non-result**, not a negative result.
   Never promote a claim off a failed or flaky run, and never let "it errored, so probably
   unsupported" become a recorded fact.
5. **Promote deliberately.** A confirmed outcome becomes evidence through an explicit step,
   never as a side effect of something else going green.
6. **Report what ran — and what didn't.** Record the cases executed, the commands, and the
   date. Then state the claims you could *not* verify. An honest gap is a finding; an
   unmentioned gap reads as coverage you never had.

Keep grounding harnesses **local and developer-only**. Do not wire a live-authority probe
into CI, ordinary tests, or a shipped command. CI should assert only what it can honestly
reach — and when the interesting boundary is outside CI's reach, say so and gate on a
manual check rather than letting green CI imply coverage it doesn't have.

## Recording the judgment

Keep two records, and never let them merge. Conflating them is the classic error:

- **Observation** — what the system emitted. Mechanical, cheap, regenerable at any time.
- **Judgment** — whether that output is *correct*. A semantic call, expensive, and **not**
  regenerable. This is the asset worth protecting.

The rules that follow from the split:

- **Never update an observation baseline merely to silence a diff.** Every added, removed,
  or moved row gets explained before any baseline is accepted. A snapshot row is proof that
  output occurred, never proof that it was right.
- **Absence means unreviewed.** Leave undecided items out of the ledger entirely; never
  serialize "unreviewed" as if it were a verdict.
- **Record the full identity** of the thing judged — source, location, rule, severity — so
  a judgment cannot drift onto a different item that merely resembles it. Keep multiplicity
  (how many times it occurred) as a separate field, outside the identity.
- **Contract drift stops the work.** If the spec, the registry, the implementation, and the
  tests disagree about the same rule, report the drift and stop. Do not adopt whichever
  source makes today's classification convenient.
- **One root cause per unit of work.** A batch of items sharing one cause is fine; unrelated
  judgments belong in separate work.

See `references/ledger-schema.md` for a concrete record shape.

## Name the authority inside the asset

Any asset carrying factual claims should say what governs it and defer to it explicitly:

> The vendor documentation is the schema authority. If this skill and that documentation
> disagree, follow the documentation and report the drift.

This one line stops a skill from quietly becoming a competing spec that outlives the thing
it describes.

## Worked example

A Power Platform skill asserts two things. They look alike and are graded differently:

- *"Delegable query limits default to 500 rows, configurable up to 2000."* — **doc-settled.**
  Microsoft Learn governs it. Cite the page and the date you read it; if the product changes,
  the dated citation is what lets a future reader tell fresh from stale.
- *"The HtmlText control strips `<style>` blocks, so styling must be inlined."* — vendor docs
  don't state it. Only a downstream project's observed behavior supports it. That is
  **experience-settled**, and the skill must say so. It is still worth keeping — it will save
  someone hours — but presenting it in the same register as the delegation limit is the
  laundering failure. If it matters enough, ground it: build the smallest app that renders a
  `<style>` block, run the controls, record the result and the date.

## Watch out

- **Grounding theatre** — attaching a citation that doesn't actually say what the claim says.
  A URL is not evidence; the sentence in it is.
- **Promoting off a flaky run.** If it took three attempts and two failed oddly, you have an
  infrastructure problem, not a result.
- **Verifying everything.** Grounding has a real cost; spend it on load-bearing claims.
- **Letting the ledger rot.** A confidently wrong record is worse than a missing one. When a
  claim becomes false, fix or delete it — and say which.

## Out of scope

- Whether a skill **triggers reliably and outperforms baseline** → `skill-creator` (evals,
  variance analysis, description optimization). That measures *performance*; this measures
  *truth*. A skill can win every eval while asserting a false fact.
- **Where** a piece of knowledge belongs → `knowledge-router`, `context-vs-skill`.
- **How to shape** a `SKILL.md` → `skill-authoring`.
