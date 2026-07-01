---
name: github-issues
description: >
  Expert at handling GitHub issues — writing, triaging, organizing, and closing them
  well. Use this skill whenever the user wants to create, file, triage, label, assign,
  link, break down, or close issues: writing a clear bug report or feature request,
  applying labels/types/milestones, splitting an epic into sub-issues, linking issues
  to PRs, searching/deduplicating existing issues, or curating a backlog. Trigger on
  "open an issue", "file a bug", "write a feature request", "triage these issues",
  "label this", "break this into sub-issues", "is there a duplicate", "close issue
  #N", "link this issue to the PR". Prefers the GitHub MCP tools (`issue_write`,
  `issue_read`, `list_issues`, `search_issues`, `sub_issue_write`) where present, else
  the `gh` CLI. Pairs with github-pull-requests (the PR that closes the issue) and
  github-comments (discussion on the issue). Be frugal — don't file noise.
---

# GitHub Issues Skill

A good issue is a unit of work someone can pick up cold: it states the problem, the
evidence, and what "done" looks like. Your job is to make issues precise, findable, and
non-duplicative — and to close the loop when work lands.

## Before filing — search first
**Always check for an existing issue before opening a new one.** Use `search_issues` /
`gh issue list --search` on the key terms and error text. Duplicates fragment
discussion and annoy maintainers. If you find one, comment/upvote there (see
github-comments) instead of filing again; if filing a genuine near-duplicate, link it
("Related to #45").

## Honor the issue templates
Check `.github/ISSUE_TEMPLATE/` for forms (`*.yml`) or markdown templates and fill the
matching one (bug vs. feature vs. question). If the repo uses **issue types** or a
required-fields config, set them. A template's headings are the maintainer's expected
shape — match them.

## Writing a bug report
Lead with what's broken and how to see it:

```markdown
### What happened
The upload retries forever when the server returns 503.

### Steps to reproduce
1. Call `upload(path)` against a server returning 503
2. Observe: it loops without backoff or limit

### Expected
Retry with backoff, give up after N attempts, surface the error.

### Environment
v2.3.1 · Python 3.12 · Linux

### Evidence
<log excerpt / stack trace / failing test>
```

- **Title = the symptom**, specific and searchable: "Upload retries forever on 503",
  not "bug in uploader".
- One bug per issue. Reproduction steps and expected-vs-actual are the parts
  maintainers most often have to ask for — include them up front.

## Writing a feature request
State the problem before the solution: **who** needs **what** and **why**, then a
proposed approach (clearly marked as a proposal), acceptance criteria, and scope/non-goals.
A feature framed as a problem invites better solutions than one framed as a demand.

## Triage — make the backlog navigable
- **Labels:** apply the repo's existing taxonomy (`bug`, `enhancement`,
  `good first issue`, area/priority labels). Read the label list first; don't invent
  labels that overlap existing ones. Use `get_label` / `gh label list`.
- **Type / milestone / assignee:** set where the project uses them.
- **Deduplicate:** close duplicates with a pointer to the canonical issue.
- **Clarify:** if an issue is unactionable, ask the one question that unblocks it
  rather than letting it rot.

## Break big work into sub-issues
For an epic, create a parent issue and link children with `sub_issue_write` (or a task
list `- [ ] #123` in the body where sub-issues aren't available). Each child should be
independently shippable and pass the same "can someone pick this up cold?" bar.

## Linking and closing
- **Link to the PR that fixes it:** the PR body's `Closes #N` (see
  github-pull-requests) auto-closes the issue on merge — prefer that over manual closing.
- **Close with a reason and a pointer:** "Fixed in #210" or "Closing as won't-fix
  because …". Never close silently — the next person needs the trail.
- **Reopen** rather than file a fresh issue when a regression recurs.

## Watch Out
1. **Search before you file.** A duplicate is worse than no issue — it splits the
   conversation.
2. **No reproduction = no bug report.** Steps + expected-vs-actual + evidence are the
   difference between an actionable issue and a help-desk message.
3. **Don't invent labels.** Match the repo's taxonomy; overlapping labels make triage
   harder, not easier.
4. **Close the loop.** An issue fixed by a merged PR but left open, or closed with no
   explanation, both erode trust in the tracker.
5. **Be frugal.** File issues that capture real, actionable work — not every passing
   thought.
