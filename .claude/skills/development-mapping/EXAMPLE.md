# Development map — worked example

> **Illustrative only.** A compact, end-to-end example of the `development-mapping`
> output for a *hypothetical* project (a small URL-shortener service), so you can see the
> shape without it being confused for any real plan. A live map lives in `.meta/roadmap/`;
> this file just teaches the format. Read `SKILL.md` for the *how*; this is the *what it
> looks like*.

The objective: **"a self-hostable URL shortener with an API and a usage dashboard."**
Decomposed into stages → versions → milestones, sequenced walking-skeleton-first and
de-risking the storage choice early.

---

## `INDEX.md` (the dashboard)

```markdown
# Development Map — shortn

## Objective
A self-hostable URL shortener: a redirect service, a create/manage API, and a usage dashboard.

## Stages
1. **Skeleton** — one end-to-end slice: create a short link, follow it. *Milestone: a link redirects in a deployed instance.*
2. **API** — full create/manage surface + auth. *Milestone: a client can CRUD links over the API.*
3. **Dashboard** — usage views over real data. *Milestone: an owner sees click stats for their links.*

## Versions
| Version | Stage | Goal (one line)                          | Status |
|---------|-------|------------------------------------------|--------|
| v0.1.0  | 01    | Walking skeleton: POST a URL → 302 follow | planned ← cursor |
| v0.2.0  | 02    | Full link CRUD + API-key auth             | planned |
| v0.3.0  | 02    | Custom slugs + expiry                     | planned |
| v0.4.0  | 03    | Click capture + per-link stats view       | planned (sketch) |
```

## `stages/01-skeleton/STAGE.md`

```markdown
# Stage 01 — Skeleton  ◀ current stage

**Goal:** prove the whole path end-to-end with the thinnest possible slice — create a short
code for a URL and redirect on it — so the architecture and the storage choice are validated
before any breadth is built.

**Versions:** v0.1.0 (walking skeleton).

**Milestone (stage exit):** a deployed instance turns a POSTed URL into a short code and
302-redirects to the original. The riskiest decision (datastore) is exercised by real traffic.
```

## `stages/01-skeleton/v0.1.0.md`  (a version card — note it's exactly the `.meta/version` shape)

```markdown
# version: v0.1.0
status: planned

## Goals
- Accept a URL via POST and return a short code.
- Redirect (302) from /<code> to the original URL.

## Objectives / acceptance
- An integration test posts a URL, follows the code, and lands on the original.
- Codes persist across a process restart (storage is real, not in-memory).
- Deploys to one environment via the project's standard path; no manual steps.
```

---

## Why this sequence (the reasoning the skill teaches)
- **Walking skeleton first (v0.1.0):** redirect + create is the thinnest slice that exercises
  every layer (HTTP, storage, deploy). It de-risks the architecture before any feature breadth.
- **De-risk storage early:** the acceptance bar forces *real* persistence in v0.1.0, so a wrong
  datastore choice surfaces while it's cheap to change — not in stage 3.
- **Vertical over horizontal:** each version ships a user-visible capability (follow a link →
  manage links → see stats), never a half-built layer no one can exercise.
- **Detail the next stage, sketch the rest:** stages 01–02 have cards; v0.4.0 is a one-line
  intention until stage 02 is near done.
- **Checkable acceptance:** every criterion above is something `goal-auditor` can verify against
  a diff (a test exists, persistence survives restart, the deploy is hands-off) — not "make it good."
