"""Migration 446 contract: bar_source_policy, the d2-v2 fallback keys, the tradeable view (185-36).

Data layer integrity design section 2: one append-only table holds every bar source decision
(the listing_venue pattern, migration 408), seeded with the real state of each timeframe; the
interior fallback basis test reads two new threshold.bar_integrity keys; an admitted IBKR
fallback bar reads NULL volume through market_data_ohlcv_tradeable, the ibkr_venue precedent.
Reads the .sql text only (no DB), SQL line comments stripped.
"""

from __future__ import annotations

import re

from src.intelligence.bars import sources
from tests.unit._source_grep_helpers import read_source

_FILE = "446_bar_source_policy.sql"
_RAW = read_source("production", "migrations", _FILE)
_CODE = re.sub(r"--[^\n]*", "", _RAW)
_FLAT = re.sub(r"\s+", " ", _CODE)


def test_policy_migration_runs_in_one_transaction():
    assert _CODE.strip().startswith("BEGIN;")
    assert _CODE.rstrip().endswith("COMMIT;")


def test_table_columns():
    assert "CREATE TABLE IF NOT EXISTS bar_source_policy" in _FLAT
    for column in (
        "timeframe text NOT NULL",
        "symbol text NULL REFERENCES instruments(symbol) ON DELETE RESTRICT",
        "valid_from date NOT NULL",
        "valid_to date NULL",
        "ingress_mode text NOT NULL",
        "primary_source text NOT NULL",
        "fallback_source text NULL",
        "reason text NOT NULL",
        "evidence jsonb NOT NULL",
        "recorded_at timestamptz NOT NULL DEFAULT now()",
    ):
        assert column in _FLAT, column


def test_value_checks():
    assert "CHECK (timeframe IN ('1d', '5m', '1m', '15m', '1h', '4h'))" in _FLAT
    assert "CHECK (ingress_mode IN ('observed', 'direct', 'derived'))" in _FLAT
    assert "CHECK (primary_source IN ('tradier', 'ibkr', 'derived'))" in _FLAT
    assert "CHECK (fallback_source IS NULL OR fallback_source IN ('tradier', 'ibkr'))" in _FLAT
    assert "CHECK (fallback_source IS DISTINCT FROM primary_source)" in _FLAT
    # A derived timeframe has no vendor source, and only a derived timeframe names 'derived'.
    assert "CHECK ((ingress_mode = 'derived') = (primary_source = 'derived'))" in _FLAT
    assert "CHECK (valid_to IS NULL OR valid_to > valid_from)" in _FLAT


def test_no_two_rows_cover_one_date_of_one_series():
    assert "CREATE EXTENSION IF NOT EXISTS btree_gist" in _FLAT
    assert "EXCLUDE USING gist" in _FLAT
    assert "timeframe WITH =" in _FLAT
    assert "(coalesce(symbol, '')) WITH =" in _FLAT
    assert "daterange(valid_from, valid_to, '[)') WITH &&" in _FLAT


def test_policy_rows_append_only_except_closing_valid_to():
    assert "BEFORE INSERT OR UPDATE OR DELETE ON bar_source_policy" in _FLAT
    assert "BEFORE TRUNCATE ON bar_source_policy" in _FLAT
    assert "OLD.valid_to IS NOT NULL" in _FLAT
    assert "NEW.valid_to IS NULL" in _FLAT
    # Every column but valid_to is compared, so only the close passes.
    trigger = _FLAT.split("CREATE OR REPLACE FUNCTION bar_source_policy_append_only()")[1]
    trigger = trigger.split("END $$;")[0]
    for column in (
        "policy_id",
        "timeframe",
        "symbol",
        "valid_from",
        "ingress_mode",
        "primary_source",
        "fallback_source",
        "reason",
        "evidence",
        "recorded_at",
    ):
        assert f"NEW.{column}" in trigger and f"OLD.{column}" in trigger, column
    assert "append-only" in trigger
    assert "DROP TRIGGER IF EXISTS trg_bar_source_policy_append_only ON bar_source_policy" in _FLAT
    assert "DROP TRIGGER IF EXISTS trg_bar_source_policy_no_truncate ON bar_source_policy" in _FLAT


