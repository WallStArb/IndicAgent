"""Migration 537 contract: canonical_bar_lineage resolves alpaca sip_rth 1d bars (todo 545).

Alpaca 1d raw rows carry a request_id with no ohlcv_request row; their provenance is the
ohlcv_load row named by load_id, and Alpaca stamps 1d at the New York session open. Reads the .sql
text only (no DB), SQL line comments stripped.
"""

from __future__ import annotations

import re

from tests.unit._source_grep_helpers import read_source

_RAW = read_source("production", "migrations", "537_canonical_bar_lineage_alpaca_sip_rth.sql")
_CODE = re.sub(r"--[^\n]*", "", _RAW)
_FLAT = re.sub(r"\s+", " ", _CODE)
_VIEW = _FLAT.split("CREATE OR REPLACE VIEW canonical_bar_lineage AS")[1].split("; COMMENT")[0]


def test_runs_in_one_transaction_and_regrants():
    assert _CODE.strip().startswith("BEGIN;")
    assert _CODE.rstrip().endswith("COMMIT;")
    assert "GRANT SELECT ON canonical_bar_lineage TO bar_derivation_writer;" in _FLAT


def test_view_keeps_the_column_names_in_order():
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


def test_alpaca_traces_through_the_load_not_the_request():
    alpaca = _VIEW.split("UNION ALL")[1].split(") o ON")[0]
    assert "JOIN ohlcv_load l ON l.load_id = r.load_id" in alpaca
    assert "ohlcv_request" not in alpaca
    assert "r.vendor = 'alpaca' AND r.kind = 'sip_rth'" in alpaca
    assert "l.caller NOT LIKE 'test-%'" in alpaca


def test_alpaca_session_date_is_the_new_york_date_at_midnight_utc():
    assert (
        "((r.\"timestamp\" AT TIME ZONE 'America/New_York')::date)::timestamp AT TIME ZONE 'UTC'"
        in _VIEW
    )
    assert 'o.session_ts = m."timestamp"' in _VIEW


def test_tradier_and_ibkr_keep_the_request_route():
    legacy = _VIEW.split("UNION ALL")[0]
    assert "JOIN ohlcv_request q ON q.request_id = r.request_id" in legacy
    assert "q.caller NOT LIKE 'test-%'" in legacy
    assert "WHEN m.vendor = 'alpaca' AND m.kind = 'sip_rth'" in _VIEW


def test_values_must_match_exactly():
    for column in ("open", "high", "low", "close", "volume"):
        assert f"o.{column} IS NOT DISTINCT FROM m.{column}" in _VIEW
