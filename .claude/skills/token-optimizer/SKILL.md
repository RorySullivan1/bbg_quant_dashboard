---
name: token-optimizer
description: >-
  Keep a Claude Code session token-efficient by deciding where work runs before it floods
  the main context, and by triaging context when a session gets heavy. Use before a
  high-volume operation (reading large/many files, running test suites, processing logs,
  fetching docs), when the conversation is getting long or approaching compaction, or
  when the user asks to save tokens / reduce context / speed things up. Routes bulk work
  to the token-manager agent or Explore, slices large reads, and flushes state to memory.
  Trigger even if "tokens" isn't said: any heavy operation is a placement decision.
---

# Token Optimizer

This decides *where* work happens so volume stays out of the permanent main context. It
doesn't filter output itself (the `PostToolUse` Bash hook does that) — it's the judgment
layer that runs before an action and when context is getting heavy. Keep three distinct
costs in mind, because they don't move together: **main-thread growth** (the transcript,
reloaded every turn, degrades quality as it fills), **total tokens processed**, and
**dollars** (which model). Isolation shrinks the first; cheaper models cut the third; a
wide fan-out can raise the second.

## Before a high-volume operation

Estimate first, then place it. The helper is a rough estimator (no real tokenizer):

```bash
python .claude/skills/token-optimizer/scripts/tokens.py estimate path/to/file
python .claude/skills/token-optimizer/scripts/tokens.py estimate src/   # whole dir
```

Then route by what the work is:

- **Bulk search / "where is X" / "how does Y work"** → delegate to **Explore** (Haiku,
  read-only, isolated, and it skips CLAUDE.md/git). Cheapest tokens *and* the churn never
  enters main context.
- **Verbose operation you don't need verbatim** — test suite, log processing, large/many
  file analysis, doc fetch → delegate to the **token-manager** agent. It does the volume
  in its own context and returns a capped summary.
- **A large file you do need to read directly** → read a slice with `offset`/`limit`, not
  the whole thing. (The `PreToolUse` read guard backstops this on very large files, but
  decide deliberately rather than relying on the cap.)
- **Small, self-contained, needs iteration** → just do it in the main thread. Delegation
  has a floor: a fresh agent re-gathers context, so shipping a trivial task out is
  net-negative.

The return contract is the catch with delegation: every agent's *summary* lands back in
main, so a wide parallel fan-out of detailed returns can cost more than it saved. Cap the
fan-out and tell each worker what to return.

## When the session is getting heavy

Before context fills (or before a compaction you can see coming):

- **Flush durable state to memory**, then stop carrying it in-thread. If the project has
  the session-memory skill, update its `INDEX.md` so the conversation can shed detail
  safely instead of holding it defensively.
- **Move remaining verbose work to subagents** rather than doing it inline.
- **Stop re-reading** files already in context; reference them instead of re-loading.

## Standing-cost hygiene (small but every turn)

These sit in context on *every* turn, so trimming them compounds over a long session:
keep `CLAUDE.md` lean (static rules only; dynamic state belongs in memory); keep installed
skill descriptions tight and prune unused skills (each description is a permanent tax);
and scope a niche MCP server into the subagent that needs it (frontmatter `mcpServers`)
rather than the main session, so its tool schemas don't sit in the main window.

## Anti-patterns

- Slurping a large file whole when a slice would do.
- Fanning out many agents that each return large summaries — the returns flood the
  context the fan-out was meant to protect.
- Delegating a one-line task and paying agent startup for it.
- Bloating `CLAUDE.md` with things that change, or with context that belongs in memory.
