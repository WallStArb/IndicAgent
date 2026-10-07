"""Tests for services/intraday_raw_archive.py (phase 185 plan 12, task 1a).

The module is the ONE writer of ohlcv_intraday_raw_archive (single_writer):
bar_derivation's archive-from-table INSERT ... SELECT statement moved here
byte-identical from services/bar_derivation.py (which imports it back), and
insert_fetched_archive_rows() is the fetched-chunk insert the historical
pipeline's 15m/1h path calls. Fake cursor only, no DB.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from services.intraday_raw_archive import ARCHIVE_FROM_TABLE_SQL, insert_fetched_archive_rows
from services.ohlcv_ingress_contract import RevisionRefused


class FakeCursor:
    """Records statements; serves the contract's two reads (thresholds, stored archive rows)."""

    def __init__(self, stored: list[tuple] | None = None) -> None:
        self.executed: list[tuple[str, tuple | list]] = []
        self.stored = stored or []
        self._result: list[tuple] = []

    def execute(self, sql: str, params: tuple | list | None = None) -> None:
        self.executed.append((sql, params if params is not None else ()))
        if sql.startswith("SELECT config_key"):
            self._result = [
                ("threshold.bar_integrity.max_revision_ratio", "0.02"),
                ("threshold.bar_integrity.revision_ratio_min_stored", "500"),
            ]
        elif sql.startswith("SELECT"):
            self._result = self.stored

    def fetchall(self) -> list[tuple]:
        return self._result

    def sql(self, prefix: str) -> list[tuple[str, tuple | list]]:
        return [(s, p) for s, p in self.executed if s.startswith(prefix)]


_T0 = datetime(2026, 9, 27, 14, 30, tzinfo=UTC)


def _rows(*sources: str) -> list[tuple]:
    """One distinct 1h bar per source (timestamps an hour apart)."""
    return [
        (
            _T0 + timedelta(hours=i),
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


def _stored(rows: list[tuple]) -> list[tuple]:
    return [(r[0], r[3], r[4], r[5], r[6], r[7], r[8]) for r in rows]


class TestInsertFetchedArchiveRows:
    def test_builds_one_multirow_values_insert_of_new_rows_and_returns_row_count(self):
        cur = FakeCursor()
        rows = _rows("ibkr", "ibkr")
        n = insert_fetched_archive_rows(cur, rows)
        assert n == 2
        sql, params = cur.sql("INSERT INTO ohlcv_intraday_raw_archive")[0]
        assert len(cur.sql("INSERT INTO ohlcv_intraday_raw_archive")) == 1
        assert "ON CONFLICT" not in sql  # new rows only; the contract classified them
        assert sql.count("(%s") == 2  # two row placeholders in one statement
        assert len(params) == 20  # 10 columns x 2 rows
        assert params[1] == "SPY" and params[9] is None  # base is NULL for fetched bars
        (load,) = cur.sql("INSERT INTO ohlcv_load")
        assert load[1][3] == "ibkr" and load[1][14] == "archive" and load[1][8] == 2

    def test_the_same_answer_twice_writes_nothing_but_its_load_row(self):
        rows = _rows("ibkr", "ibkr", "ibkr")
        cur = FakeCursor(_stored(rows))
        assert insert_fetched_archive_rows(cur, rows) == 3
        assert cur.sql("INSERT INTO ohlcv_intraday_raw_archive") == []
        assert cur.sql("INSERT INTO ohlcv_revision") == []
        (load,) = cur.sql("INSERT INTO ohlcv_load")
        assert load[1][8:10] == (0, 0) and load[1][15] == 3  # n_new, n_changed, n_unchanged

    def test_a_changed_row_is_an_upsert_with_its_old_values_in_ohlcv_revision(self):
        old = _rows("ibkr", "ibkr")
        new = [old[0], old[1][:6] + (600.75,) + old[1][7:]]
        cur = FakeCursor(_stored(old))
        insert_fetched_archive_rows(cur, new)
        sql, params = cur.sql("INSERT INTO ohlcv_intraday_raw_archive")[0]
        assert "ON CONFLICT" in sql and "DO UPDATE SET" in sql and "DO NOTHING" not in sql
        assert tuple(params[3:7]) == (600.0, 601.0, 599.0, 600.75)
        (revision,) = cur.sql("INSERT INTO ohlcv_revision")
        assert revision[1][3] == old[1][0] and revision[1][7] == 600.5  # old close
        assert cur.sql("INSERT INTO ohlcv_load")[0][1][9] == 1  # n_changed

    def test_a_breach_is_refused_before_any_archive_write(self):
        old = [
            (
                _T0 + timedelta(minutes=15 * i),
                "SPY",
                "15m",
                600.0,
                601.0,
                599.0,
                600.5,
                100,
                "ibkr",
                None,
            )
            for i in range(1000)
        ]
        new = [row[:6] + (601.0,) + row[7:] if i < 30 else row for i, row in enumerate(old)]
        cur = FakeCursor(_stored(old))
        with pytest.raises(RevisionRefused):
            insert_fetched_archive_rows(cur, new)
        assert cur.sql("INSERT") == []

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
        inserts = cur.sql("INSERT INTO ohlcv_intraday_raw_archive")
        assert [len(params) // 10 for _sql, params in inserts] == [10, 10, 5]


class TestArchiveFromTableSql:
    """The statement bar_derivation moved here (plan 11's only archive INSERT)."""

    def test_has_no_first_write_wins_clause_and_no_dead_synthetic_filter(self):
        assert "ON CONFLICT" not in ARCHIVE_FROM_TABLE_SQL
        assert "synthetic_fill" not in ARCHIVE_FROM_TABLE_SQL
        assert "source <> 'derived_5m'" in ARCHIVE_FROM_TABLE_SQL

    def test_inserts_only_keys_the_archive_does_not_hold(self):
        sql = " ".join(ARCHIVE_FROM_TABLE_SQL.split())
        assert "NOT EXISTS ( SELECT 1 FROM ohlcv_intraday_raw_archive a" in sql
        for column in ('a."timestamp"', "a.symbol", "a.timeframe"):
            assert column in sql

    def test_uses_parameter_placeholders(self):
        assert "$1" in ARCHIVE_FROM_TABLE_SQL and "$2" in ARCHIVE_FROM_TABLE_SQL
        assert "$3::uuid" in ARCHIVE_FROM_TABLE_SQL

    def test_bar_derivation_imports_it_back_and_defines_no_insert_of_its_own(self):
        import services.bar_derivation

        text = Path(services.bar_derivation.__file__).read_text()
        assert "INSERT INTO ohlcv_intraday_raw_archive" not in text
        assert "ARCHIVE_FROM_TABLE_SQL" in text
