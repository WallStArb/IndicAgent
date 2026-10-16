"""Source-level contract for the market_data_ohlcv_v2 migration (phase 191 plan 12).

Design doc step 7, first half: canonical `source` becomes `vendor` plus `kind`. `UPDATE
market_data_ohlcv` is banned and the dependent views block a column drop, so the migration
creates an empty `market_data_ohlcv_v2` (structurally identical to the live table except
`source` is replaced by `vendor` and `kind`) and seeds the five `infra.canonical_swap.*` APR
keys the build script reads. The copy, the proof and the swap are the script's, not the
migration's, because each step depends on the one before it passing. CI-clean: reads files only.

The migration number is the next free one at execution time; this test finds the file by its
subject stem, never a hardcoded number.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit._migration_catalog import migration_catalog
from tests.unit._source_grep_helpers import read_source

_MIGRATIONS = Path(__file__).parent.parent.parent / "production" / "migrations"
_V2 = "market_data_ohlcv_v2"

_APR_KEYS = (
    "infra.canonical_swap.disk_margin",
    "infra.canonical_swap.statement_timeout_s",
    "infra.canonical_swap.copy_statement_timeout_s",
    "infra.canonical_swap.lock_timeout_s",
    "infra.canonical_swap.stats_flush_wait_s",
)


def _migration_path() -> Path:
    matches = sorted(_MIGRATIONS.glob("*_market_data_ohlcv_v2_vendor_kind.sql"))
    assert matches, "no *_market_data_ohlcv_v2_vendor_kind.sql migration found"
    return matches[0]


def _sql() -> str:
    """The migration with comments stripped and whitespace collapsed: the assertions check the
    presence of statements, not the file's line wrapping."""
    stripped = re.sub(r"--[^\n]*", "", read_source(*_migration_path().parts[-3:]))
    return re.sub(r"\s+", " ", stripped)


def test_v2_is_created_empty_with_vendor_and_kind_and_no_source_column() -> None:
    sql = _sql()
    body = sql[sql.index("CREATE TABLE") : sql.index(");", sql.index("CREATE TABLE"))]
    for column, definition in (
        ("vendor", r"vendor text\s+CONSTRAINT market_data_ohlcv_v2_vendor_not_null NOT NULL"),
        ("kind", r"kind text\s+CONSTRAINT market_data_ohlcv_v2_kind_not_null NOT NULL"),
    ):
        assert re.search(definition, body), f"{column} column missing or not NOT NULL"
    assert not re.search(r"\bsource\b\s+text", body), "v2 must not carry a source column"
    # The shared columns keep the live table's NOT NULL constraint names, so the swap's
    # index and constraint renames stay mechanical.
    for name in ("timestamp", "symbol", "timeframe", "open", "high", "low", "close", "volume"):
        assert re.search(
            rf"CONSTRAINT market_data_ohlcv_{name}_not_null NOT NULL", body
        ), f"{name} constraint name drifted from the live table's"


def test_v2_shape_matches_the_live_table() -> None:
    sql = _sql()
    assert "create_hypertable" in sql
    assert "by_range('timestamp', INTERVAL '90 days')" in sql
    assert "create_default_indexes => false" in sql
    assert "timescaledb.compress" in sql
    assert "timescaledb.compress_segmentby = 'symbol, timeframe'" in sql
    assert "timescaledb.compress_orderby = '\"timestamp\" ASC'" in sql
    assert (
        "CREATE UNIQUE INDEX market_data_ohlcv_pkey_idx_rebuilt "
        'ON market_data_ohlcv_v2 ("timestamp", symbol, timeframe)' in sql
    )
    assert (
        "CREATE INDEX idx_ohlcv_symbol_tf_time_rebuilt "
        'ON market_data_ohlcv_v2 (symbol, timeframe, "timestamp" DESC)' in sql
    )
    assert (
        "GRANT SELECT, INSERT, UPDATE, DELETE ON market_data_ohlcv_v2 "
        "TO bar_derivation_writer" in sql
    )
    assert "autovacuum_vacuum_scale_factor = 0.05" in sql
    assert "autovacuum_analyze_scale_factor = 0.02" in sql


