---
name: github-releases
description: >
  Expert at cutting GitHub releases — versioning, tagging, and writing release notes
  that tell users what changed and whether to upgrade. Use this skill whenever the user
  wants to create or plan a release: choosing the next semver number, deciding
  major/minor/patch, tagging, drafting release notes or a CHANGELOG entry, grouping
  merged PRs into highlights, marking a pre-release/draft, or attaching build artifacts.
  Trigger on "cut a release", "tag v2.0", "what version is this", "write release
  notes", "update the changelog", "is this a major or minor", "draft the GitHub
  release", "publish a pre-release". Knows semver, Keep a Changelog, and
  Conventional-Commits-driven notes. Reads release state via the GitHub MCP tools
  (`list_releases`, `get_latest_release`, `get_release_by_tag`, `list_tags`); creates
  releases via `gh release create` or the API where the MCP server is read-only for
  releases. Pairs with github-pull-requests (the merged work) and github-issues.
---

# GitHub Releases Skill

A release is a promise about compatibility and a summary of value. Get the **version
number** right (it tells users how risky the upgrade is) and the **notes** right (they
tell users whether to bother). Everything else is mechanics.

## Pick the version — semantic versioning
Given the current version (check `get_latest_release` / `list_tags`), choose the bump by
the *nature* of the change, not its size:

| Bump | When | Example |
|---|---|---|
| **MAJOR** (`x`.0.0) | Any backward-incompatible change — removed/renamed API, changed behavior, dropped support | 1.4.2 → 2.0.0 |
| **MINOR** (x.`y`.0) | New, backward-compatible functionality | 1.4.2 → 1.5.0 |
| **PATCH** (x.y.`z`) | Backward-compatible bug fixes only | 1.4.2 → 1.4.3 |

- **`0.y.z`** is the unstable phase — minor *may* break; many projects treat `0.y`
  bumps as the breaking signal. Confirm the project's stance.
- **Pre-releases** append a label: `2.0.0-rc.1`, `2.0.0-beta.2`. Mark them as
  pre-release so they don't show as "Latest".
- If the project uses **Conventional Commits**, derive the bump: a `!`/`BREAKING CHANGE`
  → major, `feat:` → minor, `fix:` → patch.

## Tagging
- Tag name is conventionally `v`-prefixed (`v2.0.0`) — match the repo's existing tags
  (`list_tags`); consistency matters more than the prefix itself.
- Tag the exact merged commit you intend to ship; an annotated tag (`git tag -a`) records
  who/when/why.
- **Never move or delete a published tag.** People and build systems pin to it. A bad
  release gets a new patch tag, not a rewritten one.

## Write the release notes
Lead with why a user should care, then the details. Group by impact, not by PR order:

```markdown
## v1.5.0 — 2026-06-27

### Highlights
One or two sentences on the headline change.

### Added
- New `--retry` flag for the upload client (#210)

### Changed
- Backoff is now exponential by default (#214)

### Fixed
- Upload no longer loops forever on 503 (#212)

### Breaking
- `upload()` now raises `UploadError` instead of returning `None` — see migration below.

**Upgrade notes:** <migration steps, if any>

**Full changelog:** v1.4.2...v1.5.0
```

- Use **Keep a Changelog** sections (`Added / Changed / Deprecated / Removed / Fixed /
  Security`). A **Breaking** call-out + migration steps is non-negotiable for a major.
- Credit PRs/issues by number; GitHub auto-links them. GitHub's **auto-generated notes**
  (`generate_release_notes`) are a starting draft — curate them into highlights, don't
  ship the raw list.
- Maintain a `CHANGELOG.md` in parallel if the repo keeps one; keep an `Unreleased`
  section that you graduate on each release.

## Mechanics
- Read current state first: `get_latest_release`, `list_releases`, `list_tags`.
- Create the release with `gh release create v1.5.0 --title "…" --notes-file notes.md`
  (add `--prerelease`, `--draft`, or `--target <sha>` as needed), or the REST API. The
  GitHub MCP server here is read-oriented for releases — don't assume a create tool; fall
  back to `gh`/API and say so.
- Attach build artifacts (`--attach`/asset upload) when users consume binaries, not source.
- **Draft first** for anything significant; publish once CI is green and notes are reviewed.

## Watch Out
1. **The version number is a contract.** A breaking change shipped as a minor/patch
   silently breaks downstreams who trusted semver. When in doubt, it's a major.
2. **Never rewrite a published tag/release.** Fix-forward with a new version; mutating a
   release that people already pulled is worse than the original bug.
3. **Raw auto-generated notes aren't release notes.** A flat list of commit titles
   buries the one thing users need. Curate highlights and breaking changes.
4. **Pre-releases must be marked.** An unmarked `rc` showing as "Latest" sends untested
   bits to everyone pinning to latest.
