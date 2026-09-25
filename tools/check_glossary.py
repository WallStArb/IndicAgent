#!/usr/bin/env python3
"""Glossary enforcement checker: scans files for banned synonyms.

Parses docs/foundation/glossary.md for each entry's rule fields, then scans files for
violations. Called by the pre-commit hook (staged files) and CI (full tree), both against
the committed baseline, so existing violations are held and no file may add one.

Rule fields (see the glossary's "Rule fields" note):
    **Banned:**  plain comma list of exact terms; a line that is not a plain list fails loudly
    **Exempt:**  exact identifiers the entry's bans do not apply to
    **Scope:**   optional path globs limiting where the entry's bans apply
    **Avoid:**   contextual guidance, not enforced

Usage:
    python tools/check_glossary.py [--baseline tools/glossary_baseline.json] file1 file2 ...
    python tools/check_glossary.py --all --baseline tools/glossary_baseline.json
    python tools/check_glossary.py --all --update-baseline tools/glossary_baseline.json
Exit 0 if clean (or no count above baseline), 1 on violations, 2 on an unparseable glossary.
"""

import argparse
import fnmatch
import functools
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GLOSSARY_PATH = REPO_ROOT / "docs" / "foundation" / "glossary.md"
BASELINE_PATH = REPO_ROOT / "tools" / "glossary_baseline.json"

SCANNED_SUFFIXES = (".py", ".md", ".ts", ".tsx", ".yaml", ".yml", ".sql")
_IDENTIFIER_SUFFIXES = (".py", ".ts", ".tsx", ".yaml", ".yml", ".sql")
_WHOLE_FILE_PROSE_SUFFIXES = (".md", ".ts", ".tsx", ".yaml", ".yml", ".sql")
# Archived docs are frozen history; the glossary defines the banned terms themselves.
_EXCLUDED_PATTERNS = ("docs/ideas/archive/*", "docs/plans/archive/*", "docs/research/archive/*")
_TERM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-/]*$")


class GlossaryParseError(ValueError):
    """A rule field the checker cannot enforce as written."""


@dataclass
class GlossaryRule:
    canonical: str
    banned: list[str] = field(default_factory=list)
    status: str = "active"
    replaced_by: str | None = None
    exempt: list[str] = field(default_factory=list)
    scope: list[str] = field(default_factory=list)


@dataclass
class Violation:
    status: str  # "active", "deprecated", or "retired"
    lineno: int
    line: str
    banned_term: str
    canonical: str
    scan_type: str  # "prose" or "identifier"
    replaced_by: str | None = None


def _plain_list(raw: str, field_name: str, canonical: str, lineno: int) -> list[str]:
    terms = [t.strip() for t in raw.split(",") if t.strip()]
    bad = [t for t in terms if not _TERM_RE.match(t)]
    if bad or not terms:
        raise GlossaryParseError(
            f"glossary.md:{lineno}: `{canonical}` {field_name} must be a plain comma list of "
            f"exact terms (no quotes or notes; put guidance under **Avoid:**), got {raw!r}"
        )
    return terms


def parse_glossary(path: Path = GLOSSARY_PATH) -> list[GlossaryRule]:
    """Parse glossary.md and return every entry's rule. Raises GlossaryParseError on a
    Banned, Exempt or Scope field that is not a plain list, so no rule is silently dropped."""
    rules: list[GlossaryRule] = []
    current: GlossaryRule | None = None
    for lineno, raw_line in enumerate(path.read_text().splitlines(), 1):
        line = raw_line.strip()
        m = re.match(r"^### `(.+?)`", line)
        if m:
            if current is not None:
                rules.append(current)
            current = GlossaryRule(canonical=m.group(1))
            continue
        if current is None:
            continue
        m = re.match(r"^\*\*(Banned|Exempt|Scope):\*\*\s*(.*)", line)
        if m:
            name, raw = m.group(1), m.group(2).strip()
            if name == "Banned":
                if raw.lower() != "(none)":
                    current.banned = _plain_list(raw, "Banned", current.canonical, lineno)
            elif name == "Exempt":
                current.exempt = _plain_list(raw, "Exempt", current.canonical, lineno)
            else:
                current.scope = [g.strip() for g in raw.split(",") if g.strip()]
                if not current.scope:
                    raise GlossaryParseError(
                        f"glossary.md:{lineno}: `{current.canonical}` has an empty **Scope:**"
                    )
            continue
        m = re.match(r"^\*\*Status:\*\*\s*(\w+)", line)
        if m:
            current.status = m.group(1).strip()
            continue
        m = re.match(r"^\*\*Replaced by:\*\*\s*`(.+?)`", line)
        if m:
            current.replaced_by = m.group(1).strip()
    if current is not None:
        rules.append(current)
    return rules