def test_grants_read_only_to_the_derivation_role():
    assert "GRANT SELECT ON bar_source_policy TO bar_derivation_writer" in _FLAT
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON bar_source_policy FROM PUBLIC" in _FLAT
    # Rows arrive by migration until 185-37's CLI; no role may write them today.
    assert not re.search(r"GRANT [^;]*(INSERT|UPDATE|DELETE)[^;]* ON bar_source_policy", _FLAT)


def _seed_rows() -> dict[str, tuple[str, str, str]]:
    """timeframe -> (ingress_mode, primary_source, fallback_source) from the seed VALUES."""
    rows = re.findall(
        r"\('(1d|5m|1m|15m|1h|4h)', '(observed|direct|derived)', '(\w+)', (NULL|'\w+'), '",
        _FLAT,
    )
    return {tf: (mode, primary, fallback.strip("'")) for tf, mode, primary, fallback in rows}


def test_seed_rows_record_the_real_state():
    assert _seed_rows() == {
        "1d": ("observed", "tradier", "ibkr"),
        "5m": ("direct", "ibkr", "NULL"),
        "1m": ("direct", "ibkr", "NULL"),
        "4h": ("direct", "ibkr", "NULL"),
        "15m": ("derived", "derived", "NULL"),
        "1h": ("derived", "derived", "NULL"),
    }
    # Timeframe defaults: symbol NULL, open from 1990-01-01, idempotent on re-run.
    assert "NULL::text, DATE '1990-01-01'" in _FLAT
    assert "WHERE NOT EXISTS" in _FLAT


def test_seed_reasons_cite_the_spec_and_the_4h_state():
    assert _RAW.count("2026-10-06-data-layer-integrity-design.md") >= 2
    four_h = _FLAT.split("('4h', 'direct'")[1].split("),")[0]
    for phrase in ("kept", "not fetched", "not derived", "2,184"):
        assert phrase in four_h, phrase


def test_header_names_the_single_writer_and_decisions_not_measurements():
    header = _RAW.split("BEGIN;")[0].lower()
    assert "185-37" in header
    assert "decisions" in header and "measurement" in header
    assert "section 2" in header


def test_fallback_apr_keys_are_seeded_with_provenance():
    for key, value_type, value in (
        ("threshold.bar_integrity.fallback_basis_window_sessions", "int", "20"),
        ("threshold.bar_integrity.fallback_basis_tolerance_bp", "float", "10"),
    ):
        assert f"('{key}', '{value_type}', '{value}'" in _FLAT, key
        description = _FLAT.split(f"('{key}', '{value_type}'")[1].split("'),")[0]
        assert "[initial_estimate]" in description
        assert "Not an ML learning target" in description
        assert f"('{key}', '{value}', 1)" in _FLAT
    assert "'migration_446'" in _FLAT


def test_tradeable_view_nulls_fallback_volume_and_keeps_its_columns():
    view = _FLAT.split("CREATE OR REPLACE VIEW market_data_ohlcv_tradeable AS")[1]
    view = view.split(";")[0]
    assert (
        "CASE WHEN source IN ('ibkr_venue', 'ibkr_fallback') THEN NULL ELSE volume END AS volume"
        in view
    )
    columns = 'SELECT "timestamp", symbol, timeframe, open, high, low, close, CASE'
    assert view.strip().startswith(columns)
    assert "END AS volume, source, base, price_sanity_status FROM market_data_ohlcv" in view
    assert "WHERE volume > 0" in view
    assert "price_sanity_status IS DISTINCT FROM 'confirmed_corrupt'" in view
    assert "q.quarantine" in view


def test_sources_export_the_fallback_label():
    assert sources.SOURCE_IBKR_FALLBACK == "ibkr_fallback"
    assert sources.SOURCE_IBKR_FALLBACK in sources.CANONICAL_1D_SOURCES
    assert set(sources.CANONICAL_1D_SOURCES) == {
        "ibkr_named",
        "ibkr_venue",
        "ibkr_fallback",
        "tradier",
    }
