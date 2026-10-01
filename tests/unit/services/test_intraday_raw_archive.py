"""Tests for services/intraday_raw_archive.py (phase 185 plan 12, task 1a).

The module is the ONE writer of ohlcv_intraday_raw_archive (single_writer):
bar_derivation's archive-from-table INSERT ... SELECT statement moved here
byte-identical from services/bar_derivation.py (which imports it back), and
insert_fetched_archive_rows() is the fetched-chunk insert the historical
pipeline's 15m/1h path calls. Fake cursor only, no DB.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from services.intraday_raw_archive import ARCHIVE_FROM_TABLE_SQL, insert_fetched_archive_rows


class FakeCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple | list]] = []

    def execute(self, sql: str, params: tuple | list | None = None) -> None:
        self.executed.append((sql, params if params is not None else ()))


def _rows(*sources: str) -> list[tuple]:
    return [
        (
            datetime(2026, 9, 27, 14, 30, tzinfo=UTC),
            "SPY",
            "1h",
            600.0,
            601.0,
            599.0,
            600.5,
            1_000 + i,
            source,
            None,
        )
        for i, source in enumerate(sources)
    ]


class TestInsertFetchedArchiveRows:
    def test_builds_one_multirow_values_insert_and_returns_row_count(self):
        cur = FakeCursor()
        rows = _rows("ibkr", "ibkr")
        n = insert_fetched_archive_rows(cur, rows)
        assert n == 2
        assert len(cur.executed) == 1
        sql, params = cur.executed[0]
        assert "INSERT INTO ohlcv_intraday_raw_archive" in sql
        assert "ON CONFLICT DO NOTHING" in sql
        assert sql.count("(%s") == 2  # two row placeholders in one statement
        assert len(params) == 20  # 10 columns x 2 rows
        assert params[1] == "SPY" and params[9] is None  # base is NULL for fetched bars

    def test_refuses_synthetic_fills(self):
        """A synthetic fill is not an observation; the archive stores answers
        only (D-15, todo 462)."""
        cur = FakeCursor()
        with pytest.raises(ValueError, match="synthetic_fill"):
            insert_fetched_archive_rows(cur, _rows("ibkr", "synthetic_fill"))
        assert cur.executed == []

    def test_empty_rows_is_a_noop(self):
        cur = FakeCursor()
        assert insert_fetched_archive_rows(cur, []) == 0
        assert cur.executed == []

    def test_batch_size_chunks_the_insert(self):
        cur = FakeCursor()
        rows = _rows(*(["ibkr"] * 25))
        insert_fetched_archive_rows(cur, rows, batch_size=10)
        assert [len(params) // 10 for _sql, params in cur.executed] == [10, 10, 5]


class TestArchiveFromTableSql:
    """The statement bar_derivation moved here (plan 11's only archive INSERT)."""

    def test_excludes_synthetic_fills_and_uses_parameter_placeholders(self):
        assert "source <> 'synthetic_fill'" in ARCHIVE_FROM_TABLE_SQL
        assert "ON CONFLICT DO NOTHING" in ARCHIVE_FROM_TABLE_SQL
        assert "$1" in ARCHIVE_FROM_TABLE_SQL and "$2" in ARCHIVE_FROM_TABLE_SQL

    def test_bar_derivation_imports_it_back_and_defines_no_insert_of_its_own(self):
        bar_derivation = Path(__file__).parent.parent.parent / "services" / "bar_derivation.py"
        text = bar_derivation.read_text()
        assert "INSERT INTO ohlcv_intraday_raw_archive" not in text
        assert "ARCHIVE_FROM_TABLE_SQL" in text
