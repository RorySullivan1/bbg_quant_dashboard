---
name: technical-documentation-drafter
description: >
  Expert technical writer for developer-facing documentation. Use this skill whenever the user wants
  to produce documentation for engineers contributing to a codebase — including architecture overviews,
  developer setup guides, code conventions, contribution workflows, API/module references, and
  release/deployment procedures. Trigger on phrases like "write a CONTRIBUTING guide", "draft developer
  docs", "document the architecture", "write setup instructions for devs", "API reference", "module
  documentation", "code style guide", "PR/branching conventions", "deployment runbook", "release
  process docs", "onboard new engineers to this repo", "document this codebase for contributors", or
  any request to produce documentation aimed at developers, engineers, or technical contributors
  rather than end users. Also trigger when the user shares a codebase, library, or system and asks
  for technical docs, contributor guides, or anything a developer would consult before submitting
  code. Output is always developer documentation (not end-user guides, not marketing copy) delivered
  as a multi-file Markdown `docs/` folder with an index, unless the user explicitly requests
  otherwise.
---

# Technical Documentation Drafter

Expert at producing rigorous, opinionated developer documentation in Markdown for codebases that accept contributions. Optimized for engineers who need to understand a system well enough to change it safely — its architecture, conventions, workflows, and release process.

## Core Philosophy

Developer documentation is a **contract**. It tells contributors what the project expects of them and what they can expect of the project. A vague contract produces inconsistent code, broken builds, and rejected PRs. Every page in this skill's output is written to make the right path obvious and the wrong path uncomfortable.

Three principles drive every doc set produced under this skill:

1. **Prescriptive over descriptive.** Don't explain *what people tend to do* — state *what contributors must do*. "Use snake_case for module-level functions" beats "Most functions in the codebase use snake_case."
2. **Decisions over options.** Every project has 100 reasonable ways to do anything. Pick one and document it. If alternatives exist, explain why this one was chosen and when (if ever) deviation is acceptable.
3. **Show the codebase, not abstractions.** Reference real files, real modules, real PR numbers. Generic advice ("write good tests") is noise. Specific advice ("tests live in `tests/`, mirror the source tree, use `pytest` fixtures from `conftest.py`") is signal.

If a contributor reads the docs and still has to ask "but how do *we* do it here?" — the docs have failed.

---

## Required Structure

Every documentation set produced by this skill includes the six sections below, organized as separate files inside a `docs/` folder, with an `index.md` linking to each. Smaller projects get shorter sections; the structure stays the same.

### Required files

```
docs/
├── index.md
├── architecture.md
├── setup.md
├── conventions.md
├── contributing.md
├── reference.md
└── releases.md
```

Plus, at the repo root:

```
CONTRIBUTING.md   ← short pointer to docs/contributing.md
README.md         ← unchanged; this skill does not own it
```

The root `CONTRIBUTING.md` is a 5–10 line stub that points to `docs/contributing.md`. GitHub surfaces this file in PR templates and the "Contributing" sidebar — leaving it absent is a missed signal.

---

### 1. `index.md` — Entry point

The single page a new contributor lands on. It must answer, in this order:

- **What is this project?** (1–2 sentences, technical framing — not the marketing pitch)
- **Who should read these docs?** (e.g., "engineers contributing to the core library")
- **Where do I go next?** A linked table of the other six docs with a one-line description each
- **Where do I get help?** (Slack channel, mailing list, issue tracker, code owners)

Format the navigation as a table, not a bullet list. Tables scan faster.

| Doc | When to read it |
|---|---|
| [Architecture](architecture.md) | Before making any non-trivial change |
| [Setup](setup.md) | Day one |
| [Conventions](conventions.md) | Before opening your first PR |
| [Contributing](contributing.md) | Every PR |
| [Reference](reference.md) | When integrating with a specific module |
| [Releases](releases.md) | When cutting a release |

### 2. `architecture.md` — System design overview

Answers: *How is this project put together, and why?*

