"""Migration 443 contract: ohlcv_load and ohlcv_revision serve every canonical writer (plan 185-31).

One load table and one revision table for all timeframes (data layer integrity design section 3):
the four ohlcv_load CHECKs widen, the count and destination columns arrive, ohlcv_revision gains
its origin, the grid stage's role can record loads and revisions, and the two
threshold.bar_integrity APR keys are seeded with provenance.
"""

from __future__ import annotations

import re
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / (
    "production/migrations/443_ohlcv_load_revision_all_writers.sql"
)
_SQL = _PATH.read_text()
_CODE = "\n".join(line for line in _SQL.splitlines() if not line.lstrip().startswith("--"))
_FLAT = re.sub(r"\s+", " ", _CODE)


def test_runs_in_one_transaction():
    assert _CODE.lstrip().startswith("BEGIN;")
    assert _CODE.rstrip().endswith("COMMIT;")


def test_the_four_load_checks_are_dropped_and_widened():
    for name in ("source", "timeframe", "outcome", "destination"):
        assert f"DROP CONSTRAINT IF EXISTS ohlcv_load_{name}_check" in _FLAT
    assert "CHECK (source IN ('tradier', 'ibkr', 'derived'))" in _FLAT
    assert "CHECK (timeframe IN ('1d', '5m', '1m', '15m', '1h', '4h'))" in _FLAT
    assert (
        "CHECK (outcome IN ('loaded', 'short_history', 'no_data', 'failed', 'gated', "
        "'applied', 'refused'))" in _FLAT
    )
    assert "CHECK (destination IN ('d1', 'market_data_ohlcv', 'archive'))" in _FLAT


def test_load_gains_batch_counts_and_destination():
    for column in ("batch_id", "n_unchanged", "n_removed", "destination"):
        assert f"ADD COLUMN IF NOT EXISTS {column}" in _FLAT
    # Every load before 185-38 wrote canonical bars.
    assert "destination text NOT NULL DEFAULT 'market_data_ohlcv'" in _FLAT


def test_revision_gains_origin_and_a_nullable_volume():
    assert "ADD COLUMN IF NOT EXISTS origin text NOT NULL DEFAULT 'load'" in _FLAT
    assert "CHECK (origin IN ('load', 'archive_segment'))" in _FLAT
    assert "ALTER COLUMN old_volume DROP NOT NULL" in _FLAT
    assert "ohlcv_intraday_raw_revision" not in _CODE


def test_grid_role_reads_and_inserts_both_tables():
    assert "GRANT SELECT, INSERT ON ohlcv_load, ohlcv_revision TO bar_derivation_writer" in _FLAT


def test_both_apr_keys_are_seeded_with_provenance():
    for key, value_type, value in (
        ("threshold.bar_integrity.max_revision_ratio", "float", "0.02"),
        ("threshold.bar_integrity.revision_ratio_min_stored", "int", "500"),
    ):
        schema = re.search(rf"\('{re.escape(key)}', '{value_type}', '{value}',[^;]*?\)", _FLAT)
        assert schema, key
        assert "[initial_estimate]" in schema.group(0)
        assert "Not an ML learning target." in schema.group(0)
        assert f"('{key}', '{value}', 1)" in _FLAT
    assert "ON CONFLICT (config_key) DO NOTHING" in _FLAT


def test_grid_write_method_records_the_write_contract():
    assert "'write_contract'" in _FLAT
    assert "infra.bar_derivation.grid_write_method" in _FLAT