def _extract_prose_lines(path: Path, raw_lines: list[str] | None = None) -> list[tuple[int, str]]:
    """Return (1-based lineno, text) for prose content to scan.

    Markdown, TypeScript, YAML and SQL: every line (UX strings and labels live in code).
    Python: comment lines and content inside triple-quoted strings.
    NOTE: fires on any unclosed triple-quote, not just true docstrings; an acceptable
    tradeoff for a line-by-line scanner.
    """
    lines = raw_lines if raw_lines is not None else path.read_text().splitlines()
    if path.suffix in _WHOLE_FILE_PROSE_SUFFIXES:
        return [(i + 1, line) for i, line in enumerate(lines)]
    result: list[tuple[int, str]] = []
    in_docstring = False
    docstring_char: str | None = None
    for i, line in enumerate(lines):
        lineno = i + 1
        stripped = line.strip()
        if not in_docstring:
            for q in ('"""', "'''"):
                if q in stripped:
                    if stripped.count(q) >= 2:
                        result.append((lineno, line))
                    else:
                        in_docstring = True
                        docstring_char = q
                        result.append((lineno, line))
                    break
            else:
                if "#" in line:
                    result.append((lineno, line[line.index("#") :]))
        else:
            result.append((lineno, line))
            if docstring_char and docstring_char in stripped:
                in_docstring = False
                docstring_char = None
    return result


@functools.cache
def _identifier_tokens(name: str) -> tuple[str, ...]:
    """Split a snake_case or camelCase identifier into lowercase tokens."""
    tokens: list[str] = []
    for part in name.split("_"):
        if not part:
            continue
        expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", part)
        expanded = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", expanded)
        tokens.extend(t.lower() for t in expanded.split() if t)
    return tuple(tokens)


def _check_identifier_for_banned(identifier: str, banned_term: str) -> bool:
    """True if the banned term's words appear as consecutive tokens of the identifier, so
    `SignalSource` and `signal_source` both match "signal source"."""
    return f" {_banned_words(banned_term)} " in f" {' '.join(_identifier_tokens(identifier))} "


@functools.cache
def _banned_words(banned_term: str) -> str:
    return " ".join(w for w in re.split(r"[\s_\-/.]+", banned_term.lower()) if w)


@functools.cache
def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _in_scope(rule: GlossaryRule, rel_path: str) -> bool:
    return not rule.scope or any(fnmatch.fnmatch(rel_path, g) for g in rule.scope)


def _canonical_phrase(canonical: str) -> str:
    return re.sub(r"\s*\(.*?\)\s*", " ", canonical).strip().lower()


@dataclass(frozen=True)
class CompiledBan:
    """One banned term, ready to scan: its prose pattern, and the canonical terms containing
    it (as a prose pattern and as identifier word strings), which are never violations."""

    rule: GlossaryRule
    banned: str
    pattern: re.Pattern[str]
    shield: re.Pattern[str] | None
    shield_words: tuple[str, ...]


def _build_compiled_rules(rules: list[GlossaryRule]) -> list[CompiledBan]:
    """Per (rule, banned term): a CompiledBan. `market state classification` contains the
    banned "market state", so it is a shield for that ban."""
    phrases = {_canonical_phrase(r.canonical) for r in rules}
    result = []
    for rule in rules:
        for banned in rule.banned:
            pattern = re.compile(r"\b" + re.escape(banned) + r"\b", re.IGNORECASE)
            containing = sorted(p for p in phrases if p != banned.lower() and pattern.search(p))
            shield = (
                re.compile("|".join(re.escape(p) for p in containing), re.IGNORECASE)
                if containing
                else None
            )
            result.append(
                CompiledBan(
                    rule, banned, pattern, shield, tuple(_banned_words(p) for p in containing)
                )
            )
    return result