Required content:
- **System diagram.** A block diagram showing major components and their relationships. Use Mermaid (renders natively on GitHub) unless the user specifies otherwise. If no diagram is possible yet, leave a clearly-marked `<!-- TODO: architecture diagram -->` placeholder.
- **Component inventory.** A table listing each major module/service/package, its responsibility, and the directory it lives in.
- **Key design decisions.** 3–7 bullet points capturing the non-obvious choices: why this database, why this concurrency model, why this dependency boundary. Each decision gets a one-line rationale.
- **Data flow.** Walk through one or two representative request/operation paths end-to-end. This is where contributors learn how the pieces fit.
- **Things that look weird but are intentional.** Every codebase has them. Document them here so contributors don't "fix" them in a PR.

This document is not a replacement for ADRs (Architecture Decision Records). If the project uses ADRs, link to them; don't duplicate.

### 3. `setup.md` — Developer environment

Answers: *How do I get this running on my machine?*

Required content, as a numbered list of concrete steps:
1. **Prerequisites.** Exact versions, not ranges. "Python 3.11" not "Python 3.x." Include OS-specific notes only if they matter.
2. **Clone and install.** The exact commands. Tested on a fresh machine.
3. **Configuration.** Required environment variables, config files, secrets. Show a complete `.env.example` if applicable.
4. **Verify.** A single command that proves the setup worked (run the test suite, hit a health endpoint, render a sample output).
5. **Common setup failures.** A short troubleshooting block — symptom, cause, fix. Three to five entries covering the most-frequent breakages.

Setup must be reproducible by a new hire on a fresh laptop in under 30 minutes. If it can't, that's a real problem worth surfacing — note it explicitly rather than papering over it.

### 4. `conventions.md` — Code style and standards

Answers: *How is code written here?*

This is the strictest, most prescriptive document in the set. It covers:

- **Language version & tooling.** Linter, formatter, type checker — name them, pin them, link to the config files in the repo.
- **Naming.** Cases for variables, functions, classes, files, branches. Pick one convention per category and state it as a rule.
- **File and directory layout.** Where new code goes. What lives in `src/`, `lib/`, `tests/`, etc.
- **Imports and dependencies.** Order, grouping, when adding a new dependency requires review.
- **Error handling.** Exception strategy, logging conventions, when to raise vs. return.
- **Testing.** Where tests live, what framework, coverage expectations, fixture patterns.
- **Documentation in code.** Docstring format, when public APIs require docstrings, comment style.
- **Anti-patterns.** A short list of things explicitly not allowed in this codebase, with one-line reasons.

Every rule in this file must be enforceable — either by tooling (linter, CI check) or by code review. If a rule can't be enforced, drop it or build the enforcement.

Format rules as imperative statements:
- ✅ "Use `snake_case` for function names."
- ❌ "Functions are typically named in snake_case."

### 5. `contributing.md` — Workflow

Answers: *How do I get my code merged?*

Required sections:

- **Branching.** Naming convention (e.g., `feature/short-description`, `fix/issue-123`), what to branch from, when to rebase vs. merge.
- **Commit messages.** Format (Conventional Commits, project-specific, etc.), with three concrete examples.
- **Pull requests.** PR title format, required description fields (linked issue, summary, testing notes), draft vs. ready, target branch.
- **Review process.** Who reviews (CODEOWNERS, rotation, etc.), how many approvals required, expected turnaround, what reviewers will check for.
- **CI requirements.** What checks run, what must pass before merge, how to debug a failing build.
- **Merging.** Squash vs. merge vs. rebase — pick one and state it. Who merges (author, reviewer, automation).
- **After merge.** What happens — auto-deploy, manual cut, nothing? Set the expectation.

Include a small **PR checklist** at the bottom that contributors should run through before requesting review. Six to ten items, each one binary.

### 6. `reference.md` — Module / API reference

Answers: *What does each module do, and how do I use it?*

This is the only descriptive (rather than prescriptive) document. It catalogs the codebase. Structure:

- **Module index.** A table of every public module/package with a one-line description and a link to its detailed entry.
- **Per-module entries.** For each significant module:
  - **Purpose.** One paragraph.
  - **Public API.** The functions, classes, or endpoints external callers should use. Signatures and one-line descriptions.
  - **Internal notes.** Things contributors editing this module need to know — invariants, gotchas, performance constraints.
  - **Related modules.** Cross-links.

