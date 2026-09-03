---
name: agent-finder
description: >-
  Find and delegate to the optimal Claude Code subagent(s) for a task instead of
  defaulting to general-purpose or doing everything in the main thread. Use whenever
  a task could be delegated — research, codebase exploration, code review, test runs,
  domain-specific work, or anything that would flood the main context with output —
  and whenever the user asks which agent to use, to "use the right agent", to run work
  in parallel, or to spin up a specialist. Trigger even if the user doesn't say the
  word "agent": any multi-step or high-volume side task is a delegation decision.
---

# Agent Finder

Subagents run in their own context window and return only a summary, so the reason to
delegate is to keep verbose work (search results, logs, file dumps) and tool churn out
of the main conversation. Claude Code selects an agent by **matching the task against
each agent's `description`** — so picking well is mostly disciplined reading of the
agent descriptions already surfaced in context, with a cheap fallback to grep a large
pool or inspect an agent's real tools/model before a borderline call.

Work the decision in four steps: **inventory → match → choose topology → delegate.**

## 1. Inventory (what agents exist)

The descriptions of custom agents are already in your context, and three built-ins are
always available:

- **Explore** — Haiku, read-only. Fast/cheap codebase search and file discovery. Pass a
  thoroughness level (`quick` / `medium` / `very thorough`).
- **Plan** — read-only research to gather context before proposing a plan.
- **general-purpose** — all tools; complex multi-step work needing both exploration and
  modification. This is the fallback when no specialist fits.

Custom agents live in `.claude/agents/` (project, committed) and `~/.claude/agents/`
(user); project wins on a name collision. You usually don't need to read these files —
their descriptions are already surfaced. Use the helper only to grep a large pool, or to
check an agent's actual `tools`/`model`/scope before committing to it:

```bash
python .claude/skills/agent-finder/scripts/agents.py list          # all agents + built-ins
python .claude/skills/agent-finder/scripts/agents.py search "vba"   # match name/desc/tools
python .claude/skills/agent-finder/scripts/agents.py show NAME      # full definition + scope
```

(`python3` on macOS/Linux.)

## 2. Match (pick the best-fit agent)

- **Most specific wins.** Prefer the narrowest agent whose description fits the task over
  general-purpose. A specialist carries scoped tools and (often) preloaded skills, so it
  wastes fewer turns getting oriented.
- **Match the constraint, not just the topic.** Confirm the agent's tools/model actually
  fit the work. A read-only reviewer can't make edits; an opus researcher is overkill for
  a file lookup. If unsure what an agent can touch, `show NAME` and read its frontmatter.
- **Default routings:** read-only investigation → **Explore** (or a read-only custom
  researcher); design-before-editing → **Plan**; exploration *plus* modification, or any
  task with no matching specialist → **general-purpose**; domain work → the matching
  domain agent.
- **Tie-break by description quality.** If two agents fit, prefer the one whose
  description most precisely names the task — that's the same signal Claude routes on.

## 3. Choose topology (how many, in what shape)

- **Single agent** — the common case: one self-contained task returning a summary.
- **Parallel fan-out** — independent subtasks with no shared dependencies (e.g. research
  auth, DB, and API modules at once). Spawn them in one turn. **Cap it:** every agent's
  result returns to the main context, so a wide fan-out of detailed returns can cost more
  context than it saves.
- **Sequential chain** — dependent steps; pass each agent's summary into the next (find
  issues → fix them).
- **Stay in the main thread** instead when the task needs tight back-and-forth, shares
  significant context across phases, is a quick targeted change, or is latency-sensitive
  (a fresh agent pays startup cost gathering context).
- **Fork** (when enabled) when a task needs the full current conversation to make sense —
  a fork inherits history so you skip re-explaining, while its tool churn still stays out
  of the main context.
- For a quick question about something already in context, prefer `/btw` over a subagent.

## 4. Delegate (hand off well)

A non-fork subagent starts **fresh** — no conversation history, no files you've already
read. The delegation prompt is the entire brief, so make it crisp:

- **Objective** — the concrete outcome, not a vague topic.
- **Inputs** — exact paths, file names, ticket IDs, scope boundaries.
- **Constraints** — restate any rule the agent must honor (e.g. "ignore `vendor/`",
  "conda only"); it does **not** inherit your conversation's working assumptions.
- **Return contract** — what to hand back: a summary, the failing tests with messages,
  the diff — *not* a raw dump. This is the whole point of isolating the work.
- **Model/thoroughness** — set only when it matters (cheap Haiku/Explore for search,
  stronger model for hard reasoning).

To invoke: name the agent in the delegation ("Use the quant-researcher subagent to…"),
@-mention it (`@agent-<name>`) to force that exact agent, or spawn the Agent tool with
`subagent_type` set to the chosen name. For parallel work, issue the spawns together.

## Efficiency rules (long-context)

- Route bulk search to **Explore** (Haiku) — it's the cheap, fast default for "where is
  X / how does Y work", and its output never lands in your main context.
- **Isolate high-volume operations** (test suites, log processing, doc fetches) to a
  subagent so only the summary returns.
- **Don't over-delegate.** A single trivial step is faster done in the main thread than
  shipped to an agent that must boot and re-gather context. Delegation earns its cost
  when the work is verbose, self-contained, or genuinely parallel — not by default.
- Prefer a **specific** agent over general-purpose: scoped tools and preloaded skills
  mean fewer wasted turns.

## When nothing fits

Use **general-purpose** with a tight, fully-specified prompt. If you find yourself
spawning the same kind of worker with the same instructions repeatedly, that's the
signal to *create* a reusable agent (a markdown file in `.claude/agents/` with
`name`/`description` plus a focused system prompt, or via the `/agents` command) so the
description is there to route on next time.

## Anti-patterns

- Picking an agent by name vibes without checking its tools/model actually fit the task.
- Fanning out many agents that each return large results — the returns flood the context
  the fan-out was meant to protect.
- Delegating a one-line change, then waiting through agent startup for it.
- Assuming the subagent shares your context — it doesn't; everything it needs goes in the
  delegation prompt.
