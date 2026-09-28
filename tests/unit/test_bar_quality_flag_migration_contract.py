"""Contract test for migration 381 (bar_quality_flag quarantine, phase 185 plan 04).

Source-grep pin, same shape as test_ohlcv_observation_migration_contract.py: the
migration is applied live, so this guards the file (what future replays and
reviewers see) against silent drift from the D-09 quarantine contract.
"""

from __future__ import annotations

import re
from pathlib import Path

_SOURCE = (
    Path(__file__).resolve().parents[2] / "production" / "migrations" / "381_bar_quality_flag.sql"
)


def read_source() -> str:
    sql = _SOURCE.read_text()
    return re.sub(r"--[^\n]*", "", sql)  # strip comments; assertions target code


def test_both_tables_created_with_keys() -> None:
    sql = read_source()
    assert "CREATE TABLE IF NOT EXISTS bar_derivation_batch" in sql
    assert "CREATE TABLE IF NOT EXISTS bar_quality_flag" in sql
    assert 'PRIMARY KEY (symbol, timeframe, "timestamp", rule)' in sql
    assert "batch_id uuid PRIMARY KEY" in sql
    assert "REFERENCES bar_derivation_batch(batch_id)" in sql
    assert "WHERE quarantine" in sql  # partial index


def test_tradeable_view_anti_join_and_column_order() -> None:
    sql = read_source()
    assert "CREATE OR REPLACE VIEW market_data_ohlcv_tradeable" in sql
    assert "NOT EXISTS" in sql and "q.quarantine" in sql
    assert "price_sanity_status IS DISTINCT FROM 'confirmed_corrupt'" in sql
    view = sql.split("CREATE OR REPLACE VIEW market_data_ohlcv_tradeable")[1]
    select_list = view.split("SELECT", 1)[1].split("FROM market_data_ohlcv")[0]
    columns = [c.strip().split(" AS ")[-1].strip() for c in select_list.split(",")]
    assert [c.lstrip('"').rstrip('"') for c in columns] == [
        "timestamp",
        "symbol",
        "timeframe",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "source",
        "base",
        "price_sanity_status",
    ]


def test_scrub_input_view_and_index_drop() -> None:
    sql = read_source()
    assert "CREATE OR REPLACE VIEW market_data_ohlcv_scrub_input" in sql
    assert "DROP INDEX IF EXISTS idx_market_data_ohlcv_price_sanity_unaudited" in sql
    assert "GRANT SELECT ON market_data_ohlcv_scrub_input TO bar_derivation_writer" in sql


def test_legacy_status_copy_shape() -> None:
    sql = read_source()
    assert "'legacy_price_sanity_status', 'legacy'" in sql
    assert "price_sanity_status = 'confirmed_corrupt'" in sql
    assert "WHERE price_sanity_status IS NOT NULL" in sql


def test_nine_apr_keys_in_all_three_blocks() -> None:
    sql = read_source()
    keys = [
        "threshold.bar_scrub.jump_sigma",
        "threshold.bar_scrub.jump_vol_window",
        "threshold.bar_scrub.stale_run_min",
        "threshold.bar_scrub.volume_outlier_mad",
        "threshold.bar_scrub.volume_window",
        "threshold.bar_scrub.corroboration_max_clearable_ratio",
        "threshold.bar_scrub.view_disagreement_rel",
        "threshold.bar_scrub.quarantine_rules",
        "infra.bar_scrub.symbol_batch",
    ]
    for block in (
        sql.split("INSERT INTO config_schema")[1],
        sql.split("INSERT INTO config_state")[1].split("INSERT INTO config_history")[0],
        sql.split("INSERT INTO config_history")[1],
    ):
        for key in keys:
            assert key in block, f"{key} missing from an APR block"


def test_quarantine_rules_exclude_informational_rules() -> None:
    sql = read_source()
    seed = re.search(r"quarantine_rules', '(\[[^\n]*\])'", sql)
    assert seed is not None
    for informational in ("vol_scaled_jump", "stale_print", "volume_outlier"):
        assert informational not in seed.group(1)


def test_no_decompression() -> None:
    assert "decompress_chunk" not in read_source()
