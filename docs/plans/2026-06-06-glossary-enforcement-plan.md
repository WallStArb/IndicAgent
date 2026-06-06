# Glossary Enforcement and Lifecycle Management — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make banned synonym detection and glossary lifecycle management mechanical — enforced at commit time, zero human memory required.

**Architecture:** Structured fields (`**Banned:**`, `**Status:**`) added to `docs/foundation/glossary.md` act as the machine-readable rule set. `tools/check_glossary.py` parses those fields and scans staged `.py`/`.md` files for violations. A pre-commit check (check 8) calls the scanner on every commit. `tools/migrate_glossary.py` scans the full codebase on demand for deprecated term blast radius.

**Tech Stack:** Python 3.11+, stdlib only (`re`, `pathlib`, `argparse`, `sys`). No external dependencies. Bash (pre-commit hook extension).

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `docs/foundation/glossary.md` | Modify | Add `**Banned:**` and `**Status:**` to all entries |
| `tools/check_glossary.py` | Create | Parse glossary rules, scan files for violations |
| `tools/migrate_glossary.py` | Create | Full-codebase scan for deprecated/retired terms |
| `tests/unit/tools/test_check_glossary.py` | Create | Unit tests for parser and scanner |
| `.git/hooks/pre-commit` | Modify | Add check 8 calling `check_glossary.py` |

---

## Task 1: Add structured fields to glossary.md

**Files:**
- Modify: `docs/foundation/glossary.md`

This task adds `**Banned:**` and `**Status:** active` to every entry. The `**Banned:**` line lists comma-separated synonyms that must not appear in prose or code. Entries with no safe banned synonyms get `**Banned:** (none)` for explicitness.

Banned terms are only added when the synonym is clearly domain-wrong and low false-positive risk. Multi-word phrases are preferred over single words because they match more precisely.

- [ ] **Step 1: Add structured fields to each glossary entry**

Open `docs/foundation/glossary.md`. After the `**Not:**` paragraph of each entry, add the structured fields shown below. Add them in this order: `**Banned:**` then `**Status:**`, before the `**Code surface:**` line (or before `---` if no code surface line).

For `signal` — no safe banned synonyms:
```markdown
**Banned:** (none)
**Status:** active
```

For `regime`:
```markdown
**Banned:** market condition, market state, market environment
**Status:** active
```

For `factor`:
```markdown
**Banned:** (none)
**Status:** active
```

For `alpha`:
```markdown
**Banned:** outperformance
**Status:** active
```

For `edge`:
```markdown
**Banned:** (none)
**Status:** active
```

For `beta`:
```markdown
**Banned:** (none)
**Status:** active
```

For `weight`:
```markdown
**Banned:** (none)
**Status:** active
```

For `vocabulary`:
```markdown
**Banned:** taxonomy, ontology, classification scheme
**Status:** active
```

For `tag`:
```markdown
**Banned:** metadata label
**Status:** active
```

For `primitive`:
```markdown
**Banned:** (none)
**Status:** active
```

For `exposure`:
```markdown
**Banned:** (none)
**Status:** active
```

For `sensitivity`:
```markdown
**Banned:** (none)
**Status:** active
```

For `factor_regime`:
```markdown
**Banned:** (none)
**Status:** active
```

For `cycle_position`:
```markdown
**Banned:** (none)
**Status:** active
```

For `signal_role`:
```markdown
**Banned:** (none)
**Status:** active
```

For `macro_driver`:
```markdown
**Banned:** (none)
**Status:** active
```

For `p-value`:
```markdown
**Banned:** confidence level
**Status:** active
```

For `r²`:
```markdown
**Banned:** (none)
**Status:** active
```

For `mutual information`:
```markdown
**Banned:** (none)
**Status:** active
```

For `cross-correlation`:
```markdown
**Banned:** (none)
**Status:** active
```

For `half-life`:
```markdown
**Banned:** (none)
**Status:** active
```

For `empirical`:
```markdown
**Banned:** (none)
**Status:** active
```

For `daemon`:
```markdown
**Banned:** (none)
**Status:** active
```

For `writer`:
```markdown
**Banned:** (none)
**Status:** active
```

