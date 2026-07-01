#!/usr/bin/env python
"""agents — inventory the subagents available for delegation.

A helper for the agent-finder skill. Custom-agent descriptions are usually already in
context, so reach for this only to grep a large pool or to inspect an agent's real
tools/model/scope before a borderline routing call.

Reads project agents from <root>/.claude/agents/*.md and user agents from
~/.claude/agents/*.md (project wins on a name collision), and always includes the
three built-ins (Explore, Plan, general-purpose).

    python .claude/skills/agent-finder/scripts/agents.py list          # all agents + built-ins
    python .claude/skills/agent-finder/scripts/agents.py search "vba"   # match name/desc/tools
    python .claude/skills/agent-finder/scripts/agents.py show NAME      # full definition + scope

Stdlib only. Project root is resolved from $CLAUDE_PROJECT_DIR (fallback: cwd). On
macOS/Linux invoke with `python3`.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

BUILTINS = [
    {
        "name": "Explore",
        "scope": "built-in",
        "tools": "read-only",
        "model": "haiku",
        "description": "Read-only codebase search and file discovery. Fast and cheap; "
        "pass a thoroughness level (quick / medium / very thorough).",
    },
    {
        "name": "Plan",
        "scope": "built-in",
        "tools": "read-only",
        "model": "inherit",
        "description": "Read-only research to gather context before proposing an "
        "implementation plan.",
    },
    {
        "name": "general-purpose",
        "scope": "built-in",
        "tools": "all",
        "model": "inherit",
        "description": "All tools; complex multi-step work needing both exploration and "
        "modification. The fallback when no specialist fits.",
    },
]


def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def project_root() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def agent_dirs() -> list[tuple[str, Path]]:
    """(scope, dir) pairs; project first so it wins on name collisions."""
    return [
        ("project", project_root() / ".claude" / "agents"),
        ("user", Path.home() / ".claude" / "agents"),
    ]


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Minimal YAML-frontmatter parse: scalar `key: value` and folded `key: >`/`|` blocks."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, text
    fm, body = lines[1:end], "\n".join(lines[end + 1 :])
    data: dict[str, str] = {}
    i = 0
    while i < len(fm):
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", fm[i])
        if not m:
            i += 1
            continue
        key, val = m.group(1), m.group(2).strip()
        if val in ("", ">", ">-", ">+", "|", "|-", "|+"):  # folded/literal/empty -> gather block
            block, j = [], i + 1
            while j < len(fm) and (fm[j].startswith((" ", "\t")) or fm[j].strip() == ""):
                block.append(fm[j].strip())
                j += 1
            data[key] = " ".join(b for b in block if b)
            i = j
        else:
            data[key] = val.strip().strip("\"'")
            i += 1
    return data, body


def load_custom_agents() -> dict[str, dict]:
    """name -> agent record; project scope wins over user scope."""
    found: dict[str, dict] = {}
    for scope, directory in agent_dirs():
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            try:
                fm, body = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            name = fm.get("name")
            if not name:  # not an agent file (e.g. README.md)
                continue
            if name in found:  # earlier scope (project) wins
                continue
            found[name] = {
                "name": name,
                "scope": scope,
                "tools": fm.get("tools", "(inherit all)"),
                "model": fm.get("model", "(inherit)"),
                "description": fm.get("description", ""),
                "path": path,
                "body": body.strip(),
            }
    return found


def all_agents() -> list[dict]:
    agents = list(BUILTINS)
    agents.extend(load_custom_agents().values())
    return agents


def first_sentence(text: str, limit: int = 240) -> str:
    text = " ".join(text.split())
    if not text:
        return "(no description)"
    cut = text[:limit]
    return cut + ("…" if len(text) > limit else "")


def print_row(agent: dict) -> None:
    meta = f"[{agent['scope']}]  tools={agent['tools']}  model={agent['model']}"
    print(f"{agent['name']}  {meta}")
    print(f"    {first_sentence(agent['description'])}")


def cmd_list(_args) -> int:
    for agent in all_agents():
        print_row(agent)
    return 0


def cmd_search(args) -> int:
    q = args.query.lower()
    hits = [
        a for a in all_agents()
        if q in a["name"].lower()
        or q in a["description"].lower()
        or q in str(a["tools"]).lower()
    ]
    if not hits:
        print(f"no agents match {args.query!r}", file=sys.stderr)
        return 0
    for agent in hits:
        print_row(agent)
    return 0


def cmd_show(args) -> int:
    target = args.name.lower()
    for agent in all_agents():
        if agent["name"].lower() == target:
            print(f"name:  {agent['name']}")
            print(f"scope: {agent['scope']}")
            print(f"tools: {agent['tools']}")
            print(f"model: {agent['model']}")
            if agent.get("path"):
                print(f"path:  {agent['path']}")
            print("\ndescription:")
            print(f"  {first_sentence(agent['description'], 10_000)}")
            if agent.get("body"):
                print("\nsystem prompt:\n")
                print(agent["body"])
            return 0
    print(f"no agent named {args.name!r}; run `agents.py list`", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    parser = argparse.ArgumentParser(prog="agents.py", description="inventory subagents")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list all agents + built-ins").set_defaults(func=cmd_list)
    sp = sub.add_parser("search", help="match name/description/tools")
    sp.add_argument("query")
    sp.set_defaults(func=cmd_search)
    sp = sub.add_parser("show", help="full definition + scope for one agent")
    sp.add_argument("name")
    sp.set_defaults(func=cmd_show)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
