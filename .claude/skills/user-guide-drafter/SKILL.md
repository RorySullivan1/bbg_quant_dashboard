---
name: user-guide-drafter
description: >
  Expert technical writer for end-user documentation. Use this skill whenever the user wants to
  produce user-facing documentation for a project, tool, script, app, macro, dashboard, internal
  tool, or any deliverable whose audience is non-technical end users. Trigger on phrases like
  "write a user guide", "draft documentation", "README for users", "how-to doc", "onboarding doc",
  "user manual", "docs for my [tool/app/macro/spreadsheet/dashboard]", "explain how to use this",
  "write instructions for [users/the team/the desk]", "document this project", or any request to
  turn a working project into something a non-technical person can pick up and use. Also trigger
  when the user shares code, a workflow, or a finished tool and asks for documentation, a guide,
  or explanatory text aimed at consumers rather than developers. Output is always end-user
  documentation (not API docs, not developer onboarding, not architecture docs) delivered as
  Markdown unless the user explicitly requests another format.
---

# User Guide Drafter

Expert at producing clear, accessible end-user documentation in Markdown for projects, tools, and applications. Optimized for non-technical business users who need to understand *what* something does, *why* it exists, *how* to use it, and *what to do when it breaks* — without wading through implementation detail.

## Core Philosophy

A user guide is **not** a feature list, a code walkthrough, or a marketing page. It is a tool that helps a real person accomplish a real task with the project. Every sentence must serve that goal. When in doubt, cut.

Three principles drive every guide produced under this skill:

1. **Task-first, not feature-first.** Users open a guide because they want to *do* something. Lead with what they can accomplish, not with what the tool contains. "Generate the weekly QIS Brief" beats "Overview of the email module."
2. **Plain language over precise jargon.** If a term has a five-syllable name and a one-syllable meaning, use the one-syllable meaning. Define jargon the first time it's unavoidable.
3. **Show, don't just tell.** Concrete examples, screenshots (when available), copy-pasteable commands, and small numbered steps beat paragraphs of prose every time.

If the project is technical underneath but the audience isn't, the guide hides the technical layer entirely. The user does not need to know there is a Python script behind the button — they need to know which button to click.

---

## Required Structure

Every user guide produced by this skill includes these four sections, in this order, regardless of project size. Smaller projects get shorter sections, not fewer sections.

### 1. Intent — "Why this exists"

A short opening (2–5 sentences) that answers:
- What problem does this solve?
- Who is it for?
- What does using it get them?

This section sets expectations so users self-select in or out before investing time. Avoid origin stories, version history, or technical motivation — those belong in a CHANGELOG or developer doc.

### 2. Quick Start — "Get me running in under 5 minutes"

The fastest possible path from zero to a successful first use. Format as a numbered list of concrete actions. Include:
- Any one-time setup (install, permissions, credentials) — only if truly required
- The minimum command, click, or input needed to see a result
- A description of what success looks like ("You should see…")

If a project genuinely cannot be used in under 5 minutes, say so honestly and split into "Initial setup" and "First use" subsections. Never pad Quick Start with optional steps.

### 3. Feature Reference / How-To — "How do I do X?"

Organized by **task**, not by feature, function, or menu structure. Each entry follows the same micro-pattern:

```markdown
### How to [accomplish task]

**When to use this:** [one-sentence context]

**Steps:**
1. [Action]
2. [Action]
3. [Action]

**Result:** [what the user will see]

**Notes:** [optional — caveats, tips, common variations]
```

Order tasks by frequency of use, not by complexity. The thing 80% of users will do should be the first task documented.

### 4. Troubleshooting / FAQ — "Something went wrong"

Organized as **symptom → cause → fix**. Use the user's likely phrasing for the symptom, not the engineer's. A user types "it won't open" — not "ERR_INIT_FAIL on module load."

Format:

```markdown
### "[Symptom phrased as the user would say it]"

**Likely cause:** [plain-English explanation]

**Fix:**
1. [Action]
2. [Action]

**If that doesn't work:** [escalation path — who to contact, where to file an issue]
```

Always include an escalation path at the end of the section. Users need to know what to do when the guide runs out.

---

## Writing Rules

These apply to every section.

### Voice and tone
- **Address the user directly** with "you." Avoid "the user" except in the description/intent section.
- **Use active voice and the imperative for instructions.** "Click Save" not "The Save button should be clicked."
- **Be confident, not cautious.** "This will export your data" beats "This may potentially export your data in most cases."
- **Be friendly but not chatty.** No emojis unless the project is genuinely playful. No exclamation points except for genuine warnings.

### Plain language
- Prefer the shorter, more common word. "Use" beats "utilize." "Start" beats "initialize."
- One idea per sentence. Break long sentences.
- Define a term the first time it appears, in parentheses or a short clause: *"the macro (a small program that runs inside Excel)"*.
- If you find yourself writing a definition that's longer than the term being defined, the term might be wrong for this audience.

### Formatting choices
- **Headings:** Use `##` for top-level sections, `###` for tasks/subsections. Avoid going deeper than `####`.
- **Numbered lists** for sequential steps. **Bullet lists** for unordered options.
- **Bold** for UI elements the user will click or type into ("Click **Save**"). **Code** for literal commands, file paths, and inputs (`config.yaml`).
- **Callouts** as blockquotes for important info:
  - `> **Note:**` for helpful context
  - `> **Warning:**` for things that could cause data loss or errors
  - `> **Tip:**` for shortcuts or pro-moves
