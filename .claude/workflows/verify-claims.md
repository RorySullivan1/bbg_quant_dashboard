# verify-claims

Take an asset that asserts facts about an external system and establish, claim by claim,
whether those facts are true — then label each one with its provenance so a future reader
can tell a vendor-documented rule from somebody's Tuesday afternoon.

Run this **before shipping** a skill or context doc that carries factual weight, and when
adopting an asset from elsewhere. It is the **truth gate** — independent of `skill-creator`'s
performance evals; `claim-grounding` (this workflow's engine) states that division of labor.

**Inputs:** a target asset (a `SKILL.md`, a context brief, a bundle).
**Output:** the asset updated with tier-labeled claims and dated citations; a report of
what was verified, what was corrected, and **what could not be verified**.

## Steps

1. **Extract the claims.** Read the asset and list every falsifiable factual assertion
   about an external system — API signatures, property/constant names, platform limits,
   default values, behavioral quirks. Skip judgment, style, and preference; those are not
   claims and must not be dressed as such.

2. **Triage by what would settle each one.** Apply the `claim-grounding` triage table:
   authority-settled (a live system can answer), doc-settled (vendor documentation
   governs), experience-settled (only observed behavior supports it), or not-a-claim.
   Sort by blast radius — verify what a reader will *act on* first.

3. **Ground the doc-settled claims.** Confirm the governing source actually says what the
   asset says, and record the URL **and the retrieval date** — `claim-grounding` owns the
   citation rules; don't restate them here. For Microsoft surfaces use
   `mcp__Microsoft_Learn__microsoft_docs_search` then `microsoft_docs_fetch` for the full
   page; otherwise `WebFetch` the spec.

4. **Ground the authority-settled claims** *(only where a probe is available)*. Apply
   `claim-grounding`'s **"Grounding against a live authority"** section as written —
   controls, round-trip, serialization, stop-the-line, deliberate promotion, no CI wiring.
   The skill is the source of truth for that discipline; a summary here would only drift.

5. **Label the rest honestly** per the skill's experience-settled tier: mark the claim in
   the asset itself, naming where it was observed — never delete it, never launder it.

6. **Correct what's wrong.** Fix false claims at the source; delete claims that turned out
   to be unfounded and unverifiable. Never soften the check to make a claim survive.

7. **Record the judgments** for anything that took real work to settle, per
   `references/ledger-schema.md` — identity, verdict, rationale, `grounded_by`, and date.
   This is what stops the same claim being re-argued next quarter.

8. **Report.** State what was verified and how, what changed, and — the part people drop —
   **the claims still unverified**. An honest gap is a finding; an unmentioned gap reads as
   coverage that was never there.

## Control flow / stop conditions

- **No falsifiable claims** in the asset → **stop**, nothing to do here. A skill that only
  teaches judgment needs no grounding pass.
- **Sources disagree** (docs vs observed behavior, or two vendor pages) → **stop and report
  the drift.** Do not pick whichever source makes the claim convenient; surface the
  conflict and let a human settle it.
- **A probe's controls fail** → **stop.** The harness is broken; nothing it produced this
  run is evidence.
- **All claims tiered, labeled, and dated** → **done.** Hand off to `ship-version`.

## Invokes

- Skill: `../skills/claim-grounding/` (the triage, grounding, and ledger discipline).
- Reference: `../skills/claim-grounding/references/ledger-schema.md` (record shape).
- Tools: `mcp__Microsoft_Learn__microsoft_docs_search` / `microsoft_docs_fetch`, `WebFetch`.
- Hook: none here — the upstream `asset_integrity.py` structural check is not vendored in this
  repo (see `../hooks/README.md`); the semantic gate stands alone.
- Workflow: `ship-version.md` (ships once the truth gate passes).