For `auditor`:
```markdown
**Banned:** (none)
**Status:** active
```

For `tracker`:
```markdown
**Banned:** (none)
**Status:** active
```

For `plugin`:
```markdown
**Banned:** (none)
**Status:** active
```

- [ ] **Step 2: Commit**

```bash
git add docs/foundation/glossary.md
git commit -m "docs(glossary): add Banned and Status structured fields to all entries"
```

---

## Task 2: Write failing tests for check_glossary.py

**Files:**
- Create: `tests/unit/tools/test_check_glossary.py`

Write all tests before implementation. Each test must fail with `ImportError` or `AttributeError` until Task 3 is complete.

- [ ] **Step 1: Create test file**

```python
"""Unit tests for tools/check_glossary.py."""

import textwrap
from pathlib import Path

import pytest

from tools.check_glossary import GlossaryRule, parse_glossary, scan_file


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_glossary(tmp_path: Path) -> Path:
    """Minimal glossary with two entries: one with banned terms, one without."""
    content = textwrap.dedent("""\
        # Glossary

        ## Core Terms

        ### `vocabulary`

        The controlled set of valid tags.

        **Not:** "taxonomy," "ontology," or "classification scheme"

        **Banned:** taxonomy, ontology, classification scheme
        **Status:** active

        **Code surface:** `tag_vocabulary` table.

        ---

        ### `signal`

        A time-stamped trade hypothesis.

        **Not:** a Kafka message or OTel metric.

        **Banned:** (none)
        **Status:** active

        ---

        ### `old_term`

        A deprecated concept.

        **Banned:** legacy name, old name
        **Status:** deprecated
        **Replaced by:** `vocabulary`
        **Deprecated:** 2026-01-01

        ---

        ### `retired_term`

        A fully retired concept.

        **Banned:** dead name
        **Status:** retired
        **Replaced by:** `signal`

        ---
    """)
    p = tmp_path / "glossary.md"
    p.write_text(content)
    return p


@pytest.fixture
def py_file_with_banned(tmp_path: Path) -> Path:
    p = tmp_path / "example.py"
    p.write_text(textwrap.dedent("""\
        # This is a taxonomy of instruments
        def get_taxonomy():
            pass
    """))
    return p


@pytest.fixture
def py_file_clean(tmp_path: Path) -> Path:
    p = tmp_path / "clean.py"
    p.write_text(textwrap.dedent("""\
        # Uses the correct term: vocabulary
        def get_vocabulary():
            pass
    """))
    return p


@pytest.fixture
def md_file_with_banned(tmp_path: Path) -> Path:
    p = tmp_path / "example.md"
    p.write_text("The taxonomy of instruments is defined here.\n")
    return p


@pytest.fixture
def py_file_with_identifier_violation(tmp_path: Path) -> Path:
    p = tmp_path / "identifier.py"
    p.write_text(textwrap.dedent("""\
        instrument_taxonomy = {}
        def build_taxonomy_map():
            pass
    """))
    return p


@pytest.fixture
def py_file_with_deprecated_banned(tmp_path: Path) -> Path:
    p = tmp_path / "deprecated.py"
    p.write_text("# uses legacy name here\n")
    return p


@pytest.fixture
def py_file_with_retired_banned(tmp_path: Path) -> Path:
    p = tmp_path / "retired.py"
    p.write_text("# references dead name\n")
    return p


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

class TestParseGlossary:
    def test_parses_active_entry_with_banned_terms(self, sample_glossary):
        rules = parse_glossary(sample_glossary)
        vocab = next(r for r in rules if r.canonical == "vocabulary")
        assert vocab.status == "active"
        assert "taxonomy" in vocab.banned
        assert "ontology" in vocab.banned
        assert "classification scheme" in vocab.banned

    def test_parses_entry_with_no_banned_terms(self, sample_glossary):
        rules = parse_glossary(sample_glossary)
        sig = next(r for r in rules if r.canonical == "signal")
        assert sig.status == "active"
        assert sig.banned == []

    def test_parses_deprecated_entry(self, sample_glossary):
        rules = parse_glossary(sample_glossary)
        old = next(r for r in rules if r.canonical == "old_term")
        assert old.status == "deprecated"
        assert old.replaced_by == "vocabulary"
        assert "legacy name" in old.banned
        assert "old name" in old.banned

    def test_parses_retired_entry(self, sample_glossary):
        rules = parse_glossary(sample_glossary)
        ret = next(r for r in rules if r.canonical == "retired_term")
        assert ret.status == "retired"
        assert ret.replaced_by == "signal"
        assert "dead name" in ret.banned

    def test_returns_all_entries(self, sample_glossary):
        rules = parse_glossary(sample_glossary)
        assert len(rules) == 4


# ---------------------------------------------------------------------------
# Prose scan tests
# ---------------------------------------------------------------------------

class TestScanFileProse:
    def test_detects_banned_term_in_py_comment(self, sample_glossary, py_file_with_banned):
        rules = parse_glossary(sample_glossary)
        violations = scan_file(py_file_with_banned, rules)
        assert len(violations) >= 1
        statuses = {v.status for v in violations}
        assert "active" not in statuses  # active banned terms not enforced

    def test_detects_banned_term_in_md_file(self, sample_glossary, md_file_with_banned):
        rules = parse_glossary(sample_glossary)
        violations = scan_file(md_file_with_banned, rules)
        assert any(v.banned_term == "taxonomy" for v in violations)

    def test_no_violation_on_clean_file(self, sample_glossary, py_file_clean):
        rules = parse_glossary(sample_glossary)
        violations = scan_file(py_file_clean, rules)
        assert violations == []

    def test_detects_deprecated_term_in_comment(self, sample_glossary, py_file_with_deprecated_banned):
        rules = parse_glossary(sample_glossary)
        violations = scan_file(py_file_with_deprecated_banned, rules)
        assert any(v.status == "deprecated" for v in violations)

    def test_detects_retired_term_in_comment(self, sample_glossary, py_file_with_retired_banned):
        rules = parse_glossary(sample_glossary)
        violations = scan_file(py_file_with_retired_banned, rules)
        assert any(v.status == "retired" for v in violations)


# ---------------------------------------------------------------------------
# Identifier scan tests
# ---------------------------------------------------------------------------

class TestScanFileIdentifiers:
    def test_detects_banned_term_in_variable_name(self, sample_glossary, py_file_with_identifier_violation):
        rules = parse_glossary(sample_glossary)
        violations = scan_file(py_file_with_identifier_violation, rules)
        assert len(violations) >= 1

    def test_identifier_scan_skipped_for_md(self, sample_glossary, md_file_with_banned):
        # MD files don't have identifier scans - violations come from prose only
        rules = parse_glossary(sample_glossary)
        violations = scan_file(md_file_with_banned, rules)
        assert all(v.scan_type == "prose" for v in violations)


# ---------------------------------------------------------------------------
# Violation dataclass tests
# ---------------------------------------------------------------------------

class TestViolation:
    def test_violation_has_required_fields(self, sample_glossary, md_file_with_banned):
        rules = parse_glossary(sample_glossary)
        violations = scan_file(md_file_with_banned, rules)
        v = violations[0]
        assert hasattr(v, "status")
        assert hasattr(v, "lineno")
        assert hasattr(v, "line")
        assert hasattr(v, "banned_term")
        assert hasattr(v, "canonical")
        assert hasattr(v, "scan_type")
```