- **Tables** for comparisons or option references — never for sequential instructions.

### Length discipline
- Quick Start should fit on one screen.
- Each How-To entry should fit on one screen.
- A guide for a small project should be one Markdown file. A guide for a large project should be split across files with a clear index.

---

## Markdown Conventions

The deliverable is always a `.md` file (or set of files) ready to drop into a repo, wiki, or docs site. Conventions:

- **Filename:** `README.md` for single-file guides, `docs/index.md` (or `docs/user-guide.md`) for split docs.
- **Top of file:** H1 title (`# [Project Name] — User Guide`), then a one-line tagline, then a table of contents *only if* the guide is longer than ~150 lines.
- **Internal links:** Use Markdown anchor links for cross-references: `[Troubleshooting](#troubleshooting)`.
- **Code blocks:** Always specify the language for syntax highlighting (` ```bash `, ` ```python `, ` ```vba `). Use plain ` ``` ` only for output samples or generic text.
- **Images:** Reference with relative paths (`![Login screen](images/login.png)`). If the user hasn't provided images, leave clearly marked placeholders: `<!-- TODO: screenshot of login screen -->`.

For multi-file docs, produce an `index.md` (or update the existing one) that links to each section file. Default to single-file unless the project is genuinely large.

---

## Adapting to the Project

Before drafting, gather (or ask for) the following. If the user hasn't provided enough, ask once with a focused list of questions — don't ask piecemeal across multiple turns.

| Need to know | Why it matters |
|---|---|
| What does the project do? | Drives Intent and Quick Start |
| Who uses it? (role, technical level, context) | Sets the language register |
| How do users interact with it? (CLI, button, email, web form, spreadsheet) | Determines the format of step-by-step instructions |
| What are the 3–5 most common things users will do? | Becomes the How-To section |
| What goes wrong most often? | Becomes Troubleshooting |
| Where does the user go for help? | Becomes the escalation path |
| Is there branding, tone, or style to match? | Aligns with house style |

If the user provides a working project (code, a macro, a tool) but no documentation, infer as much as possible from the project itself — function names, comments, UI labels, error messages — then ask only for the gaps.

---

## What This Skill Does *Not* Produce

To stay focused, this skill explicitly does not produce:

- **API reference docs** — function signatures, parameter tables, return types. Use a doc-generation tool (Sphinx, JSDoc, etc.).
- **Developer onboarding** — how to set up a dev environment, run tests, contribute. That's a `CONTRIBUTING.md`.
- **Architecture docs** — system diagrams, data flows, design decisions. That's a separate ADR or design doc.
- **Marketing copy** — landing pages, sales collateral.
- **Internal runbooks** — operational procedures for engineers.

If a request blends user docs with one of the above, produce the user guide cleanly and flag the rest as a separate deliverable.

---

## Output Pattern

When asked to draft a user guide:

1. **Read the project** (code, files, context the user shared) to understand what it actually does.
2. **Identify the audience and primary tasks** — ask if unclear.
3. **Draft the four required sections** in order: Intent → Quick Start → How-To → Troubleshooting.
4. **Review against the writing rules** — every section should pass: task-first, plain language, concrete examples.
5. **Deliver as a single `.md` file** unless the project warrants splitting.
6. **Flag gaps** — anywhere a screenshot, a real example, or a missing detail would improve the guide, leave a clear `<!-- TODO: -->` marker so the user knows what to fill in.

A finished guide should be something a brand-new user could open, read top-to-bottom in under 15 minutes, and immediately use the project successfully.

---

## Example: Micro-Guide Skeleton

For reference, a minimal user guide for a small tool looks like this:

```markdown
# Weekly Report Generator — User Guide

Generates and emails the weekly performance report to the distribution list.

## What this is for

The weekly report generator pulls performance figures from the master spreadsheet, formats them into the standard report template, and emails the result to your distribution list. It exists so you don't have to copy-paste numbers into Outlook every Friday.

## Quick start

1. Open `WeeklyReport.xlsm`.
2. Click the **Generate Report** button on the Home tab.
3. Wait 5–10 seconds. A draft email opens in Outlook with the report attached.
4. Review the draft and click **Send**.

You should see a confirmation message: *"Report generated successfully."*

## How to...

### Change the distribution list
**When to use this:** Someone joins or leaves the team.
**Steps:**
1. Open `WeeklyReport.xlsm`.
2. Go to the **Settings** tab.
3. Edit the email addresses in column B (one per row).
4. Save and close.
**Result:** The new list will be used the next time you generate a report.

### Re-run the report for a previous week
[…]

## Troubleshooting

### "The Generate Report button does nothing"
**Likely cause:** Macros are disabled.
**Fix:**
1. Close the file.
2. Right-click `WeeklyReport.xlsm` → **Properties** → check **Unblock** → **OK**.
3. Reopen and try again.
**If that doesn't work:** Contact [escalation path].
```

That's the bar: short, direct, task-driven, and immediately usable.
