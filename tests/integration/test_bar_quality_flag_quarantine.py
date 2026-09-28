"""Integration: migration 381's quarantine state against the live indicagent DB.

Runs against the production database (not indicagent_test) because the point is
the live legacy copy and the live tradeable-view anti-join; the rebuilt test DB
has no market data, so every data assertion would trivially pass empty there.
Strictly read-only: SELECTs only, no rows are written or modified.

Note for the conftest replay: 381 is numbered above the 2026-09-27 baseline
cutoff (380), so it replays onto indicagent_test too. Its legacy-copy INSERT
selects from an empty hypertable there (0 rows, harmless) and every other
statement is DDL or ON CONFLICT DO NOTHING.
"""

from __future__ import annotations

import psycopg
import pytest

_LIVE_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent"

pytestmark = pytest.mark.integration


def _query(sql: str) -> list[tuple]:
    with psycopg.connect(_LIVE_DB_URL) as conn:
        conn.execute("SET default_transaction_read_only = on")
        return list(conn.execute(sql).fetchall())


def test_legacy_copy_matches_source_statuses() -> None:
    copied, source, quarantined = _query(
        "SELECT (SELECT count(*) FROM bar_quality_flag"
        "  WHERE rule = 'legacy_price_sanity_status'),"
        " (SELECT count(*) FROM market_data_ohlcv WHERE price_sanity_status IS NOT NULL),"
        " (SELECT count(*) FROM bar_quality_flag"
        "  WHERE rule = 'legacy_price_sanity_status' AND quarantine)"
    )[0]
    assert copied == source, "legacy copy must cover every non-null status"
    assert quarantined > 0, "confirmed_corrupt statuses must quarantine"


def test_quarantined_bars_absent_from_tradeable_view() -> None:
    keys = _query(
        'SELECT symbol, timeframe, "timestamp" FROM bar_quality_flag'
        " WHERE quarantine ORDER BY flagged_at LIMIT 3"
    )
    assert keys, "expected at least one quarantined bar"
    with psycopg.connect(_LIVE_DB_URL) as conn:
        conn.execute("SET default_transaction_read_only = on")
        for symbol, timeframe, ts in keys:
            in_raw = conn.execute(
                "SELECT count(*) FROM market_data_ohlcv WHERE symbol = %s"
                ' AND timeframe = %s AND "timestamp" = %s',
                (symbol, timeframe, ts),
            ).fetchone()[0]
            in_view = conn.execute(
                "SELECT count(*) FROM market_data_ohlcv_tradeable WHERE symbol = %s"
                ' AND timeframe = %s AND "timestamp" = %s',
                (symbol, timeframe, ts),
            ).fetchone()[0]
            assert in_raw > 0, f"flagged bar {symbol}/{timeframe}/{ts} missing from raw"
            assert in_view == 0, f"quarantined bar {symbol}/{timeframe}/{ts} visible in view"


def test_unquarantined_legacy_bars_still_visible() -> None:
    n = _query(
        "SELECT count(*) FROM market_data_ohlcv_tradeable t"
        " JOIN bar_quality_flag q ON q.symbol = t.symbol AND q.timeframe = t.timeframe"
        ' AND q."timestamp" = t."timestamp"'
        " WHERE NOT q.quarantine AND q.rule = 'legacy_price_sanity_status'"
    )[0][0]
    assert n > 0, "non-quarantined flagged bars must stay in the view"


def test_dropped_index_gone() -> None:
    n = _query(
        "SELECT count(*) FROM pg_indexes"
        " WHERE indexname = 'idx_market_data_ohlcv_price_sanity_unaudited'"
    )[0][0]
    assert n == 0


def test_tradeable_view_column_contract() -> None:
    rows = _query(
        "SELECT column_name FROM information_schema.columns"
        " WHERE table_name = 'market_data_ohlcv_tradeable'"
        " ORDER BY ordinal_position"
    )
    assert [r[0] for r in rows] == [
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
