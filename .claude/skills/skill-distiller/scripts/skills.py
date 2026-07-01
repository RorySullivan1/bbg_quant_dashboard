#!/usr/bin/env python3
"""Inventory existing skills, dedupe a candidate against them, and manage the
candidate queue. Stdlib only. Companion to the skill-distiller SKILL.md.

Subcommands:
  list                         Existing skills (winning definition per name) + scope.
  similar "DESC"  [--limit N]  Lexically rank existing skills against a candidate
                               description. Surfaces likely duplicate/extend targets.
  candidates                   Print the candidate queue (CANDIDATES.md).
  add-candidate --name N --desc D [--why W] [--source S]
                               Append a structured stub to the candidate queue.

Skill discovery (highest precedence first): project .claude/skills walking up from cwd
to repo root (closest wins), then ~/.claude/skills. Each skill is a directory holding a
SKILL.md. Similarity is purely lexical (token overlap), not semantic — treat it as a
prompt to look, not a verdict.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import sys
from pathlib import Path

KEY_RE = re.compile(r"^([A-Za-z][\w-]*):\s?(.*)$")
BLOCK_RE = re.compile(r"^[>|][+-]?\s*$")
WORD_RE = re.compile(r"[a-z0-9]+")
STOP = {
    "the", "a", "an", "and", "or", "to", "of", "for", "in", "on", "with", "use",
    "used", "using", "this", "that", "when", "whenever", "skill", "claude", "is",
    "are", "be", "it", "its", "as", "by", "at", "from", "into", "any", "should",
    "user", "wants", "asks", "make", "sure", "even", "if", "they", "dont", "you",
}


def repo_root(start: Path) -> Path:
    cur = start.resolve()
    for p in [cur, *cur.parents]:
        if (p / ".git").exists():
            return p
    return cur


def skill_dirs() -> list[tuple[Path, str]]:
    cwd = Path.cwd().resolve()
    root = repo_root(cwd)
    dirs: list[tuple[Path, str]] = []
    p = cwd
    while True:
        d = p / ".claude" / "skills"
        if d.is_dir():
            dirs.append((d, "project" if p == root else f"project:{p.relative_to(root)}"))
        if p == root:
            break
        p = p.parent
    user = Path.home() / ".claude" / "skills"
    if user.is_dir():
        dirs.append((user, "user"))
    return dirs


def candidate_file() -> Path:
    cwd = Path.cwd().resolve()
    root = repo_root(cwd)
    return root / ".claude" / "skills" / "_candidates" / "CANDIDATES.md"


def parse_frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}
    fm: dict[str, str] = {}
    i = 1
    while i < end:
        m = KEY_RE.match(lines[i])
        if not m:
            i += 1
            continue
        key, val = m.group(1), m.group(2).strip()
        if val == "" or BLOCK_RE.match(val):
            block, j = [], i + 1
            while j < end and (lines[j].strip() == "" or lines[j][:1] in (" ", "\t")):
                block.append(lines[j].strip())
                j += 1
            fm[key] = " ".join(b for b in block if b).strip()
            i = j
        else:
            fm[key] = val.strip("'\"")
            i += 1
    return fm


def find_skill_mds(d: Path) -> list[Path]:
    """All SKILL.md under d, following symlinked skill dirs (the factory single-sources
    operational skills as symlinks into example-project, so plain rglob would miss them)."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(d, followlinks=True):
        if "_candidates" in dirnames:
            dirnames.remove("_candidates")
        if "SKILL.md" in filenames:
            found.append(Path(dirpath) / "SKILL.md")
    return found


def load_skills() -> dict[str, dict]:
    winners: dict[str, dict] = {}
    for d, scope in skill_dirs():
        for skill_md in sorted(find_skill_mds(d)):
            if "_candidates" in skill_md.parts:
                continue
            try:
                fm = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
            except OSError:
                continue
            name = fm.get("name") or skill_md.parent.name
            if name not in winners:
                winners[name] = {
                    "name": name, "scope": scope, "path": str(skill_md),
                    "description": fm.get("description", ""),
                }
    return winners


def tokens(text: str) -> set[str]:
    return {w for w in WORD_RE.findall(text.lower()) if w not in STOP and len(w) > 2}


def _trunc(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def cmd_list(_: argparse.Namespace) -> int:
    skills = load_skills()
    if not skills:
        print("(no skills found in project or user scope)")
        return 0
    for rec in sorted(skills.values(), key=lambda r: r["name"]):
        print(f"  {rec['name']:<26} [{rec['scope']}]  {_trunc(rec['description'], 60)}")
    return 0


def cmd_similar(args: argparse.Namespace) -> int:
    cand = tokens(args.desc)
    if not cand:
        print("(candidate description has no distinctive tokens)", file=sys.stderr)
        return 0
    scored = []
    for rec in load_skills().values():
        st = tokens(f"{rec['name']} {rec['description']}")
        if not st:
            continue
        inter = cand & st
        jacc = len(inter) / len(cand | st)
        scored.append((jacc, sorted(inter), rec))
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        print("No existing skills to compare against — candidate is net-new.")
        return 0
    for jacc, shared, rec in scored[: args.limit or 8]:
        if jacc >= 0.40:
            verdict = "LIKELY DUPLICATE / extend this one"
        elif jacc >= 0.18:
            verdict = "overlaps — check boundary, maybe extend"
        else:
            verdict = "distinct"
        print(f"  {jacc:4.0%}  {rec['name']:<24} {verdict}")
        if shared:
            print(f"         shared: {', '.join(shared[:8])}")
    print("\n(lexical overlap only — read the top matches before deciding)")
    return 0


def cmd_candidates(_: argparse.Namespace) -> int:
    cf = candidate_file()
    if not cf.exists():
        print("(no candidate queue yet)")
        return 0
    print(cf.read_text(encoding="utf-8"), end="")
    return 0


def cmd_add_candidate(args: argparse.Namespace) -> int:
    cf = candidate_file()
    cf.parent.mkdir(parents=True, exist_ok=True)
    if not cf.exists():
        cf.write_text("# Skill candidates\n\n> Flagged-but-not-yet-built skill ideas. "
                      "Review deliberately; build the worthwhile ones with /add-skill.\n",
                      encoding="utf-8")
    stamp = _dt.datetime.now().strftime("%Y-%m-%d")
    block = (f"\n## {args.name}  ({stamp})\n"
             f"- description: {args.desc}\n"
             f"- why significant: {args.why or '(fill in)'}\n"
             f"- source: {args.source or '(session/plan)'}\n")
    with cf.open("a", encoding="utf-8") as fh:
        fh.write(block)
    print(f"Appended candidate '{args.name}' to {cf}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Skill inventory / dedupe / candidate queue")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list existing skills").set_defaults(func=cmd_list)

    s = sub.add_parser("similar", help="rank existing skills against a candidate desc")
    s.add_argument("desc")
    s.add_argument("--limit", type=int, default=0)
    s.set_defaults(func=cmd_similar)

    sub.add_parser("candidates", help="print the candidate queue").set_defaults(func=cmd_candidates)

    a = sub.add_parser("add-candidate", help="append a stub to the candidate queue")
    a.add_argument("--name", required=True)
    a.add_argument("--desc", required=True)
    a.add_argument("--why", default="")
    a.add_argument("--source", default="")
    a.set_defaults(func=cmd_add_candidate)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
