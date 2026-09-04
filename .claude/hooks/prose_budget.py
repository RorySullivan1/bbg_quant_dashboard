#!/usr/bin/env python3
"""Measure code commentary against a per-scope budget, and report what overruns it.

Enforces the scope table in the `coding-standards` skill: a file states its purpose, a
class may be verbose, a function is limited but descriptive, inline comments are for the
non-obvious only.

Two entry points over one measurer. As a PostToolUse hook it reports on the file just
edited; as a library (`scan_source`, `scan_tree`) it hands findings to a project's CI
gate. An advisory hook cannot be a gate — it must never block — and a second measurer
written for the gate is how the two come to disagree about the rule.

OPT IN BY PRESENCE: silent unless the project has a `.claude/prose-budget.json`.
ADVISORY and NON-MUTATING: it never edits a file or blocks a call. FAILS SAFE: on any
bad payload, unparseable source or missing config it reports nothing.

Python only, via `ast` and `tokenize` — stdlib parsing is exact where a cross-language
regex would spend its accuracy on false positives. `_SCANNERS` is the extension point.
See `.claude/hooks/README.md` for the config keys and the baseline format.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import re
import os
import sys
import tokenize
from dataclasses import dataclass, replace
from pathlib import Path

#: Shipped defaults. Loose on purpose — they encode the *ordering* the standard states
#: (a class may be verbose, a function may not) rather than a recommended number, since
#: a cap that fits one codebase is wrong for the next. A project tunes them down.
DEFAULT_BUDGETS = {"module": 20, "class": 30, "function": 15, "comment_run": 5,
                   "attribute": 30}

CONFIG_NAME = "prose-budget.json"
MAX_FINDINGS = 8
SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".mypy_cache"}


@dataclass(frozen=True)
class Finding:
    """One scope whose prose exceeds its budget.

    `location` is the baseline key, and it is deliberately not line-based: a docstring
    keyed by line number moves whenever anything above it does, so an unrelated edit
    would break a baseline entry and fail the gate for a reason that has nothing to do
    with prose. Keying on the qualified name churns only when the code itself is
    renamed or restructured, which is when re-baselining is the correct answer anyway.
    """

    path: str
    scope: str
    name: str
    line: int
    measured: int
    budget: int
    unit: str = "lines"

    @property
    def location(self) -> str:
        return f"{self.path}::{self.scope}:{self.name}"

    def describe(self) -> str:
        return (f"{self.path}:{self.line} {self.scope} {self.name} — "
                f"{self.measured:,} {self.unit}, budget {self.budget:,}")


@dataclass(frozen=True)
class Budgets:
    """Resolved per-scope caps plus the baseline of locations already exempt.

    A baseline entry is a location mapped to a one-line reason. It exists so a check
    can ship green against a codebase that predates it — one arriving red teaches
    everyone to switch it off — and it is meant to shrink to nothing. Nothing here
    grows it; a consumer that wants a ratchet asserts that separately.
    """

    module: int = DEFAULT_BUDGETS["module"]
    cls: int = DEFAULT_BUDGETS["class"]
    function: int = DEFAULT_BUDGETS["function"]
    comment_run: int = DEFAULT_BUDGETS["comment_run"]
    attribute: int = DEFAULT_BUDGETS["attribute"]
    claude_md_lines: int = 0
    claude_md_chars: int = 0
    baseline: frozenset[str] = frozenset()
    include: tuple[str, ...] = ()

    def cap(self, scope: str) -> int:
        return {"module": self.module, "class": self.cls,
                "function": self.function, "comment_run": self.comment_run,
                "attribute": self.attribute}[scope]


def project_root() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())


def load_budgets(root: Path | None = None) -> Budgets | None:
    """Read the project's config, or return None when the project has not adopted this.

    None is the opt-out and every caller must honour it — the config file is the
    adoption marker, not merely a place to override numbers.
    """
    root = root or project_root()
    config_path = root / ".claude" / CONFIG_NAME
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None

    budgets = Budgets()
    for key, field in (("module", "module"), ("class", "cls"),
                       ("function", "function"), ("comment_run", "comment_run"),
                       ("attribute", "attribute")):
        value = raw.get(key)
        if isinstance(value, int) and value > 0:
            budgets = replace(budgets, **{field: value})

    claude_md = raw.get("claude_md")
    if isinstance(claude_md, dict):
        lines_cap, chars_cap = claude_md.get("lines"), claude_md.get("chars")
        if isinstance(lines_cap, int) and lines_cap > 0:
            budgets = replace(budgets, claude_md_lines=lines_cap)
        if isinstance(chars_cap, int) and chars_cap > 0:
            budgets = replace(budgets, claude_md_chars=chars_cap)

    baseline: frozenset[str] = frozenset()
    baseline_ref = raw.get("baseline")
    if isinstance(baseline_ref, str):
        try:
            entries = json.loads((root / baseline_ref).read_text(encoding="utf-8"))
            if isinstance(entries, dict):
                baseline = frozenset(entries)
        except (OSError, json.JSONDecodeError, ValueError):
            baseline = frozenset()

    include = raw.get("include")
    if isinstance(include, list):
        budgets = replace(budgets, include=tuple(str(p) for p in include))
    return replace(budgets, baseline=baseline)


def _docstring_span(node: ast.AST) -> tuple[int, int] | None:
    body = getattr(node, "body", None)
    if not body:
        return None
    first = body[0]
    if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)):
        return None
    end = first.value.end_lineno or first.value.lineno
    return first.value.lineno, end - first.value.lineno + 1


def _qualnames(tree: ast.Module) -> list[tuple[str, str, ast.AST]]:
    """Every class and function in the tree, paired with its dotted qualified name."""
    found: list[tuple[str, str, ast.AST]] = []

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                name = f"{prefix}{child.name}"
                found.append(("class", name, child))
                walk(child, f"{name}.")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}{child.name}"
                found.append(("function", name, child))
                walk(child, f"{name}.")
            else:
                walk(child, prefix)

    walk(tree, "")
    return found


def _enclosing(scopes: list[tuple[str, str, ast.AST]], line: int) -> str:
    """The innermost class or function containing `line`, or "module"."""
    best, best_size = "module", None
    for _, name, node in scopes:
        start, end = node.lineno, getattr(node, "end_lineno", node.lineno)
        if start <= line <= end:
            size = end - start
            if best_size is None or size < best_size:
                best, best_size = name, size
    return best


def _comment_runs(source: str, scopes: list[tuple[str, str, ast.AST]]) -> list[tuple[str, int, int]]:
    """Runs of consecutive own-line comments, as (enclosing scope, first line, length).

    Trailing comments are excluded: `count += 1  # increment` is a different defect and
    a run of them is not a prose block. `tokenize` is what distinguishes the two — a
    line-based scan cannot, because a `#` inside a string looks identical.
    """
    lines = source.splitlines()
    own_line: list[int] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT and not lines[token.start[0] - 1][:token.start[1]].strip():
            own_line.append(token.start[0])

    runs: list[tuple[str, int, int]] = []
    start = previous = None

    def close(a: int, b: int) -> None:
        runs.append((_enclosing(scopes, a), a, b - a + 1))

    for line in own_line:
        if previous is not None and line == previous + 1:
            previous = line
            continue
        if start is not None:
            close(start, previous)
        start = previous = line
    if start is not None:
        close(start, previous)
    return runs


def _run_slug(source: str, line: int, length: int) -> str:
    """A short content hash identifying one comment run, for its baseline key.

    Content-derived so the key survives line moves and neighbouring runs being
    added or removed — it churns only when the comment itself is rewritten, which
    is when re-baselining is the correct answer anyway. Two byte-identical runs in
    one scope share a key; a baseline entry then exempts both, which is acceptable
    for an exemption that names the text it exempts.
    """
    block = "\n".join(l.strip() for l in source.splitlines()[line - 1 : line - 1 + length])
    return hashlib.sha1(block.encode("utf-8")).hexdigest()[:8]


def _is_attribute_doc(source: str, line: int, length: int) -> str | None:
    """The name a ``#:`` run documents, or None when it is an ordinary comment block.

    ``#:`` before an assignment is Sphinx's way of documenting a module constant —
    API documentation, not inline prose, and measuring it as a comment block would
    force correct documentation to be deleted. Its name is also a stable baseline
    key, for `Finding.location`'s reason.
    """
    lines = source.splitlines()
    block = lines[line - 1 : line - 1 + length]
    if not block or not all(l.strip().startswith("#:") for l in block if l.strip()):
        return None
    following = next((l for l in lines[line - 1 + length :] if l.strip()), "")
    name = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*[:=]", following)
    return name.group(1) if name else None


def scan_python(source: str, path: str, budgets: Budgets) -> list[Finding]:
    """Measure one Python source string. Raises nothing a caller must catch but SyntaxError."""
    tree = ast.parse(source)
    scopes = _qualnames(tree)
    findings: list[Finding] = []

    span = _docstring_span(tree)
    if span and span[1] > budgets.cap("module"):
        findings.append(Finding(path, "module", Path(path).name, span[0], span[1], budgets.cap("module")))

    for scope, name, node in scopes:
        span = _docstring_span(node)
        if span and span[1] > budgets.cap(scope):
            findings.append(Finding(path, scope, name, span[0], span[1], budgets.cap(scope)))

    for enclosing, line, length in _comment_runs(source, scopes):
        attribute = _is_attribute_doc(source, line, length)
        scope = "attribute" if attribute else "comment_run"
        if attribute:
            # Qualified by the enclosing scope: two classes may document
            # same-named attributes, and their exemptions must not collide.
            name = attribute if enclosing == "module" else f"{enclosing}.{attribute}"
        else:
            name = f"{enclosing}#{_run_slug(source, line, length)}"
        if length > budgets.cap(scope):
            findings.append(Finding(path, scope, name, line, length, budgets.cap(scope)))

    return [f for f in findings if f.location not in budgets.baseline]


#: Suffix to scanner. The extension point named in the module docstring: a language
#: with no entry here is silently skipped, which is the correct answer for a measurer
#: that would otherwise be guessing.
_SCANNERS = {".py": scan_python}


def scan_source(source: str, path: str, budgets: Budgets) -> list[Finding]:
    """Measure one file's text. Returns [] for an unsupported language or unparseable source."""
    scanner = _SCANNERS.get(Path(path).suffix)
    if scanner is None:
        return []
    try:
        return scanner(source, path, budgets)
    except (SyntaxError, ValueError, tokenize.TokenError, IndentationError, RecursionError):
        return []