- [ ] **Step 2: Run tests to confirm they fail with ImportError**

```bash
.venv/bin/pytest tests/unit/tools/test_check_glossary.py -v 2>&1 | head -20
```

Expected: `ImportError: No module named 'tools.check_glossary'`

---

## Task 3: Implement tools/check_glossary.py

**Files:**
- Create: `tools/check_glossary.py`

- [ ] **Step 1: Create the file**

```python
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


@dataclass
class GlossaryRule:
    canonical: str
    banned: list[str] = field(default_factory=list)
    status: str = "active"
    replaced_by: str | None = None


@dataclass
class Violation:
    status: str        # "deprecated" or "retired"
    lineno: int
    line: str
    banned_term: str
    canonical: str
    scan_type: str     # "prose" or "identifier"
    replaced_by: str | None = None


def parse_glossary(path: Path = GLOSSARY_PATH) -> list[GlossaryRule]:
    """Parse glossary.md and return all rules with banned terms."""
    rules: list[GlossaryRule] = []
    current: GlossaryRule | None = None

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()

        m = re.match(r'^### `(.+?)`', line)
        if m:
            if current is not None:
                rules.append(current)
            current = GlossaryRule(canonical=m.group(1))
            continue

        if current is None:
            continue

        m = re.match(r'^\*\*Banned:\*\*\s*(.+)', line)
        if m:
            raw = m.group(1).strip()
            if raw.lower() != "(none)":
                current.banned = [t.strip() for t in raw.split(",") if t.strip()]
            continue

        m = re.match(r'^\*\*Status:\*\*\s*(\w+)', line)
        if m:
            current.status = m.group(1).strip()
            continue

        m = re.match(r'^\*\*Replaced by:\*\*\s*`(.+?)`', line)
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
            # Check for triple-quoted string start
            for q in ('"""', "'''"):
                if q in stripped:
                    occurrences = stripped.count(q)
                    if occurrences >= 2:
                        # Opens and closes on the same line
                        result.append((lineno, line))
                    else:
                        in_docstring = True
                        docstring_char = q
                        result.append((lineno, line))
                    break
            else:
                # Plain comment
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
    # Split on underscores
    parts = name.split("_")
    tokens: list[str] = []
    for part in parts:
        if not part:
            continue
        # Split camelCase: insert space before each uppercase letter that
        # follows a lowercase letter or precedes a lowercase letter
        expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", part)
        expanded = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", expanded)
        tokens.extend(t.lower() for t in expanded.split() if t)
    return tokens


def _check_identifier_for_banned(identifier: str, banned_term: str) -> bool:
    """Return True if a single-word banned term appears as a token in the identifier."""
    banned_words = banned_term.lower().split()
    if len(banned_words) != 1:
        # Multi-word banned terms are prose-only; too noisy in identifiers
        return False
    tokens = _split_identifier(identifier)
    return banned_words[0] in tokens


def scan_file(path: Path, rules: list[GlossaryRule]) -> list[Violation]:
    """Scan a file for glossary violations.

    Only deprecated and retired terms produce violations — active banned terms
    are checked here so the framework is in place, but flagging only enforces
    terms that are being phased out or have been replaced.

    Active terms with banned synonyms: violations ARE reported (the banned list
    means "never use these").
    """
    violations: list[Violation] = []
    enforced_rules = [r for r in rules if r.banned and r.status in ("active", "deprecated", "retired")]

    # --- Prose scan ---
    prose_lines = _extract_prose_lines(path)
    for lineno, text in prose_lines:
        for rule in enforced_rules:
            for banned in rule.banned:
                pattern = r"\b" + re.escape(banned) + r"\b"
                if re.search(pattern, text, re.IGNORECASE):
                    violations.append(Violation(
                        status=rule.status,
                        lineno=lineno,
                        line=text.strip(),
                        banned_term=banned,
                        canonical=rule.canonical,
                        scan_type="prose",
                        replaced_by=rule.replaced_by,
                    ))

    # --- Identifier scan (Python only) ---
    if path.suffix == ".py":
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            for m in re.finditer(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b", line):
                identifier = m.group(1)
                for rule in enforced_rules:
                    for banned in rule.banned:
                        if _check_identifier_for_banned(identifier, banned):
                            # Avoid double-reporting if prose scan already caught it
                            already = any(
                                v.lineno == lineno and v.banned_term == banned and v.scan_type == "prose"
                                for v in violations
                            )
                            if not already:
                                violations.append(Violation(
                                    status=rule.status,
                                    lineno=lineno,
                                    line=line.strip(),
                                    banned_term=banned,
                                    canonical=rule.canonical,
                                    scan_type="identifier",
                                    replaced_by=rule.replaced_by,
                                ))

    return violations


def _format_violation(path: Path, v: Violation) -> str:
    replacement = f" (use: `{v.replaced_by}`)" if v.replaced_by else f" (use: `{v.canonical}`)"
    return (
        f"  {path}:{v.lineno}: [{v.status}] '{v.banned_term}'{replacement}\n"
        f"    {v.line}"
    )


def main(argv: list[str] | None = None) -> int:
    files = [Path(f) for f in (argv if argv is not None else sys.argv[1:])]
    if not files:
        print("check_glossary.py: no files provided")
        return 0

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
```

