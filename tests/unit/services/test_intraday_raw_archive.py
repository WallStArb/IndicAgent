"""Tests for services/intraday_raw_archive.py (phase 185 plan 12; legacy since 191-05).

The module keeps only bar_derivation's archive-from-table INSERT ... SELECT statement (moved here
byte-identical from services/bar_derivation.py, which imports it back); the fetched-chunk writers
left with phase 191 plan 05 (the fetcher and the Alpaca loader write ohlcv_raw). No DB.
"""

from __future__ import annotations

from pathlib import Path

from services.intraday_raw_archive import ARCHIVE_FROM_TABLE_SQL


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

    def test_the_fetch_path_writers_are_gone(self):
        import services.intraday_raw_archive as module

        for retired in ("insert_fetched_archive_rows", "archive_refusal_rows"):
            assert not hasattr(module, retired)
