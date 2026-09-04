# Evidence ledger — record shape

A concrete shape for the **judgment** record described in `SKILL.md`. Adapt the field names
to the domain; keep the four structural properties.

## The four properties that matter

1. **Identity is complete and normalized.** A judgment must be pinned to exactly one thing.
   If two different items could match the same record, the judgment will eventually drift
   onto the wrong one.
2. **Multiplicity sits outside identity.** How many times something occurred is data about
   the observation, not part of what was judged. Keep it in its own field so a count change
   doesn't read as a new item.
3. **A rationale is mandatory.** Record the *fact that makes the verdict true*, not the
   verdict alone. A bare `true-positive` is unreviewable a month later.
4. **Absence is meaningful.** Undecided items have no row. There is no `unreviewed` value —
   that state is expressed by not being in the ledger at all.

## Shape

One JSON object per line (JSONL), sorted canonically so diffs stay reviewable:

```jsonl
{"id":{"source":"src/report.py","symbol":"build_summary","line":142,"rule":"E501","severity":"warning"},"verdict":"true-positive","count":3,"rationale":"Line is 118 chars; the project cap is 100 and this file is not generated.","grounded_by":"doc:https://peps.python.org/pep-0008/","checked":"2026-08-14"}
{"id":{"source":"src/legacy/parse.vb","symbol":"ParseRow","line":88,"rule":"VB-201","severity":"error"},"verdict":"false-positive","count":1,"rationale":"Analyzer treats the ByRef parenthesized arg as a value copy; the runtime passes by reference.","grounded_by":"probe:byref-parenthesized-variable","negative_controls":["accept:byref-plain-variable"],"checked":"2026-08-14"}
```

### Fields

| Field | Purpose |
|---|---|
| `id` | The complete normalized identity. Every coordinate needed to re-find *this* item. |
| `verdict` | The semantic call — e.g. `true-positive`, `false-positive`. Never `unreviewed`. |
| `count` | Multiplicity. Deliberately outside `id`. |
| `rationale` | The source fact that makes the verdict true. Required. |
| `grounded_by` | Provenance, tier-tagged: `doc:<url>`, `probe:<case-id>`, or `experience:<project>`. |
| `negative_controls` | For a rejection: the accepted cases that protect the same rule from over-correction. |
| `checked` | The date the judgment was made — what lets a reader tell fresh from stale. |

`grounded_by` carries the tier from the triage table in `SKILL.md`. An `experience:` value is
legitimate; an *absent* one is not.

## Two files, never one

Keep observations and judgments in separate files:

```
observations/snapshot.jsonl   ← regenerated mechanically from the system
reviews/ledger.jsonl          ← written only by deliberate judgment
```

The snapshot may be regenerated at will. The ledger may not — every row costs a real
decision. When a snapshot delta appears, explain it against the ledger *before* accepting
the new baseline; a row that vanishes from the snapshot while its judgment remains is
either a fix worth noting or a regression in the harness.

## Negative controls

When you record that something is wrong (a false positive, an unsupported behavior), also
record the cases that must keep working. Otherwise the fix that satisfies this row is free
to break the rule everywhere else, and nothing will catch it.