- [ ] **Step 2: Run tests**

```bash
.venv/bin/pytest tests/unit/tools/test_check_glossary.py -v
```

Expected: All tests pass.

- [ ] **Step 3: Smoke test against the glossary itself (should be clean)**

```bash
.venv/bin/python tools/check_glossary.py docs/foundation/glossary.md
```

Expected: no output, exit 0.

- [ ] **Step 4: Smoke test with a synthetic violation**

```bash
echo "# uses taxonomy here" > /tmp/test_banned.py
.venv/bin/python tools/check_glossary.py /tmp/test_banned.py
```

Expected: output like `[active] 'taxonomy' (use: 'vocabulary')`, exit 1.

- [ ] **Step 5: Commit**

```bash
git add tools/check_glossary.py tests/unit/tools/test_check_glossary.py
git commit -m "feat(glossary): add check_glossary.py scanner with unit tests"
```

---

## Task 4: Implement tools/migrate_glossary.py

**Files:**
- Create: `tools/migrate_glossary.py`

- [ ] **Step 1: Create the file**

```python
#!/usr/bin/env python3
"""Glossary migration tool — scan codebase for deprecated/retired terms.

Run before deprecating a term to assess blast radius. Run after fixing
all occurrences to confirm the codebase is clean before promoting to 'retired'.

Usage:
    python tools/migrate_glossary.py --term taxonomy
    python tools/migrate_glossary.py --deprecated
    python tools/migrate_glossary.py --retired

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


def _rules_for_mode(rules: list[GlossaryRule], mode: str, specific_term: str | None) -> list[GlossaryRule]:
    if specific_term:
        matched = [r for r in rules if specific_term in r.banned or specific_term == r.canonical]
        if not matched:
            print(f"No glossary entry found with banned term or canonical name: '{specific_term}'")
            sys.exit(1)
        return matched
    if mode == "deprecated":
        return [r for r in rules if r.status == "deprecated" and r.banned]
    if mode == "retired":
        return [r for r in rules if r.status == "retired" and r.banned]
    return [r for r in rules if r.status in ("deprecated", "retired") and r.banned]


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan codebase for deprecated/retired glossary terms.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--term", metavar="TERM", help="Scan for a specific banned synonym or canonical name")
    group.add_argument("--deprecated", action="store_true", help="Scan for all deprecated terms")
    group.add_argument("--retired", action="store_true", help="Scan for all retired terms")
    group.add_argument("--all", action="store_true", help="Scan for all deprecated and retired terms")
    args = parser.parse_args()

    rules = parse_glossary()
    mode = "deprecated" if args.deprecated else ("retired" if args.retired else "all")
    target_rules = _rules_for_mode(rules, mode, args.term)

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
```