def scan_claude_md(source: str, path: str, budgets: Budgets) -> list[Finding]:
    """Measure a CLAUDE.md against the always-loaded-file caps. [] unless adopted.

    CLAUDE.md is prose that loads into every session, so its size is a per-session
    tax — the same argument session-memory's BUDGETS make for the memory index,
    which has its own check in memory.py. Whole-file caps only: scope tables are
    for code, and a markdown "scope" would be a guess.
    """
    findings: list[Finding] = []
    name = Path(path).name
    if budgets.claude_md_lines:
        measured = len(source.splitlines())
        if measured > budgets.claude_md_lines:
            findings.append(Finding(path, "claude_md", name, 1, measured, budgets.claude_md_lines))
    if budgets.claude_md_chars:
        if len(source) > budgets.claude_md_chars:
            findings.append(Finding(path, "claude_md", name, 1, len(source), budgets.claude_md_chars, unit="chars"))
    return [f for f in findings if f.location not in budgets.baseline]


def scan_tree(root: Path | None = None, budgets: Budgets | None = None) -> list[Finding]:
    """Measure every supported file under the configured roots. The CI gate's entry point."""
    root = root or project_root()
    budgets = budgets or load_budgets(root)
    if budgets is None:
        return []
    bases = [root / p for p in budgets.include] if budgets.include else [root]
    findings: list[Finding] = []
    for base in bases:
        if budgets.claude_md_lines or budgets.claude_md_chars:
            for path in sorted(base.rglob("CLAUDE.md")):
                if SKIP_DIRS & set(path.parts):
                    continue
                try:
                    source = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                findings.extend(scan_claude_md(source, path.relative_to(root).as_posix(), budgets))
        for suffix in _SCANNERS:
            for path in sorted(base.rglob(f"*{suffix}")):
                if SKIP_DIRS & set(path.parts):
                    continue
                try:
                    source = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                findings.extend(scan_source(source, path.relative_to(root).as_posix(), budgets))
    return findings


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        file_path = (payload.get("tool_input") or {}).get("file_path")
        if not file_path:
            return 0
        root = project_root()
        budgets = load_budgets(root)
        if budgets is None:
            return 0
        path = Path(file_path)
        relative = path.relative_to(root).as_posix() if path.is_absolute() else path.as_posix()
        if path.name == "CLAUDE.md":
            findings = scan_claude_md(path.read_text(encoding="utf-8"), relative, budgets)
        elif path.suffix in _SCANNERS:
            findings = scan_source(path.read_text(encoding="utf-8"), relative, budgets)
        else:
            return 0
    except Exception:
        return 0

    if not findings:
        return 0
    shown = findings[:MAX_FINDINGS]
    lines = [f"prose over budget in {relative} (advisory — see the coding-standards skill):"]
    lines += [f"  {f.describe()}" for f in shown]
    if len(findings) > len(shown):
        lines.append(f"  ... and {len(findings) - len(shown)} more not listed")
    lines.append("  Trim to the scope's rule, or route the reasoning with knowledge-router.")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
