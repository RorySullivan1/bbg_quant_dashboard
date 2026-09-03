#!/usr/bin/env python3
"""Rough token estimator. Stdlib only. Companion to the token-optimizer skill.

There's no real tokenizer here (no tiktoken dependency), so this is a heuristic:
~4 characters per token. Treat the numbers as order-of-magnitude, not exact — they're
for deciding "read this whole / read a slice / delegate it", not for billing.

Usage:
  tokens.py estimate PATH [PATH ...]    Estimate tokens for files and/or directories.
  tokens.py estimate --text "STRING"    Estimate tokens for a literal string.

Heuristic thresholds it prints as guidance:
  < ~1.5k tokens   read freely
  ~1.5k–5k         fine, but don't read several at once
  > ~5k            read a slice (offset/limit) or delegate to the token-manager agent
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

CHARS_PER_TOKEN = 4.0
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".gz", ".bin",
            ".so", ".dylib", ".o", ".pyc", ".woff", ".woff2", ".ico", ".mp4"}


def est_tokens(chars: int) -> int:
    return round(chars / CHARS_PER_TOKEN)


def hint(tok: int) -> str:
    if tok < 1500:
        return "read freely"
    if tok < 5000:
        return "ok — avoid reading several together"
    return "SLICE (offset/limit) or DELEGATE to token-manager"


def file_stats(p: Path) -> tuple[int, int]:
    """Return (bytes, lines). Bytes proxy for chars."""
    try:
        data = p.read_bytes()
    except OSError:
        return (0, 0)
    return (len(data), data.count(b"\n") + 1)


def cmd_estimate(args: argparse.Namespace) -> int:
    if args.text is not None:
        tok = est_tokens(len(args.text))
        print(f"~{tok:,} tokens  ({len(args.text):,} chars)  [{hint(tok)}]")
        return 0
    if not args.paths:
        print("error: provide PATH(s) or --text", file=sys.stderr)
        return 2

    grand_chars = 0
    rows: list[tuple[str, int, int, int]] = []  # name, bytes, lines, tokens
    for raw in args.paths:
        p = Path(raw)
        if p.is_dir():
            sub_chars = 0
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix.lower() not in SKIP_EXT:
                    b, _ = file_stats(f)
                    sub_chars += b
            rows.append((f"{raw}/ (dir)", sub_chars, 0, est_tokens(sub_chars)))
            grand_chars += sub_chars
        elif p.is_file():
            b, ln = file_stats(p)
            rows.append((raw, b, ln, est_tokens(b)))
            grand_chars += b
        else:
            rows.append((f"{raw} (missing)", 0, 0, 0))

    width = max((len(r[0]) for r in rows), default=10)
    for name, b, ln, tok in rows:
        line_part = f"{ln:>6} lines  " if ln else " " * 13
        print(f"  {name:<{width}}  ~{tok:>7,} tok  {line_part}({b:,} B)  [{hint(tok)}]")
    if len(rows) > 1:
        gt = est_tokens(grand_chars)
        print(f"  {'TOTAL':<{width}}  ~{gt:>7,} tok  ({grand_chars:,} B)  [{hint(gt)}]")
    print("\n(rough estimate: ~4 chars/token, no real tokenizer)")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Rough token estimator")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("estimate", help="estimate tokens for files/dirs/text")
    e.add_argument("paths", nargs="*")
    e.add_argument("--text", default=None)
    e.set_defaults(func=cmd_estimate)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