- [ ] **Step 2: Smoke test**

```bash
.venv/bin/python tools/migrate_glossary.py --deprecated
```

Expected: "Clean — no deprecated/retired terms found." (since all entries are `active`), exit 0.

- [ ] **Step 3: Commit**

```bash
git add tools/migrate_glossary.py
git commit -m "feat(glossary): add migrate_glossary.py blast-radius scanner"
```

---

## Task 5: Add check 8 to pre-commit hook

**Files:**
- Modify: `.git/hooks/pre-commit`

- [ ] **Step 1: Add the check function**

In `.git/hooks/pre-commit`, find the line `check_ring0_boundary || FAILURES=$((FAILURES + 1))` at the bottom of the "Run all checks" section. Add after it:

```bash
check_glossary_terms || FAILURES=$((FAILURES + 1))
```

Then add the function definition before the "Run all checks" section (after `check_ring0_boundary` function closes):

```bash
# -----------------------------------------------------------------------------
# Check 8: Glossary enforcement — banned synonyms must not appear in staged files
#
# Scope: All .py and .md files in this commit
# Tool: tools/check_glossary.py
# Blocks on any banned term (active, deprecated, or retired) in prose or identifiers
# -----------------------------------------------------------------------------
check_glossary_terms() {
    echo "[8/8] Glossary enforcement check..."

    CHANGED_FILES=$(git diff --cached --name-only --diff-filter=ACM | \
        grep -E '\.(py|md)$' | \
        grep -vE '(\.venv|node_modules|\.git|__pycache__)' || true)

    if [ -z "$CHANGED_FILES" ]; then
        echo "  OK No Python or Markdown files changed"
        return 0
    fi

    PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
    SCRIPT="${REPO_ROOT}/tools/check_glossary.py"

    if [ ! -f "$SCRIPT" ]; then
        echo "  SKIPPED: tools/check_glossary.py not found"
        return 0
    fi

    FULL_PATHS=""
    for file in $CHANGED_FILES; do
        if [ -f "${REPO_ROOT}/${file}" ]; then
            FULL_PATHS="${FULL_PATHS} ${REPO_ROOT}/${file}"
        fi
    done

    if [ -z "$FULL_PATHS" ]; then
        echo "  OK No files found on disk"
        return 0
    fi

    if ! "$PYTHON_BIN" "$SCRIPT" $FULL_PATHS; then
        echo "  Remediation: Replace banned term with the canonical glossary term."
        echo "  Reference: docs/foundation/glossary.md"
        return 1
    fi

    echo "  OK Glossary terms clean"
    return 0
}
```