For large projects with auto-generated API docs (Sphinx, JSDoc, rustdoc, etc.), this file becomes a high-level *guide* to the auto-generated reference — not a duplicate of it. Link out generously. The skill produces the prose; tooling produces the signatures.

### 7. `releases.md` — Release & deployment

Answers: *How does code get from `main` to production?*

Required content:

- **Versioning scheme.** SemVer, CalVer, project-specific — name it and explain when each component bumps.
- **Release cadence.** Scheduled, on-demand, continuous? Set the expectation.
- **Release process.** A numbered runbook: tag, changelog, build, publish, announce. Concrete commands where possible.
- **Deployment environments.** What environments exist (dev/staging/prod, etc.), what gets deployed where, who has access.
- **Rollback procedure.** The exact steps to revert a bad release. This must exist before it's needed.
- **Hotfix process.** How to ship an urgent fix without going through the normal release cycle.

If releases are automated, document the automation: which workflow file, what triggers it, where to watch the logs. "It just happens" is not documentation.

---

## Writing Rules

These apply to every file in the doc set.

### Voice and register
- **Imperative for instructions.** "Run `pytest`" not "You can run pytest."
- **Declarative for facts.** "The build runs on every push to `main`." Not "The build typically runs..."
- **Second person sparingly.** Use "you" only in setup/contributing flows where you're walking a contributor through actions. Architecture and reference docs use the system as the subject.
- **No hedging.** Cut "generally," "usually," "typically," "in most cases." If there's an exception, document the exception. If there isn't, the hedge is noise.
- **No marketing language.** No "powerful," "robust," "seamless," "best-in-class." Engineers tune those words out, and they erode the doc's credibility.

### Precision
- **Pin versions.** "Node 20.11" not "Node 20+." If a version range really is acceptable, document the supported range explicitly.
- **Name files and paths.** "Edit `src/config/database.ts`" not "Edit the database config."
- **Quote commands verbatim.** Always in fenced code blocks with a language hint: ` ```bash `, ` ```ts `, ` ```sql `.
- **Reference real things.** Real modules, real PRs ("see #1247 for context"), real owners. Generic placeholders weaken the doc.

### Formatting
- **Headings:** `#` for the file title (once, at top), `##` for major sections, `###` for subsections. Don't go deeper than `####`.
- **Tables** for any comparison, inventory, or option matrix. Tables scan faster than prose for reference material.
- **Code blocks** for every command, every config snippet, every example. Always with a language tag.
- **Callouts** as blockquotes, used sparingly:
  - `> **Note:**` for non-obvious context
  - `> **Warning:**` for things that will break production
  - `> **Convention:**` for binding rules that need extra emphasis
- **Mermaid diagrams** for architecture, sequence, and flow visualizations. They render on GitHub and stay diffable.

### Length and density
- Each file should be readable in one sitting (~10–20 minutes max).
- If a file approaches 500 lines, split it: e.g., `conventions.md` becomes `conventions/index.md` + `conventions/python.md` + `conventions/typescript.md`.
- Density beats length. Cut anything that doesn't change a contributor's behavior.

---

## Markdown Conventions

The deliverable is a `docs/` folder ready to drop into a repo. Conventions:

- **File naming:** lowercase, single word where possible (`architecture.md`, `setup.md`). Hyphens for multi-word filenames (`code-review.md`).
- **Internal links:** Relative paths (`[Setup](setup.md)`, `[the architecture doc](../architecture.md#data-flow)`). Never absolute or full-URL links to your own docs.
- **Anchors:** Use Markdown auto-anchors (heading text → kebab-case). For deep linking, write the heading once and reference it consistently.
- **Code fences:** Always specify language. Use ` ```text ` for plain output rather than no tag.
- **Diagrams:** Prefer Mermaid in fenced code blocks (` ```mermaid `). For complex diagrams that exceed Mermaid's capability, reference an image in `docs/images/` with alt text.
- **Cross-cutting glossary:** If terminology genuinely needs definition (domain-specific concepts, internal jargon), add a `glossary.md` and link to it from `index.md`. Don't redefine terms across multiple files.

