#!/usr/bin/env python3
"""Glossary migration tool — scan codebase for deprecated/retired terms.

Run before deprecating a term to assess blast radius. Run after fixing
all occurrences to confirm the codebase is clean before promoting to 'retired'.

Usage:
    python tools/migrate_glossary.py --term taxonomy
    python tools/migrate_glossary.py --deprecated
    python tools/migrate_glossary.py --retired
    python tools/migrate_glossary.py --all

Exit 0 if clean, exit 1 if hits found.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from check_glossary import GlossaryRule, parse_glossary

ROOT = Path(__file__).parent.parent
SKIP_DIRS = {".venv", "node_modules", ".git", "__pycache__", ".mypy_cache", ".pytest_cache"}


def _scan_codebase(terms: list[str]) -> dict[str, list[tuple[Path, int, str]]]:
    """Return {term: [(path, lineno, line), ...]} for every hit in the codebase."""
    hits: dict[str, list[tuple[Path, int, str]]] = {t: [] for t in terms}
    patterns = {t: re.compile(r"\b" + re.escape(t) + r"\b", re.IGNORECASE) for t in terms}

    for path in ROOT.rglob("*"):
        if path.suffix not in (".py", ".md"):
            continue
        if any(skip in path.parts for skip in SKIP_DIRS):
            continue
        try:
            for i, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
                for term, pattern in patterns.items():
                    if pattern.search(line):
                        hits[term].append((path, i, line.strip()))
        except (PermissionError, OSError):
            continue

    return hits


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan codebase for deprecated/retired glossary terms."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--term", metavar="TERM", help="Scan for a specific banned synonym or canonical name"
    )
    group.add_argument("--deprecated", action="store_true", help="Scan for all deprecated terms")
    group.add_argument("--retired", action="store_true", help="Scan for all retired terms")
    group.add_argument(
        "--all", action="store_true", help="Scan for all deprecated and retired terms"
    )
    args = parser.parse_args()

    rules = parse_glossary()

    if args.term:
        target_rules = [r for r in rules if args.term in r.banned or args.term == r.canonical]
        if not target_rules:
            print(f"No glossary entry found with banned term or canonical name: '{args.term}'")
            return 1
    elif args.deprecated:
        target_rules = [r for r in rules if r.status == "deprecated" and r.banned]
    elif args.retired:
        target_rules = [r for r in rules if r.status == "retired" and r.banned]
    else:
        target_rules = [r for r in rules if r.status in ("deprecated", "retired") and r.banned]

    if args.term and target_rules:
        print(
            f"Matched rule: `{target_rules[0].canonical}` — scanning all banned terms: {target_rules[0].banned}\n"
        )

    # Collect all banned terms to scan (flatten across rules)
    all_banned: dict[str, GlossaryRule] = {}
    for rule in target_rules:
        for b in rule.banned:
            all_banned[b] = rule

    if not all_banned:
        print("No banned terms found for the given filter.")
        return 0

    print(f"Scanning codebase for {len(all_banned)} banned term(s)...\n")
    hits = _scan_codebase(list(all_banned.keys()))

    total = 0
    for term, occurrences in hits.items():
        if not occurrences:
            continue
        rule = all_banned[term]
        replacement = rule.replaced_by or rule.canonical
        print(f"  {term!r} [{rule.status}]  ->  use: `{replacement}`")
        for path, lineno, line in occurrences:
            rel = path.relative_to(ROOT)
            print(f"    {rel}:{lineno}: {line}")
        print()
        total += len(occurrences)

    if total == 0:
        print("Clean — no deprecated/retired terms found.")
        return 0

    print(f"{total} occurrence(s) found. Fix these, then update the glossary entry status.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