- [ ] **Step 2: Update the check count header comment**

Find the comment block at the top of the pre-commit hook that says:
```
# Checks:
#   1. Plugin class naming...
#   ...
#   7. Ring 0 boundary check
```

Add:
```
#   8. Glossary enforcement — banned synonyms blocked in .py and .md files
```

- [ ] **Step 3: Verify the hook runs correctly on a clean commit**

Make a trivial change to any file and try to stage+commit it:

```bash
# Touch the glossary itself (which should be clean)
git add docs/foundation/glossary.md
git commit --dry-run
```

Expected: `[8/8] Glossary enforcement check... OK Glossary terms clean`

If `--dry-run` is not available on your git version, make a small whitespace-only edit to a `.md` file and run `git stash` after to undo:

```bash
echo "" >> docs/foundation/glossary.md
git add docs/foundation/glossary.md
git stash
```

- [ ] **Step 4: Verify the hook blocks a banned term**

```bash
echo "# taxonomy of instruments" >> /tmp/hook_test.md
# Temporarily stage it (won't actually commit — just test the check function)
cp /tmp/hook_test.md /tmp/hook_test_staged.md
.venv/bin/python tools/check_glossary.py /tmp/hook_test_staged.md
```

Expected: exit 1 with `[active] 'taxonomy' (use: 'vocabulary')`.

- [ ] **Step 5: Commit the hook**

The pre-commit hook is in `.git/hooks/` which is not tracked by git. Commit a reference copy to `production/` or `tools/` so it is not lost:

```bash
cp .git/hooks/pre-commit tools/pre-commit.hook
git add tools/pre-commit.hook
git commit -m "feat(glossary): add check 8 — glossary enforcement in pre-commit hook"
```

---

## Task 6: Integration test + final push

**Files:**
- No new files

- [ ] **Step 1: Run full unit test suite**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all tests pass, no new failures.

- [ ] **Step 2: Run migrate_glossary against all deprecated terms (should be clean)**

```bash
.venv/bin/python tools/migrate_glossary.py --deprecated
```

Expected: "Clean — no deprecated/retired terms found."

- [ ] **Step 3: Run check_glossary against core source dirs**

```bash
.venv/bin/python tools/check_glossary.py \
  $(find src/ docs/ services/ -name "*.py" -o -name "*.md" | grep -v .venv | grep -v __pycache__ | head -100)
```

Expected: exit 0. If violations are found, fix the worst offenders (e.g. any "taxonomy" or "outperformance" hits in docs) and commit the fixes.

- [ ] **Step 4: Push**

```bash
git push origin main
```