def _is_quoted_mention(match: re.Match[str], text: str) -> bool:
    """A mention, not a use: the term inside matching quotes or backticks ("term", `term`,
    'term'), with an optional trailing comma or period inside the quotes."""
    before = text[match.start() - 1] if match.start() else ""
    after = re.match(r"[,.]?([\"'`])", text[match.end() :])
    return bool(before) and before in "\"'`" and bool(after) and after.group(1) == before


def _in_canonical_phrase(match: re.Match[str], shield: re.Pattern[str] | None, text: str) -> bool:
    """The hit lies inside a canonical term that contains the banned one."""
    return shield is not None and any(
        s.start() <= match.start() and match.end() <= s.end() for s in shield.finditer(text)
    )


def scan_file(
    path: Path, rules: list[GlossaryRule], compiled: list[CompiledBan] | None = None
) -> list[Violation]:
    """Scan one file for violations of every rule in scope (active, deprecated, retired).
    `compiled` is `_build_compiled_rules(rules)`, passed in to build it once per run."""
    rel_path = _rel(path)
    if compiled is None:
        compiled = _build_compiled_rules(rules)
    compiled = [c for c in compiled if _in_scope(c.rule, rel_path)]
    raw_lines = path.read_text(errors="replace").splitlines()
    violations: list[Violation] = []
    prose_keys: set[tuple[int, str]] = set()
    if not compiled:
        return violations
    # One pass screens each line for any banned term (prose) or any term's first word
    # (identifiers, where `SignalSource` hides the space); per-rule work runs only on hits.
    any_term = re.compile("|".join(c.pattern.pattern for c in compiled), re.IGNORECASE)
    any_word = re.compile(
        "|".join(sorted({re.escape(_banned_words(c.banned).split(" ")[0]) for c in compiled})),
        re.IGNORECASE,
    )

    for lineno, text in _extract_prose_lines(path, raw_lines):
        if not any_term.search(text):
            continue
        for c in compiled:
            rule, banned, pattern, shield = c.rule, c.banned, c.pattern, c.shield
            if any(
                not (_is_quoted_mention(m, text) or _in_canonical_phrase(m, shield, text))
                for m in pattern.finditer(text)
            ):
                violations.append(
                    Violation(
                        rule.status,
                        lineno,
                        text.strip(),
                        banned,
                        rule.canonical,
                        "prose",
                        rule.replaced_by,
                    )
                )
                prose_keys.add((lineno, banned))

    if path.suffix in _IDENTIFIER_SUFFIXES:
        for lineno, line in enumerate(raw_lines, 1):
            if not any_word.search(line):
                continue
            lowered = line.lower()
            live = [c for c in compiled if _banned_words(c.banned).split(" ")[0] in lowered]
            for m in re.finditer(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", line):
                identifier = m.group(0)
                if _is_quoted_mention(m, line):
                    continue
                words = f" {' '.join(_identifier_tokens(identifier))} "
                for c in live:
                    if identifier in c.rule.exempt or (lineno, c.banned) in prose_keys:
                        continue
                    if not _check_identifier_for_banned(identifier, c.banned):
                        continue
                    if any(f" {w} " in words for w in c.shield_words):
                        continue
                    violations.append(
                        Violation(
                            c.rule.status,
                            lineno,
                            line.strip(),
                            c.banned,
                            c.rule.canonical,
                            "identifier",
                            c.rule.replaced_by,
                        )
                    )
                    prose_keys.add((lineno, c.banned))
    return violations


def _format_violation(path: Path, v: Violation) -> str:
    use = v.replaced_by or v.canonical
    return f"  {_rel(path)}:{v.lineno}: [{v.status}] '{v.banned_term}' (use: `{use}`)\n    {v.line}"


def _scannable(path: Path) -> bool:
    rel = _rel(path)
    return (
        path.suffix in SCANNED_SUFFIXES
        and path.exists()
        and rel != _rel(GLOSSARY_PATH)
        and "node_modules/" not in rel
        and not any(fnmatch.fnmatch(rel, g) for g in _EXCLUDED_PATTERNS)
    )


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [REPO_ROOT / f for f in out.splitlines()]


def _counts(found: list[tuple[Path, Violation]]) -> dict[str, dict[str, int]]:
    c: Counter[tuple[str, str]] = Counter((_rel(p), v.banned_term.lower()) for p, v in found)
    out: dict[str, dict[str, int]] = {}
    for (f, t), n in sorted(c.items()):
        out.setdefault(f, {})[t] = n
    return out


def carry_renames(baseline_path: Path, renames: list[tuple[str, str]]) -> bool:
    """Move held counts from each renamed file's old path to its new one, so `git mv` of a
    file with held violations is not read as new violations. Returns True if it changed."""
    data = json.loads(baseline_path.read_text())
    counts = data["counts"]
    moved = False
    for old, new in renames:
        if old in counts and new not in counts:
            counts[new] = counts.pop(old)
            moved = True
    if moved:
        baseline_path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    return moved


def _staged_renames() -> list[tuple[str, str]]:
    out = subprocess.run(
        ["git", "diff", "--cached", "-M", "--name-status", "--diff-filter=R"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [(f[1], f[2]) for f in (line.split("\t") for line in out.splitlines()) if len(f) == 3]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--all", action="store_true", help="scan every tracked file")
    ap.add_argument("--baseline", type=Path, help="fail only on counts above this baseline")
    ap.add_argument("--update-baseline", type=Path, help="write current counts as the baseline")
    ap.add_argument(
        "--carry-renames",
        action="store_true",
        help="move --baseline entries across staged renames and stage the baseline (hook)",
    )
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])

    try:
        rules = parse_glossary()
    except GlossaryParseError as error:
        print(f"  FAILED: unparseable glossary rule\n  {error}")
        return 2
    if not rules:
        print("  FAILED: glossary.md parsed 0 rules; check the file path")
        return 2

    if args.carry_renames and args.baseline and carry_renames(args.baseline, _staged_renames()):
        subprocess.run(["git", "add", str(args.baseline)], cwd=REPO_ROOT, check=True)
        print("  NOTE: baseline entries carried across staged renames and staged")

    paths = _tracked_files() if args.all else [Path(f) for f in args.files]
    paths = [p for p in paths if _scannable(p)]
    if not paths and not args.update_baseline:
        return 0

    if args.all:
        scanned_rel = [_rel(p) for p in paths]
        dead = [
            (r.canonical, g)
            for r in rules
            for g in r.scope
            if not any(fnmatch.fnmatch(f, g) for f in scanned_rel)
        ]
        if dead:
            print(f"  FAILED: **Scope:** glob(s) matching no scanned file: {dead}")
            return 2

    compiled = _build_compiled_rules(rules)
    found = [(p, v) for p in paths for v in scan_file(p, rules, compiled)]
    counts = _counts(found)

    if args.update_baseline:
        if not args.all:
            print("  FAILED: --update-baseline needs --all (a baseline covers the whole tree)")
            return 2
        args.update_baseline.write_text(
            json.dumps({"version": 1, "counts": counts}, indent=1, sort_keys=True) + "\n"
        )
        total = sum(n for f in counts.values() for n in f.values())
        print(f"  Baseline written: {total} held violation(s) in {len(counts)} file(s)")
        return 0

    baseline: dict[str, dict[str, int]] = {}
    if args.baseline:
        baseline = json.loads(args.baseline.read_text())["counts"]

    scanned = {_rel(p) for p in paths}
    over = {
        (f, t)
        for f, terms in counts.items()
        for t, n in terms.items()
        if n > baseline.get(f, {}).get(t, 0)
    }
    under = sorted(
        (f, t)
        for f in scanned
        for t, n in baseline.get(f, {}).items()
        if counts.get(f, {}).get(t, 0) < n
    )

    if under:
        print(
            f"  NOTE: {len(under)} baseline entr(ies) now below their held count; lower the "
            "baseline with --all --update-baseline tools/glossary_baseline.json"
        )
    if not over:
        return 0
    failing = [(p, v) for p, v in found if (_rel(p), v.banned_term.lower()) in over]
    print(f"  FAILED: {len(over)} file/term count(s) above baseline")
    for path, v in failing:
        print(_format_violation(path, v))
    return 1


if __name__ == "__main__":
    sys.exit(main())
