#!/usr/bin/env python3
"""Glossary enforcement checker — scans files for banned synonyms.

Parses docs/foundation/glossary.md to extract banned term rules,
then scans provided files for violations. Called by pre-commit hook.

Exit 0 if clean, exit 1 if any violations found.

Usage:
    python tools/check_glossary.py file1.py file2.md ...
    python tools/check_glossary.py $(find . -name "*.py" -o -name "*.md" | grep -v .venv)
"""

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

GLOSSARY_PATH = Path(__file__).parent.parent / "docs" / "foundation" / "glossary.md"
GLOSSARY_SKIP = (Path(__file__).parent.parent / "docs" / "foundation" / "glossary.md").resolve()


@dataclass
class GlossaryRule:
    canonical: str
    banned: list[str] = field(default_factory=list)
    status: str = "active"
    replaced_by: str | None = None


@dataclass
class Violation:
    status: str  # "active", "deprecated", or "retired"
    lineno: int
    line: str
    banned_term: str
    canonical: str
    scan_type: str  # "prose" or "identifier"
    replaced_by: str | None = None


def parse_glossary(path: Path = GLOSSARY_PATH) -> list[GlossaryRule]:
    """Parse glossary.md and return all rules with banned terms."""
    rules: list[GlossaryRule] = []
    current: GlossaryRule | None = None

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()

        m = re.match(r"^### `(.+?)`", line)
        if m:
            if current is not None:
                rules.append(current)
            current = GlossaryRule(canonical=m.group(1))
            continue

        if current is None:
            continue

        m = re.match(r"^\*\*Banned:\*\*\s*(.+)", line)
        if m:
            raw = m.group(1).strip()
            if raw.lower() != "(none)":
                current.banned = [t.strip() for t in raw.split(",") if t.strip()]
            continue

        m = re.match(r"^\*\*Status:\*\*\s*(\w+)", line)
        if m:
            current.status = m.group(1).strip()
            continue

        m = re.match(r"^\*\*Replaced by:\*\*\s*`(.+?)`", line)
        if m:
            current.replaced_by = m.group(1).strip()
            continue

    if current is not None:
        rules.append(current)

    return rules


def _extract_prose_lines(path: Path) -> list[tuple[int, str]]:
    """Return (1-based lineno, text) for prose content to scan.

    For .md files: all lines.
    For .py files: comment lines and content inside triple-quoted strings.
    """
    if path.suffix == ".md":
        return [(i + 1, line) for i, line in enumerate(path.read_text().splitlines())]

    lines = path.read_text().splitlines()
    result: list[tuple[int, str]] = []
    in_docstring = False
    docstring_char: str | None = None

    for i, line in enumerate(lines):
        lineno = i + 1
        stripped = line.strip()

        if not in_docstring:
            for q in ('"""', "'''"):
                if q in stripped:
                    occurrences = stripped.count(q)
                    if occurrences >= 2:
                        result.append((lineno, line))
                    else:
                        in_docstring = True
                        docstring_char = q
                        result.append((lineno, line))
                    break
            else:
                if "#" in line:
                    comment_start = line.index("#")
                    result.append((lineno, line[comment_start:]))
        else:
            result.append((lineno, line))
            if docstring_char and docstring_char in stripped:
                in_docstring = False
                docstring_char = None

    return result


def _split_identifier(name: str) -> list[str]:
    """Split a snake_case or camelCase identifier into lowercase tokens."""
    parts = name.split("_")
    tokens: list[str] = []
    for part in parts:
        if not part:
            continue
        expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", part)
        expanded = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", expanded)
        tokens.extend(t.lower() for t in expanded.split() if t)
    return tokens


def _check_identifier_for_banned(identifier: str, banned_term: str) -> bool:
    """Return True if a single-word banned term appears as a token in the identifier."""
    banned_words = banned_term.lower().split()
    if len(banned_words) != 1:
        return False
    tokens = _split_identifier(identifier)
    return banned_words[0] in tokens


def scan_file(path: Path, rules: list[GlossaryRule]) -> list[Violation]:
    """Scan a file for glossary violations.

    Checks active, deprecated, and retired entries — all banned synonyms are enforced.
    """
    violations: list[Violation] = []
    enforced_rules = [r for r in rules if r.banned]

    # --- Prose scan ---
    prose_lines = _extract_prose_lines(path)
    for lineno, text in prose_lines:
        for rule in enforced_rules:
            for banned in rule.banned:
                pattern = r"\b" + re.escape(banned) + r"\b"
                if re.search(pattern, text, re.IGNORECASE):
                    violations.append(
                        Violation(
                            status=rule.status,
                            lineno=lineno,
                            line=text.strip(),
                            banned_term=banned,
                            canonical=rule.canonical,
                            scan_type="prose",
                            replaced_by=rule.replaced_by,
                        )
                    )

    # --- Identifier scan (Python only) ---
    if path.suffix == ".py":
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            for m in re.finditer(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b", line):
                identifier = m.group(1)
                for rule in enforced_rules:
                    for banned in rule.banned:
                        if _check_identifier_for_banned(identifier, banned):
                            already = any(
                                v.lineno == lineno
                                and v.banned_term == banned
                                and v.scan_type == "prose"
                                for v in violations
                            )
                            if not already:
                                violations.append(
                                    Violation(
                                        status=rule.status,
                                        lineno=lineno,
                                        line=line.strip(),
                                        banned_term=banned,
                                        canonical=rule.canonical,
                                        scan_type="identifier",
                                        replaced_by=rule.replaced_by,
                                    )
                                )

    return violations


def _format_violation(path: Path, v: Violation) -> str:
    replacement = f" (use: `{v.replaced_by}`)" if v.replaced_by else f" (use: `{v.canonical}`)"
    return f"  {path}:{v.lineno}: [{v.status}] '{v.banned_term}'{replacement}\n" f"    {v.line}"


def main(argv: list[str] | None = None) -> int:
    files = [Path(f) for f in (argv if argv is not None else sys.argv[1:])]
    if not files:
        print("check_glossary.py: no files provided")
        return 0

    # Skip the glossary itself — it contains banned terms by definition
    files = [f for f in files if f.resolve() != GLOSSARY_SKIP]

    rules = parse_glossary()
    if not rules:
        print("  WARNING: glossary.md parsed 0 rules — check file path")
        return 0

    all_violations: list[tuple[Path, Violation]] = []
    for path in files:
        if not path.exists() or path.suffix not in (".py", ".md"):
            continue
        for v in scan_file(path, rules):
            all_violations.append((path, v))

    if not all_violations:
        return 0

    print(f"  FAILED: {len(all_violations)} glossary violation(s) found")
    for path, v in all_violations:
        print(_format_violation(path, v))
    return 1


if __name__ == "__main__":
    sys.exit(main())