def test_migration_is_idempotent_and_never_decompresses() -> None:
    sql = _sql()
    assert (
        "to_regclass('public.market_data_ohlcv_v2')" in sql
    ), "re-applying must be safe: the create is guarded by a to_regclass check"
    assert (
        "decompress_chunk(" not in sql
    ), "the build copies into an empty table; decompressing live chunks is the 768 GB class"
    for table in ("config_schema", "config_state", "config_history"):
        assert f"INSERT INTO {table}" in sql
    assert sql.count("ON CONFLICT") >= 3


def test_the_five_canonical_swap_apr_keys_are_seeded_with_history() -> None:
    sql = _sql()
    for key in _APR_KEYS:
        assert sql.count(f"'{key}'") >= 3, f"{key} must be seeded in schema, state and history"
        assert "Not an ML learning target." in sql
    # The copy runs while every writer is held; no masked-slot-era key rides along.
    assert "masked_audit" not in sql
    assert "infra.real_rows_swap" not in sql


# --- the views swap migration (phase 191 plan 14) -------------------------------------------------


def _views_migration_path() -> Path:
    matches = sorted(_MIGRATIONS.glob("*_market_data_ohlcv_vendor_kind_views.sql"))
    assert matches, "no *_market_data_ohlcv_vendor_kind_views.sql migration found"
    return matches[0]


def _views_sql() -> str:
    stripped = re.sub(r"--[^\n]*", "", read_source(*_views_migration_path().parts[-3:]))
    return re.sub(r"\s+", " ", stripped)


def test_views_migration_renames_both_tables_as_literal_text_in_order() -> None:
    sql = _views_sql()
    first = "ALTER TABLE market_data_ohlcv RENAME TO market_data_ohlcv_old;"
    second = "ALTER TABLE market_data_ohlcv_v2 RENAME TO market_data_ohlcv;"
    # The catalog (tests/unit/_migration_catalog.py) parses ALTER RENAME from migration text
    # only, applied in file order: the live table must rename away before v2 takes the name.
    assert first in sql, "the live table's rename away is missing or not a literal statement"
    assert second in sql, "v2's rename into place is missing or not a literal statement"
    assert sql.index(first) < sql.index(second), "ohlcv must rename away before v2 takes the name"


def test_views_migration_recreates_the_four_views_and_moves_the_policy() -> None:
    sql = _views_sql()
    for view in (
        "market_data_ohlcv_tradeable",
        "market_data_ohlcv_scrub_input",
        "market_data_5m",
        "canonical_bar_lineage",
    ):
        assert f"DROP VIEW {view};" in sql, f"{view} is not dropped"
        assert f"CREATE VIEW {view} AS" in sql, f"{view} is not recreated"
        assert sql.index(f"DROP VIEW {view};") < sql.index(f"CREATE VIEW {view} AS"), view
    # ohlcv_venue_head moved onto ohlcv_raw in plan 09; the swap must never touch it.
    assert "ohlcv_venue_head" not in sql
    # The tradeable view nulls volume by kind, not by label.
    assert "kind IN ('venue', 'fallback')" in sql
    assert "ibkr_venue" not in sql and "ibkr_fallback" not in sql
    # The original grants ride with the recreated views (market_data_5m carries none).
    assert (
        "GRANT SELECT ON market_data_ohlcv_tradeable, market_data_ohlcv_scrub_input, "
        "canonical_bar_lineage TO bar_derivation_writer" in sql
    )
    # The compression policy moves with the name: same compress_after and schedule.
    assert "alter_job" in sql and "scheduled => false" in sql
    assert "add_compression_policy" in sql


def test_views_migration_catalog_resolves_the_swapped_names() -> None:
    tables, _ = migration_catalog()
    assert "market_data_ohlcv" in tables
    assert "market_data_ohlcv_old" in tables, "the kept original must resolve in the catalog"
    assert _V2 not in tables, "v2 renamed away must no longer resolve in the catalog"
