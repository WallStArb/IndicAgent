"""Contract test for migration 383 (D2b archive + bar content digest, plan 11).

Source-grep pin, same shape as test_bar_quality_flag_migration_contract.py: the
migration is applied live, so this guards the file (what future replays and
reviewers see) against silent drift from the D-07/D-15 contract: append-only
archive and digest, the digest-current view, the role grants 185-01 A7 measured
safe, both APR keys, and the recorded write method.
"""

from __future__ import annotations

import re
from pathlib import Path

_SOURCE = Path(__file__).resolve().parents[2] / "production" / "migrations" / "383_derived_grid.sql"


def read_source() -> str:
    sql = _SOURCE.read_text()
    return re.sub(r"--[^\n]*", "", sql)  # strip comments; assertions target code


def test_archive_table_hypertable_and_compression() -> None:
    sql = read_source()
    assert "CREATE TABLE IF NOT EXISTS ohlcv_intraday_raw_archive" in sql
    assert 'PRIMARY KEY ("timestamp", symbol, timeframe)' in sql
    assert "archived_at timestamptz NOT NULL DEFAULT now()" in sql
    assert "batch_id uuid REFERENCES bar_derivation_batch(batch_id)" in sql
    assert "create_hypertable" in sql
    assert "'ohlcv_intraday_raw_archive'" in sql
    assert "INTERVAL '3 months'" in sql  # market_data_ohlcv's own chunk interval
    assert "timescaledb.compress_segmentby = 'symbol, timeframe'" in sql
    assert "timescaledb.compress_orderby = '\"timestamp\" ASC'" in sql
    assert "add_compression_policy" in sql


def test_digest_table_keys() -> None:
    sql = read_source()
    assert "CREATE TABLE IF NOT EXISTS bar_content_digest" in sql
    assert "PRIMARY KEY (symbol, timeframe, range_start, computed_at)" in sql
    assert "digest text NOT NULL" in sql
    assert "algorithm text NOT NULL" in sql
    assert "rule_version text NOT NULL" in sql
    assert "n_rows integer NOT NULL" in sql


def test_append_only_triggers_on_both_tables() -> None:
    sql = read_source()
    for table in ("ohlcv_intraday_raw_archive", "bar_content_digest"):
        assert f"BEFORE UPDATE OR DELETE ON {table}" in sql
        assert f"BEFORE TRUNCATE ON {table}" in sql
    assert sql.count("EXECUTE FUNCTION bar_derivation_append_only()") == 4


def test_current_view_is_distinct_on_latest() -> None:
    sql = read_source()
    assert "CREATE OR REPLACE VIEW bar_content_digest_current" in sql
    view = sql.split("CREATE OR REPLACE VIEW bar_content_digest_current")[1]
    assert "DISTINCT ON (symbol, timeframe, range_start)" in view
    assert "ORDER BY symbol, timeframe, range_start, computed_at DESC" in view


def test_role_grants_match_the_measured_role_result() -> None:
    sql = read_source()
    # 185-01 A7: the NOLOGIN role CAN DML compressed chunks, so the grants are live.
    assert "GRANT INSERT, SELECT ON ohlcv_intraday_raw_archive, bar_content_digest" in sql
    assert "GRANT SELECT, INSERT, DELETE ON market_data_ohlcv TO bar_derivation_writer" in sql
    assert "GRANT SELECT ON bar_content_digest_current TO bar_derivation_writer" in sql


def test_both_apr_keys_seeded() -> None:
    sql = read_source()
    for key, value in (
        ("infra.bar_derivation.grid_symbol_batch", "10"),
        ("infra.bar_derivation.grid_write_method", "segment_delete_copy"),
    ):
        assert f"'{key}'" in sql
        assert f"('{key}', '{value}'" in sql


def test_header_records_write_method_and_role_result() -> None:
    header = _SOURCE.read_text().split("BEGIN;")[0]
    assert "segment_delete_copy" in header
    assert "185-01" in header


def test_no_decompression_so_no_vacuum_clause_needed() -> None:
    sql = read_source()
    assert "decompress_chunk" not in sql
