"""Migration 447 contract: canonical_bar_lineage as a view derived on read (plan 185-38 Task 2).

Data layer integrity design section 4: the lineage table is dropped and a view of the same name
returns, per canonical 1d bar, the latest non-test observation of the bar's source route with
equal OHLCV; the tradeable view loses its price_sanity_status predicate (todo 500). Reads the
.sql text only (no DB), SQL line comments stripped.
"""

from __future__ import annotations

import re

from tests.unit._source_grep_helpers import read_source

_RAW = read_source("production", "migrations", "447_canonical_bar_lineage_view.sql")
_CODE = re.sub(r"--[^\n]*", "", _RAW)
_FLAT = re.sub(r"\s+", " ", _CODE)
_VIEW = _FLAT.split("CREATE VIEW canonical_bar_lineage AS")[1].split(";")[0]


def test_migration_447_runs_in_one_transaction():
    assert _CODE.strip().startswith("BEGIN;")
    assert _CODE.rstrip().endswith("COMMIT;")


def test_drops_the_table_before_creating_the_view_and_adds_no_index():
    assert _FLAT.index("DROP TABLE canonical_bar_lineage;") < _FLAT.index(
        "CREATE VIEW canonical_bar_lineage"
    )
    assert "CREATE INDEX" not in _FLAT


def test_view_keeps_the_table_column_names_in_order():
    select = _VIEW.split(" FROM market_data_ohlcv m")[0]
    names = re.findall(r"(?:AS (\w+)|\.(\"?\w+\"?))(?:,|$)", select.strip())
    columns = [a or b.strip('"') for a, b in names]
    assert columns == [
        "symbol",
        "timeframe",
        "timestamp",
        "rule_version",
        "request_ids",
        "batch_id",
        "derived_at",
    ]


def test_view_matches_equal_values_only():
    for column in ("open", "high", "low", "close", "volume"):
        assert f"ob.{column} IS NOT DISTINCT FROM m.{column}" in _VIEW


def test_route_follows_the_bar_source_and_test_callers_never_count():
    assert "WHEN m.source = 'tradier' THEN ARRAY['TRADIER']" in _VIEW
    assert (
        "WHEN m.source IN ('ibkr_named', 'ibkr_fallback') THEN ARRAY['SMART', 'LEGACY_IMPORT']"
        in _VIEW
    )
    assert "ob.what_to_show = 'TRADES'" in _VIEW
    assert "q.caller NOT LIKE 'test-%'" in _VIEW
    # Latest observation first, SMART before the stored corpus's import.
    assert "ORDER BY (ob.route = 'LEGACY_IMPORT'), ob.fetched_at DESC" in _VIEW
    assert "WHERE m.timeframe = '1d'" in _VIEW


def test_rule_version_and_batch_come_from_the_month_digest():
    assert "FROM bar_content_digest c" in _VIEW
    assert 'c.range_start <= m."timestamp" AND m."timestamp" < c.range_end' in _VIEW
    assert "ORDER BY c.range_start DESC, c.computed_at DESC" in _VIEW


def test_grants_select_to_every_role_that_read_the_table():
    assert "GRANT SELECT ON canonical_bar_lineage TO bar_derivation_writer;" in _FLAT
    assert "GRANT INSERT" not in _FLAT and "GRANT UPDATE" not in _FLAT


def test_tradeable_view_drops_the_price_sanity_predicate_and_keeps_its_columns():
    view = _FLAT.split("CREATE OR REPLACE VIEW market_data_ohlcv_tradeable AS")[1].split(";")[0]
    assert view.strip().startswith(
        'SELECT "timestamp", symbol, timeframe, open, high, low, close, CASE'
    )
    assert (
        "CASE WHEN source IN ('ibkr_venue', 'ibkr_fallback') THEN NULL ELSE volume END AS volume"
        in view
    )
    assert "END AS volume, source, base, price_sanity_status FROM market_data_ohlcv" in view
    assert "WHERE volume > 0 AND NOT EXISTS" in view
    assert "q.quarantine" in view
    assert "confirmed_corrupt" not in view


