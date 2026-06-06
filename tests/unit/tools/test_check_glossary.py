"""Unit tests for tools/check_glossary.py."""

import textwrap
from pathlib import Path

import pytest

from tools.check_glossary import parse_glossary, scan_file

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

    def test_detects_banned_term_in_md_file(self, sample_glossary, md_file_with_banned):
        rules = parse_glossary(sample_glossary)
        violations = scan_file(md_file_with_banned, rules)
        assert any(v.banned_term == "taxonomy" for v in violations)

    def test_no_violation_on_clean_file(self, sample_glossary, py_file_clean):
        rules = parse_glossary(sample_glossary)
        violations = scan_file(py_file_clean, rules)
        assert violations == []

    def test_detects_deprecated_term_in_comment(
        self, sample_glossary, py_file_with_deprecated_banned
    ):
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
    def test_detects_banned_term_in_variable_name(
        self, sample_glossary, py_file_with_identifier_violation
    ):
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