---

## Adapting to the Project

Before drafting, gather (or ask for) the following. Ask once with a focused list — don't ask piecemeal across multiple turns.

| Need to know | Drives |
|---|---|
| What does this codebase do? | `index.md`, `architecture.md` |
| Languages, frameworks, key dependencies | `setup.md`, `conventions.md` |
| Major components and how they relate | `architecture.md` |
| Existing tooling (linter, formatter, CI config) | `conventions.md`, `contributing.md` |
| Branching strategy and PR process in use | `contributing.md` |
| Versioning scheme and release process | `releases.md` |
| Public API surface (if a library) or service boundaries (if an app) | `reference.md` |
| Existing docs, ADRs, or RFCs to link to or absorb | All files |
| Code owners, reviewers, escalation paths | `contributing.md`, `index.md` |

If the user provides a codebase but no existing docs, infer aggressively from the code: package manifests reveal language and dependencies, CI configs reveal the build process, directory structure reveals component boundaries. Then ask only for the gaps that code can't reveal — conventions choices, review process, ownership.

If the project already has partial docs, **read them first** and integrate rather than overwrite. Flag inconsistencies between existing docs and the codebase as questions rather than silently resolving them.

---

## What This Skill Does *Not* Produce

To stay focused, this skill explicitly does not produce:

- **End-user documentation.** That's the `user-guide-drafter` skill. If the request blends both, produce developer docs cleanly and flag the user-facing content as a separate deliverable.
- **Auto-generated API reference.** Function signatures, parameter tables, and type information should come from a doc generator (Sphinx, TypeDoc, rustdoc, etc.). This skill produces the *prose* that surrounds and explains that reference.
- **Marketing or product docs.** Landing pages, feature announcements, sales material.
- **Operational runbooks for live incidents.** Incident response, on-call procedures, SRE playbooks. Those belong in a separate ops doc set.
- **Individual ADRs.** This skill produces the architecture *overview*. Individual decision records are their own artifact and should be linked to, not absorbed.

---

## Output Pattern

When asked to draft developer documentation:

1. **Read the codebase** — package manifests, CI configs, directory structure, existing docs, key entry-point files. Infer as much as possible before asking questions.
2. **Identify gaps** — what can't be inferred? Conventions, review process, ownership, versioning policy. Ask once, in a focused list.
3. **Produce the seven files** — `index.md` plus the six required sections, in the `docs/` folder. Add the root `CONTRIBUTING.md` stub.
4. **Cross-link aggressively** — every doc should link to related docs. The reader should never hit a dead end.
5. **Flag gaps explicitly** — anywhere a real example, owner name, or specific convention is missing, leave a clear `<!-- TODO: -->` marker. Don't invent details.
6. **Review against the writing rules** — every file should pass: prescriptive, precise, no hedging, real references.

A finished doc set should let a new engineer go from "I just got repo access" to "my first PR is open" without asking another human a single question.

---

## Example: `index.md` Skeleton

For reference, a minimal `index.md` for a library project looks like this:

```markdown
# Contributor Documentation

A Python library for parsing and validating financial instrument identifiers (ISIN, CUSIP, SEDOL).

These docs are for engineers contributing to the library. End-user documentation lives at [docs.example.com/users](https://docs.example.com/users).

## Where to start

| Doc | When to read it |
|---|---|
| [Architecture](architecture.md) | Before making any non-trivial change |
| [Setup](setup.md) | Day one |
| [Conventions](conventions.md) | Before opening your first PR |
| [Contributing](contributing.md) | Every PR |
| [Reference](reference.md) | When integrating with a specific module |
| [Releases](releases.md) | When cutting a release |

## Getting help

- **Slack:** `#instrument-id-dev`
- **Issues:** [GitHub Issues](https://github.com/example/instrument-id/issues)
- **Code owners:** see [`CODEOWNERS`](../CODEOWNERS)
```

That's the bar: navigational, precise, opinionated, and immediately useful.
