"""Unit tests for the data adjacency diff (todo 603, rung 0).

CI-clean: no DB, no network. The diff logic is tested against a fake
information_schema column map; the register doc is parsed from disk so the
script's SERVED_FIELDS mapping and docs/reference/data-adjacency-register.md
cannot drift apart silently (the doc's "The diff script" section promises they
move together).
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.ops.ops_adjacency_diff import (
    NOT_STORED,
    PARTIAL,
    SERVED_FIELDS,
    STORED,
    ServedField,
    diff,
    field_verdict,
)

_REPO_ROOT = Path(__file__).parent.parent.parent
_REGISTER_DOC = _REPO_ROOT / "docs" / "reference" / "data-adjacency-register.md"

# Tables the register doc names as storage locations; a target outside this set
# is almost certainly a typo, since the doc and the mapping are one seed.
_KNOWN_STORAGE_TABLES = frozenset(
    {
        "ohlcv_raw",
        "listing_end",
        "borrow_availability_snapshots",
        "dividend_events",
        "corporate_action",
        "economic_series_observation",
    }
)


def _register_field_cells() -> list[str]:
    rows = [
        line
        for line in _REGISTER_DOC.read_text().splitlines()
        if line.startswith("|") and not set(line) <= {"|", "-", " ", ":"}
    ]
    cells = []
    for row in rows:
        parts = [part.strip() for part in row.split("|")]
        if len(parts) > 2 and parts[1] not in ("Field", ""):
            cells.append(parts[1].replace("`", ""))
    return cells


def test_every_served_field_appears_in_the_register_doc():
    cells = _register_field_cells()
    missing = [
        field.field for field in SERVED_FIELDS if not any(field.field in cell for cell in cells)
    ]
    assert not missing, f"SERVED_FIELDS entries with no register doc table row: {missing}"


def test_every_target_names_a_known_storage_table():
    bad = [
        (field.field, table)
        for field in SERVED_FIELDS
        for table, _column in field.targets
        if table not in _KNOWN_STORAGE_TABLES
    ]
    assert not bad, f"targets referencing tables the register doc does not store into: {bad}"


def test_target_tables_and_columns_are_well_formed():
    for field in SERVED_FIELDS:
        assert field.source and field.field
        for table, column in field.targets:
            assert table and column


def test_field_verdict_full_targets_present_is_stored():
    field = ServedField("s", "f", (("t1", "a"), ("t1", "b")))
    stored = {"t1": {"a", "b"}}
    assert field_verdict(field, stored) == (STORED, [])


def test_field_verdict_some_targets_missing_is_partial():
    field = ServedField("s", "f", (("t1", "a"), ("t1", "b")))
    stored = {"t1": {"a"}}
    verdict, missing = field_verdict(field, stored)
    assert verdict == PARTIAL
    assert missing == ["t1.b"]


def test_field_verdict_no_targets_and_no_hits_is_not_stored():
    no_targets = ServedField("s", "f", ())
    assert field_verdict(no_targets, {"t1": {"a"}}) == (NOT_STORED, [])
    unknown_table = ServedField("s", "f", (("missing", "col"),))
    verdict, missing = field_verdict(unknown_table, {"t1": {"a"}})
    assert verdict == NOT_STORED
    assert missing == ["missing.col"]


def test_diff_groups_all_fields_by_source():
    stored = {"ohlcv_raw": {"open", "volume"}, "dividend_events": {"ex_date"}}
    by_source = diff(SERVED_FIELDS, stored)
    grouped = {source for source, verdicts in by_source.items() for _ in verdicts}
    assert grouped == {field.source for field in SERVED_FIELDS}
    total_fields = sum(
        len(fields) for verdicts in by_source.values() for fields in verdicts.values()
    )
    assert total_fields == len(SERVED_FIELDS)


def test_served_field_sources_are_stable_strings():
    # The report aligns columns on these names; keep them lowercase plain text.
    for field in SERVED_FIELDS:
        assert re.fullmatch(r"[a-z0-9 /-]+", field.source), field.source
