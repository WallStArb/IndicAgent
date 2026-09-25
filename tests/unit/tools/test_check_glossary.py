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


@pytest.fixture
def md_file_with_multiword_banned(tmp_path: Path) -> Path:
    p = tmp_path / "multiword.md"
    p.write_text("The classification scheme used here is well-defined.\n")
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

    def test_detects_multiword_banned_term_in_prose(
        self, sample_glossary, md_file_with_multiword_banned
    ):
        rules = parse_glossary(sample_glossary)
        violations = scan_file(md_file_with_multiword_banned, rules)
        assert any(v.banned_term == "classification scheme" for v in violations)
        assert any(v.canonical == "vocabulary" for v in violations)


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
    def test_violation_fields_from_md_prose_scan(self, sample_glossary, md_file_with_banned):
        rules = parse_glossary(sample_glossary)
        violations = scan_file(md_file_with_banned, rules)
        assert len(violations) == 1
        v = violations[0]
        assert v.lineno == 1
        assert v.banned_term == "taxonomy"
        assert v.canonical == "vocabulary"
        assert v.status == "active"
        assert v.scan_type == "prose"
        assert "taxonomy" in v.line


# ---------------------------------------------------------------------------
# Todo 430: strict parsing, multi-word identifiers, coverage, mentions, baseline
# ---------------------------------------------------------------------------

from tools.check_glossary import GlossaryParseError, main  # noqa: E402


def _glossary(tmp_path: Path, banned_line: str, extra: str = "") -> Path:
    p = tmp_path / "glossary.md"
    p.write_text(
        "# Glossary\n\n### `market state classification`\n\nx\n\n**Banned:** (none)\n\n---\n\n"
        f"### `intelligence vector`\n\nx\n\n{banned_line}\n{extra}**Status:** active\n\n---\n"
    )
    return p


def test_quoted_banned_line_fails_loudly(tmp_path: Path) -> None:
    g = _glossary(tmp_path, '**Banned:** "signal source," "alpha source" (use `x`)')
    with pytest.raises(GlossaryParseError):
        parse_glossary(g)


def test_multiword_ban_matches_camel_and_snake_identifiers(tmp_path: Path) -> None:
    rules = parse_glossary(_glossary(tmp_path, "**Banned:** signal source"))
    f = tmp_path / "m.py"
    f.write_text("class SignalSource:\n    pass\nsignal_source_x = 1\nsignals = 2\n")
    hits = [v for v in scan_file(f, rules) if v.scan_type == "identifier"]
    assert [v.lineno for v in hits] == [1, 3]


def test_exempt_identifier_is_not_flagged(tmp_path: Path) -> None:
    rules = parse_glossary(
        _glossary(tmp_path, "**Banned:** signal source", "**Exempt:** SignalSource\n")
    )
    f = tmp_path / "m.py"
    f.write_text("class SignalSource:\n    pass\n")
    assert scan_file(f, rules) == []


def test_typescript_and_yaml_are_scanned(tmp_path: Path) -> None:
    rules = parse_glossary(_glossary(tmp_path, "**Banned:** signal source"))
    ts = tmp_path / "Panel.tsx"
    ts.write_text('const title = "Top signal source";\nconst signalSource = 1;\n')
    yml = tmp_path / "spec.yaml"
    yml.write_text("label: best signal source\n")
    assert len(scan_file(ts, rules)) == 2
    assert len(scan_file(yml, rules)) == 1


def test_quoted_mention_is_not_a_use(tmp_path: Path) -> None:
    rules = parse_glossary(_glossary(tmp_path, "**Banned:** signal source"))
    f = tmp_path / "doc.md"
    f.write_text('The glossary bans "signal source," and `signal source`.\nA signal source here.\n')
    assert [v.lineno for v in scan_file(f, rules)] == [2]


def test_canonical_term_containing_a_ban_is_not_flagged(tmp_path: Path) -> None:
    rules = parse_glossary(_glossary(tmp_path, "**Banned:** market state"))
    f = tmp_path / "doc.md"
    f.write_text("See market state classification.\nThe market state is bad.\n")
    assert [v.lineno for v in scan_file(f, rules)] == [2]


def test_scope_limits_a_ban_to_its_paths(tmp_path: Path) -> None:
    rules = parse_glossary(
        _glossary(tmp_path, "**Banned:** signal source", "**Scope:** research/*\n")
    )
    f = tmp_path / "doc.md"
    f.write_text("A signal source.\n")
    assert scan_file(f, rules) == []


def test_baseline_holds_existing_and_fails_on_increase(tmp_path: Path, monkeypatch) -> None:
    import json

    import tools.check_glossary as cg

    g = _glossary(tmp_path, "**Banned:** signal source")
    monkeypatch.setattr(cg, "GLOSSARY_PATH", g)
    doc = tmp_path / "doc.md"
    doc.write_text("A signal source.\n")
    rel = cg._rel(doc)
    base = tmp_path / "baseline.json"
    base.write_text(json.dumps({"version": 1, "counts": {rel: {"signal source": 1}}}))
    assert main([str(doc), "--baseline", str(base)]) == 0
    doc.write_text("A signal source.\nAnother signal source.\n")
    assert main([str(doc), "--baseline", str(base)]) == 1


def test_identifier_pass_honours_mentions_and_canonical_terms(tmp_path: Path) -> None:
    rules = parse_glossary(_glossary(tmp_path, "**Banned:** market state"))
    f = tmp_path / "m.py"
    f.write_text(
        '# we avoid "market_state" here\n' "market_state_classification = 2\n" "market_state = 3\n"
    )
    assert [v.lineno for v in scan_file(f, rules)] == [3]


def test_carry_renames_moves_held_counts(tmp_path: Path) -> None:
    import json

    from tools.check_glossary import carry_renames

    base = tmp_path / "baseline.json"
    base.write_text(json.dumps({"version": 1, "counts": {"a/old.md": {"x": 2}, "b.md": {"y": 1}}}))
    assert carry_renames(base, [("a/old.md", "a/new.md"), ("zz.md", "yy.md")])
    counts = json.loads(base.read_text())["counts"]
    assert counts == {"a/new.md": {"x": 2}, "b.md": {"y": 1}}
    assert not carry_renames(base, [("a/old.md", "a/other.md")])


def test_empty_scope_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(GlossaryParseError):
        parse_glossary(_glossary(tmp_path, "**Banned:** signal source", "**Scope:**\n"))