def test_header_names_the_dump_and_the_rollback():
    header = _RAW.split("BEGIN;")[0]
    assert "data/backups/185-38/canonical_bar_lineage_" in header
    assert "pg_restore" in header and "Rollback" in header


# ---------------------------------------------------------------------------
# Migration 491 (plan 191-09 Task 1): the same view over ohlcv_raw. One raw row per
# (bar, vendor, kind) holds the current value and the request that served it, so the lookup is
# the bar's key plus the vendor and kind its source names, with equal OHLCV.
# ---------------------------------------------------------------------------

_RAW_491 = read_source("production", "migrations", "491_canonical_bar_lineage_over_raw.sql")
_CODE_491 = re.sub(r"--[^\n]*", "", _RAW_491)
_FLAT_491 = re.sub(r"\s+", " ", _CODE_491)
_VIEW_491 = _FLAT_491.split("CREATE OR REPLACE VIEW canonical_bar_lineage AS")[1].split(";")[0]


def test_migration_491_runs_in_one_transaction_and_replaces_in_place():
    assert _CODE_491.strip().startswith("BEGIN;")
    assert _CODE_491.rstrip().endswith("COMMIT;")
    assert "DROP " not in _FLAT_491 and "CREATE INDEX" not in _FLAT_491


def test_491_reads_raw_and_never_the_observation_store():
    assert "FROM ohlcv_raw r" in _VIEW_491
    assert "ohlcv_observation" not in _CODE_491


def test_491_keeps_the_column_names_in_order():
    select = _VIEW_491.split(" FROM market_data_ohlcv m")[0]
    names = re.findall(r"(?:AS (\w+)|\.(\"?\w+\"?))(?:,|$)", select.strip())
    assert [a or b.strip('"') for a, b in names] == [
        "symbol",
        "timeframe",
        "timestamp",
        "rule_version",
        "request_ids",
        "batch_id",
        "derived_at",
    ]


def test_491_matches_the_bar_key_vendor_kind_and_equal_values():
    assert "r.timeframe = '1d'" in _VIEW_491
    assert "o.symbol = m.symbol" in _VIEW_491
    assert 'o."timestamp" = m."timestamp"' in _VIEW_491
    assert "WHEN m.source = 'tradier' THEN o.vendor = 'tradier' AND o.kind = 'consolidated'" in (
        _VIEW_491
    )
    assert (
        "WHEN m.source IN ('ibkr_named', 'ibkr_fallback') THEN o.vendor = 'ibkr' "
        "AND o.kind = 'smart_trades'"
    ) in _VIEW_491
    assert "ELSE false" in _VIEW_491
    for column in ("open", "high", "low", "close", "volume"):
        assert f"o.{column} IS NOT DISTINCT FROM m.{column}" in _VIEW_491


def test_491_is_a_set_join_not_a_per_bar_probe_into_compressed_raw():
    raw_part = _VIEW_491.split("FROM ohlcv_raw r")[0].rsplit("LEFT JOIN", 1)[1]
    assert "LATERAL" not in raw_part


def test_491_test_callers_and_unknown_requests_never_count():
    assert "JOIN ohlcv_request q ON q.request_id = r.request_id" in _VIEW_491
    assert "q.caller NOT LIKE 'test-%'" in _VIEW_491


def test_491_keeps_the_month_digest_and_the_grant():
    assert "FROM bar_content_digest c" in _VIEW_491
    assert "ORDER BY c.range_start DESC, c.computed_at DESC" in _VIEW_491
    assert "WHERE m.timeframe = '1d'" in _VIEW_491
    assert "GRANT SELECT ON canonical_bar_lineage TO bar_derivation_writer;" in _FLAT_491
