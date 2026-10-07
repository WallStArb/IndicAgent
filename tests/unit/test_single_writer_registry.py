"""CI guard: the single_writer invariant for every canonical data layer table (plan 185-44).

Canonical tables are the tables the migrations create (tests/unit/_migration_catalog.py) whose
name belongs to the data layer: _CANONICAL_TABLE. Every one of them needs a _REGISTRY entry,
and a registry entry for a table the migrations no longer create fails as stale. An entry is
either
- Covered(<test file>): a dedicated boundary test owns the table's writers; this guard asserts
  the file exists and names the table, and scans nothing itself, or
- a tuple of Writer(module, segment, reason): the modules under services/, src/ and scripts/ that
  write the table (INSERT INTO, UPDATE, DELETE FROM, COPY, TRUNCATE, MERGE INTO, or asyncpg
  copy_records_to_table/copy_to_table on its literal name). The scanned writer set must equal
  the registered one: an unregistered writer fails and a registered module that no longer
  writes fails as stale. One writer per table, or one per declared segment: every writer then
  names the segment it owns on one dimension (`rule`, `inferred_by`, `monitor_type`, a
  timeframe set), the declared sets are pairwise disjoint, and at most one writer owns the
  complement (segment None, "every other value"). A writer that breaks this is entered
  TEMPORARY with `retire: <plan id>` naming the plan that removes it; the expiry guard
  (test_temporary_allow_list_expiry.py) fails the entry once that plan completes. An empty
  tuple registers a table nothing may write.

Later plans that add a canonical table or a writer edit this registry in the same commit.
CI-clean: filesystem only, no database. A write through a table name held in a variable
(f"INSERT INTO {table}") is invisible to the scan, as in every boundary test.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from tests.unit._migration_catalog import REPO_ROOT, migration_catalog

_SEARCH_DIRS = ("services", "src", "scripts")
_FILE_GLOBS = ("*.py", "*.sh", "*.sql")
_CANONICAL_TABLE = re.compile(
    r"^(?:ohlcv_|bar_|market_data_|canonical_bar_|corporate_action|listing_venue|dividend_|"
    r"integrity_monitor)"
)


@dataclass(frozen=True)
class Covered:
    test_file: str


@dataclass(frozen=True)
class Writer:
    module: str
    segment: tuple[str, frozenset[str]] | None = None
    reason: str = ""


def _segment(dimension: str, *values: str) -> tuple[str, frozenset[str]]:
    return dimension, frozenset(values)


_SCRUB_RULES = (
    "price_sanity",
    "ohlc_invariant",
    "non_positive_price",
    "vol_scaled_jump",
    "stale_print",
    "volume_outlier",
    "view_disagreement",
    "return_magnitude",
    "gap_before_next",
)

_REGISTRY: dict[str, Covered | tuple[Writer, ...]] = {
    # Tables with a dedicated boundary test.
    "market_data_ohlcv": Covered("tests/unit/test_market_data_ohlcv_writer_boundary.py"),
    "ohlcv_intraday_raw_archive": Covered(
        "tests/unit/test_ohlcv_intraday_raw_archive_writer_boundary.py"
    ),
    "ohlcv_coverage": Covered("tests/unit/test_ohlcv_coverage_writer_boundary.py"),
    "canonical_bar_lineage": Covered("tests/unit/test_canonical_lineage_digest_writer_boundary.py"),
    "bar_content_digest": Covered("tests/unit/test_canonical_lineage_digest_writer_boundary.py"),
    # One writer per ohlcv_load.source segment (plan 185-31).
    "ohlcv_load": Covered("tests/unit/test_ohlcv_load_revision_writer_boundary.py"),
    "ohlcv_revision": Covered("tests/unit/test_ohlcv_load_revision_writer_boundary.py"),
    # Scanned here. bar_source_policy joins when 185-36 creates it.
    "ohlcv_observation": (
        Writer(
            "services/ohlcv_observation_writer.py",
            reason="the D1 writer (ObservationSink / AsyncObservationSink, phase 185 D1)",
        ),
        Writer(
            "scripts/ops/bars/ops_d1_dedupe.py",
            reason=(
                "TEMPORARY: one-off dedupe of repeated identical Tradier observations, deletes "
                "with no disjoint segment; deleted with the one-off scripts (retire: 185-42)"
            ),
        ),
    ),
    "ohlcv_request": (
        Writer(
            "services/ohlcv_observation_writer.py",
            reason="the D1 writer: each request row lands with its observations",
        ),
    ),
    "ohlcv_empty_history": (
        Writer(
            "scripts/infrastructure/backfill/_empty_history.py",
            reason="the answered-empty ledger's one module (todo 433)",
        ),
    ),
    "ohlcv_provider_head": (
        Writer(
            "scripts/infrastructure/backfill/_empty_history.py",
            reason="verified provider heads, written beside the empty-history rows",
        ),
    ),
    "bar_quality_flag": (
        Writer(
            "services/bar_scrub.py",
            _segment("rule", *_SCRUB_RULES, "split_seam"),
            "the scrub's flag writer (write_flags); ops_seam_audit.py writes split_seam "
            "through it, never directly",
        ),
        Writer(
            "services/bar_derivation.py",
            _segment("rule", "constituent_flag", "partial_constituents"),
            "the grid stage's derived-bar flags",
        ),
        Writer(
            "scripts/ops/bars/ops_tradier_lineage_backfill.py",
            _segment("rule", "legacy_price_sanity_status"),
            "185-30's retirement of replaced 1d legacy flags (seeded by migration 381); the "
            "scrub's stale-flag delete excludes this rule",
        ),
    ),
    "corporate_action": (
        Writer(
            "scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py",
            _segment("inferred_by", "tradier_refetch"),
            "a Tradier refetch whose changes are a split (migration 440)",
        ),
        Writer(
            "scripts/ops/bars/ops_split_detect.py",
            _segment("inferred_by", "nightly_overlap"),
            "the overlap split detector (migration 406)",
        ),
        Writer(
            "scripts/ops/bars/ops_seam_audit.py",
            _segment("inferred_by", "seam_audit"),
            "the split-seam audit (phase 185 plan 15)",
        ),
    ),
    "integrity_monitor": (
        Writer(
            "src/core/integrity_monitor.py",
            None,
            "the shared writer: every monitor_type not declared below goes through it",
        ),
        Writer(
            "scripts/ops/alpha/ops_dependence_length_diagnostic.py",
            _segment("monitor_type", "ic_bootstrap"),
            "raw INSERT of its own monitor_type",
        ),
        Writer(
            "scripts/ops/corpus/ops_stale_k3_hmm_fields_cleanup.py",
            _segment("monitor_type", "stale_k3_hmm_field_cleanup"),
            "raw INSERT of its own monitor_type",
        ),
    ),
    "listing_venue": (
        Writer("services/listing_venue_writer.py", reason="the venue history writer (D-19)"),
    ),
    "bar_derivation_batch": (
        Writer("services/bar_derivation_batch.py", reason="provenance batches for every stage"),
    ),
    "market_data_gaps": (
        Writer("services/bar_auditor.py", reason="the gap auditor (dormant streaming path)"),
    ),
    "market_data_ohlcv_new": (
        Writer(
            "scripts/ops/bars/ops_real_rows_swap.py",
            reason="the swap target of migration 439, filled only by the swap script",
        ),
    ),
    "market_data_ohlcv_old": (),  # renamed aside by migration 045, not live; nothing writes it
    "dividend_events": (
        Writer("services/dividend_event_writer.py", reason="Yahoo dividends (todo 428)"),
    ),
    "dividend_event_coverage": (
        Writer("services/dividend_event_writer.py", reason="dividend coverage windows"),
    ),
    "dividend_date_dispute": (
        Writer("services/dividend_event_writer.py", reason="dividend date disagreements"),
    ),
}


def writer_pattern(table: str) -> re.Pattern[str]:
    name = re.escape(table)
    return re.compile(
        r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|COPY|TRUNCATE(?:\s+TABLE)?|MERGE\s+INTO)\s+"
        rf"(?:ONLY\s+)?(?:public\.)?{name}\b"
        rf"|\bcopy_(?:records_)?to_table\(\s*[\"']{name}[\"']"
    )


def scan_writers(repo_root: Path, tables: Iterable[str]) -> dict[str, set[str]]:
    patterns = {table: writer_pattern(table) for table in tables}
    writers: dict[str, set[str]] = {table: set() for table in patterns}
    for directory in _SEARCH_DIRS:
        for glob in _FILE_GLOBS:
            for path in (repo_root / directory).rglob(glob):
                if "__pycache__" in path.parts:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                for table, pattern in patterns.items():
                    if table in text and pattern.search(text):
                        writers[table].add(str(path.relative_to(repo_root)))
    return writers


def _segment_problems(table: str, entries: tuple[Writer, ...]) -> list[str]:
    owned = [entry for entry in entries if "TEMPORARY" not in entry.reason]
    if len(owned) <= 1:
        return []
    problems: list[str] = []
    complements = [entry.module for entry in owned if entry.segment is None]
    if len(complements) > 1:
        problems.append(
            f"{table}: {len(complements)} writers claim the whole table ({complements}); "
            "declare a segment for each, or mark the extra writer TEMPORARY with a retire clause"
        )
    declared = [entry for entry in owned if entry.segment is not None]
    dimensions = {entry.segment[0] for entry in declared if entry.segment}
    if len(dimensions) > 1:
        problems.append(f"{table}: segments on more than one dimension {sorted(dimensions)}")
    for i, first in enumerate(declared):
        for second in declared[i + 1 :]:
            assert first.segment and second.segment
            overlap = first.segment[1] & second.segment[1]
            if overlap:
                problems.append(
                    f"{table}: {first.module} and {second.module} overlap on "
                    f"{first.segment[0]} {sorted(overlap)}"
                )
    for entry in declared:
        if entry.segment and not entry.segment[1]:
            problems.append(f"{table}: {entry.module} declares an empty segment")
    return problems


def registry_violations(
    canonical: Iterable[str],
    registry: Mapping[str, Covered | tuple[Writer, ...]],
    writers: Mapping[str, set[str]],
    repo_root: Path,
) -> list[str]:
    canonical = set(canonical)
    problems = [
        f"{table}: canonical table with no _REGISTRY entry (register its single writer)"
        for table in sorted(canonical - set(registry))
    ]
    problems += [
        f"{table}: registered but no longer created by the migrations; remove the entry"
        for table in sorted(set(registry) - canonical)
    ]
    for table in sorted(canonical & set(registry)):
        entry = registry[table]
        if isinstance(entry, Covered):
            path = repo_root / entry.test_file
            if not path.exists():
                problems.append(f"{table}: dedicated test {entry.test_file} does not exist")
            elif not re.search(rf"\b{re.escape(table)}\b", path.read_text()):
                problems.append(f"{table}: dedicated test {entry.test_file} never names it")
            continue
        registered = {writer.module for writer in entry}
        found = writers.get(table, set())
        problems += [
            f"{table}: {module} writes it outside the registered writers "
            f"{sorted(registered) or '(none)'} (single_writer)"
            for module in sorted(found - registered)
        ]
        problems += [
            f"{table}: registered writer {module} no longer writes it; remove it"
            for module in sorted(registered - found)
        ]
        problems += _segment_problems(table, entry)
    return problems


def _canonical_tables(tables: Iterable[str]) -> set[str]:
    return {table for table in tables if _CANONICAL_TABLE.match(table)}


def test_every_canonical_table_has_a_single_registered_writer():
    tables, _ = migration_catalog()
    canonical = _canonical_tables(tables)
    scanned = [table for table in canonical if not isinstance(_REGISTRY.get(table), Covered)]
    problems = registry_violations(
        canonical, _REGISTRY, scan_writers(REPO_ROOT, scanned), REPO_ROOT
    )
    assert not problems, "\n".join(problems)


# ---------------------------------------------------------------------------------------------
# the guard's own behavior, on fakes


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for relative, text in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return tmp_path


def _violations(tmp_path: Path, files: dict[str, str], registry, canonical=("ohlcv_x",)):
    root = _tree(tmp_path, files)
    scanned = [t for t in canonical if not isinstance(registry.get(t), Covered)]
    return registry_violations(canonical, registry, scan_writers(root, scanned), root)


def test_fake_writer_outside_the_registered_writer_fails(tmp_path):
    files = {
        "services/owner.py": 'SQL = "INSERT INTO ohlcv_x (a) VALUES (1)"',
        "scripts/rogue.py": 'conn.execute("DELETE FROM ohlcv_x WHERE a = 1")',
        "scripts/reader.py": 'conn.execute("SELECT * FROM ohlcv_x")',
    }
    registry = {"ohlcv_x": (Writer("services/owner.py"),)}
    assert _violations(tmp_path, files, registry) == [
        "ohlcv_x: scripts/rogue.py writes it outside the registered writers "
        "['services/owner.py'] (single_writer)"
    ]


def test_fake_asyncpg_copy_counts_as_a_write(tmp_path):
    files = {"services/a.py": 'await conn.copy_records_to_table(\n    "ohlcv_x", records=r)'}
    assert _violations(tmp_path, files, {"ohlcv_x": ()}) == [
        "ohlcv_x: services/a.py writes it outside the registered writers (none) (single_writer)"
    ]


def test_fake_two_writers_pass_only_with_disjoint_segments(tmp_path):
    files = {
        "services/a.py": 'SQL = "INSERT INTO ohlcv_x VALUES (1)"',
        "services/b.py": 'SQL = "UPDATE ohlcv_x SET a = 1"',
    }
    unsegmented = {"ohlcv_x": (Writer("services/a.py"), Writer("services/b.py"))}
    assert len(_violations(tmp_path, files, unsegmented)) == 1
    disjoint = {
        "ohlcv_x": (
            Writer("services/a.py", _segment("timeframe", "1d")),
            Writer("services/b.py", _segment("timeframe", "5m", "1m")),
        )
    }
    assert _violations(tmp_path, files, disjoint) == []
    overlapping = {
        "ohlcv_x": (
            Writer("services/a.py", _segment("timeframe", "1d", "5m")),
            Writer("services/b.py", _segment("timeframe", "5m")),
        )
    }
    assert _violations(tmp_path, files, overlapping) == [
        "ohlcv_x: services/a.py and services/b.py overlap on timeframe ['5m']"
    ]
    complement = {
        "ohlcv_x": (
            Writer("services/a.py", None),
            Writer("services/b.py", _segment("timeframe", "5m")),
        )
    }
    assert _violations(tmp_path, files, complement) == []
    temporary = {
        "ohlcv_x": (
            Writer("services/a.py"),
            Writer("services/b.py", reason="TEMPORARY: second writer (retire: 185-99)"),
        )
    }
    assert _violations(tmp_path, files, temporary) == []


def test_fake_canonical_table_missing_from_registry_fails(tmp_path):
    assert _violations(tmp_path, {}, {}, canonical=("ohlcv_x",)) == [
        "ohlcv_x: canonical table with no _REGISTRY entry (register its single writer)"
    ]
    assert _violations(tmp_path, {}, {"ohlcv_gone": ()}, canonical=()) == [
        "ohlcv_gone: registered but no longer created by the migrations; remove the entry"
    ]


def test_fake_registered_writer_that_stopped_writing_is_stale(tmp_path):
    files = {"services/a.py": 'SQL = "SELECT 1 FROM ohlcv_x"'}
    assert _violations(tmp_path, files, {"ohlcv_x": (Writer("services/a.py"),)}) == [
        "ohlcv_x: registered writer services/a.py no longer writes it; remove it"
    ]


def test_fake_covered_entry_needs_its_dedicated_test(tmp_path):
    registry = {"ohlcv_x": Covered("tests/unit/test_ohlcv_x_writer_boundary.py")}
    assert _violations(tmp_path, {}, registry) == [
        "ohlcv_x: dedicated test tests/unit/test_ohlcv_x_writer_boundary.py does not exist"
    ]
    files = {"tests/unit/test_ohlcv_x_writer_boundary.py": "# guards nothing"}
    assert _violations(tmp_path, files, registry) == [
        "ohlcv_x: dedicated test tests/unit/test_ohlcv_x_writer_boundary.py never names it"
    ]
    files = {"tests/unit/test_ohlcv_x_writer_boundary.py": '_TABLE = "ohlcv_x"'}
    assert _violations(tmp_path, files, registry) == []


def test_canonical_table_rule_matches_the_data_layer_names():
    assert _canonical_tables(
        ["ohlcv_load", "bar_source_policy", "market_data_ohlcv", "feature_vectors", "instruments"]
    ) == {"ohlcv_load", "bar_source_policy", "market_data_ohlcv"}
