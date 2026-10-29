"""Source-level contract test for migration 472 (ohlcv_raw, phase 191 plan 01).

Reads the .sql file as text: no DB, no network, CI-clean. Whole-line SQL comments are stripped
before matching so a header sentence cannot satisfy an assertion about the real DDL.
"""

from __future__ import annotations

import re

from src.intelligence.bars.vendor_kind import BAR_KINDS, BAR_VENDORS, LABEL_TO_VENDOR_KIND
from tests.unit._source_grep_helpers import read_source

_SQL_LINE_COMMENT_RE = re.compile(r"(?m)^\s*--[^\n]*")
_NAME = "472_ohlcv_raw_unified_table.sql"


def _sql() -> str:
    return _SQL_LINE_COMMENT_RE.sub("", read_source("production", "migrations", _NAME))


def _table_body(sql: str) -> str:
    start = sql.index("CREATE TABLE IF NOT EXISTS ohlcv_raw")
    return sql[start : sql.index(");\n\nSELECT create_hypertable", start)]


def test_creates_ohlcv_raw_with_the_ten_spec_columns():
    body = _table_body(_sql())
    for column, decl in (
        ('"timestamp"', "timestamptz NOT NULL"),
        ("symbol", "text NOT NULL REFERENCES instruments(symbol)"),
        ("timeframe", "text NOT NULL"),
        ("vendor", "text NOT NULL"),
        ("kind", "text NOT NULL"),
        ("open", "double precision NOT NULL"),
        ("high", "double precision NOT NULL"),
        ("low", "double precision NOT NULL"),
        ("close", "double precision NOT NULL"),
        ("volume", "bigint,"),
        ("served_at", "timestamptz,"),
        ("request_id", "uuid,"),
        ("load_id", "uuid,"),
    ):
        assert re.search(rf"(?m)^\s+{re.escape(column)} {re.escape(decl)}", body), column
    # served_at, request_id and load_id are nullable (no NOT NULL on their lines)
    for nullable in ("served_at", "request_id", "load_id", "volume"):
        line = re.search(rf"(?m)^\s+{nullable} [^\n]*", body)
        assert line and "NOT NULL" not in line.group(0), nullable


def test_primary_key_and_finite_check_and_no_vendor_kind_check():
    sql = _sql()
    body = _table_body(sql)
    assert 'PRIMARY KEY ("timestamp", symbol, timeframe, vendor, kind)' in body
    for column in ("open", "high", "low", "close"):
        for bad in ("NaN", "Infinity", "-Infinity"):
            assert f"{column} <> '{bad}'::double precision" in body
    assert not re.search(r"CHECK[^;]*\b(vendor|kind)\s+(IN|=)", body)
    assert not re.search(r"ALTER TABLE ohlcv_raw[^;]*(vendor|kind)[^;]*CHECK", sql)


def test_hypertable_and_compression_without_a_policy():
    sql = _sql()
    assert re.search(
        r"create_hypertable\('ohlcv_raw', 'timestamp',\s*chunk_time_interval => INTERVAL '30 days'",
        sql,
    )
    assert "timescaledb.compress_segmentby = 'symbol, timeframe, vendor'" in sql
    assert "add_compression_policy" not in sql


def test_grant_is_insert_select_update_to_the_bar_writer_only():
    sql = _sql()
    grants = re.findall(r"GRANT[^;]*ohlcv_raw[^;]*;", sql)
    assert grants == ["GRANT INSERT, SELECT, UPDATE ON ohlcv_raw TO bar_derivation_writer;"]


def _seed_codes(sql: str, namespace: str) -> list[str]:
    return re.findall(rf"\('{namespace}', '([^']+)', ", sql)


def test_cvr_seeds_equal_the_vendor_kind_module():
    sql = _sql()
    assert tuple(_seed_codes(sql, "bar_vendor")) == BAR_VENDORS
    # 472 seeded the original eleven kinds; iex_rth joined later (migration 511, the alpaca
    # iex feed), so it is the one BAR_KINDS entry 472 does not carry.
    assert tuple(_seed_codes(sql, "bar_kind")) == tuple(k for k in BAR_KINDS if k != "iex_rth")
    assert "ON CONFLICT (namespace, code) DO NOTHING" in sql


def test_revision_mapping_values_equal_the_vendor_kind_module():
    sql = _sql()
    block = sql[
        sql.index("UPDATE ohlcv_revision r") : sql.index(
            "DROP CONSTRAINT IF EXISTS ohlcv_revision_origin_check"
        )
    ]
    pairs = dict(
        (label, (vendor, kind))
        for label, vendor, kind in re.findall(r"\('([^']+)', '([^']+)', '([^']+)'\)", block)
    )
    # Migration 472 is history: it still maps the retired vendor's label, which the module dropped.
    assert pairs == {**LABEL_TO_VENDOR_KIND, "tradier": ("tradier", "consolidated")}


def test_revision_gains_nullable_columns_and_admits_raw():
    sql = _sql()
    for column, sql_type in (("vendor", "text"), ("kind", "text"), ("request_id", "uuid")):
        assert f"ALTER TABLE ohlcv_revision ADD COLUMN IF NOT EXISTS {column} {sql_type};" in sql
    assert "ohlcv_revision" not in "".join(re.findall(r"[^;]*SET NOT NULL[^;]*;", sql))
    assert "ADD PRIMARY KEY" not in sql
    assert "CHECK (origin IN ('load', 'archive_segment', 'raw'))" in sql


def test_load_and_policy_checks():
    sql = _sql()
    assert "ALTER TABLE ohlcv_load DROP CONSTRAINT IF EXISTS ohlcv_load_source_check;" in sql
    assert "ADD CONSTRAINT ohlcv_load_source_check" not in sql
    assert "CHECK (destination IN ('d1', 'market_data_ohlcv', 'archive', 'raw'))" in sql
    assert "a.attname IN ('primary_source', 'fallback_source')" in sql
    assert "array_length(con.conkey, 1) = 1" in sql
    assert "DROP CONSTRAINT %I" in sql


def test_additive_only():
    sql = _sql()
    assert "decompress_chunk" not in sql
    assert "compress_chunk" not in sql


def test_migration_476_seeds_one_bar_kind_per_venue_route():
    from src.intelligence.bars.vendor_kind import VENUE_ROUTE_KINDS

    sql = _SQL_LINE_COMMENT_RE.sub(
        "", read_source("production", "migrations", "476_bar_kind_venue_routes.sql")
    )
    assert tuple(_seed_codes(sql, "bar_kind")) == tuple(VENUE_ROUTE_KINDS)
    assert "ON CONFLICT (namespace, code) DO NOTHING" in sql
