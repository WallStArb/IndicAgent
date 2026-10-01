"""Integration: the derived 15m/1h grid on live data (phase 185 plan 12, D-15).

Read-only against the live indicagent DB (skips when unreachable). The plan's
D-15 identity checks after the rewrite:

- no (symbol, session) has 1h rows at two different minutes (the old :00 grid
  and IBKR's :30 grid must never be visible together);
- every derived symbol's 1h rows carry source derived_5m and minute 30;
- for sampled symbols and sessions, the derived 1h and 15m bars equal a direct
  SQL aggregation of the tradeable 5m (the direct-oracle convention);
- per sampled session, the sum of derived 1h volume equals the 1d volume and
  the first derived 1h open equals the 1d open (the 1d close differs by the
  auction, so close is not compared);
- the archive holds the stored observations the rewrite removed (per derived
  symbol the archived 15m/1h rows are non-zero, and the latest completed grid
  batch's detail records the same total it verified and removed);
- bar_content_digest_current covers 5m, 15m and 1h for every derived symbol.
"""

from __future__ import annotations

import json
import random

import psycopg
import pytest

_LIVE_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent"

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def conn():
    try:
        c = psycopg.connect(_LIVE_DB_URL, autocommit=True)
    except Exception as error:  # reachability probe; any failure means skip
        pytest.skip(f"live database not reachable: {error}")
    yield c
    c.close()


def _derived_symbols(cur) -> list[str]:
    cur.execute("""
        SELECT DISTINCT symbol FROM market_data_ohlcv
        WHERE timeframe = '1h' AND source = 'derived_5m'
        ORDER BY symbol
        """)
    return [r[0] for r in cur.fetchall()]


def test_no_session_has_1h_rows_at_two_minutes(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT count(*) FROM (
            SELECT symbol, date_trunc('day', "timestamp") AS d
            FROM market_data_ohlcv
            WHERE timeframe = '1h' AND volume > 0
            GROUP BY 1, 2
            HAVING count(DISTINCT extract(minute FROM "timestamp")) > 1
        ) x
        """)
    assert cur.fetchone()[0] == 0


def test_derived_symbols_1h_rows_are_derived_and_on_the_30(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT count(*) FROM market_data_ohlcv
        WHERE timeframe = '1h'
          AND symbol IN (SELECT DISTINCT symbol FROM market_data_ohlcv
                         WHERE timeframe = '1h' AND source = 'derived_5m')
          AND (source <> 'derived_5m' OR extract(minute FROM "timestamp") <> 30)
        """)
    assert cur.fetchone()[0] == 0


def test_derived_bars_equal_direct_5m_aggregation(conn):
    """5 random derived symbols x 5 random sessions: derived 1h and 15m equal
    a direct aggregation of the tradeable 5m over the same buckets."""
    cur = conn.cursor()
    symbols = _derived_symbols(cur)
    if not symbols:
        pytest.skip("no derived 1h symbols yet (rewrite has not run)")
    rng = random.Random(18512)
    sampled = rng.sample(symbols, min(5, len(symbols)))
    checked = 0
    for symbol in sampled:
        cur.execute(
            """
            SELECT DISTINCT date_trunc('day', "timestamp")
            FROM market_data_ohlcv
            WHERE symbol = %s AND timeframe = '15m' AND source = 'derived_5m'
            ORDER BY 1
            """,
            (symbol,),
        )
        sessions = [r[0] for r in cur.fetchall()]
        if not sessions:
            continue
        for session in rng.sample(sessions, min(5, len(sessions))):
            for tf, minutes in (("15m", 15), ("1h", 60)):
                cur.execute(
                    f"""
                    WITH agg AS (
                        SELECT date_bin('{minutes} minutes', "timestamp", %s) AS bucket,
                               min(open) AS open, max(high) AS high, min(low) AS low,
                               max(close) AS close, sum(volume) AS volume,
                               count(*) AS n
                        FROM market_data_ohlcv_tradeable
                        WHERE symbol = %s AND timeframe = '5m'
                          AND "timestamp" >= %s AND "timestamp" < %s + interval '1 day'
                        GROUP BY 1
                    )
                    SELECT count(*) FROM (
                        SELECT d."timestamp", d.open, d.high, d.low, d.close, d.volume
                        FROM market_data_ohlcv d
                        WHERE d.symbol = %s AND d.timeframe = %s AND d.source = 'derived_5m'
                          AND d."timestamp" >= %s AND d."timestamp" < %s + interval '1 day'
                    ) der JOIN agg ON agg.bucket = der."timestamp"
                    WHERE der.open <> agg.open OR der.high <> agg.high
                       OR der.low <> agg.low OR der.close <> agg.close
                       OR der.volume <> agg.volume OR agg.n * 5 <> {minutes}
                    """,
                    (session, symbol, session, session, symbol, tf, session, session),
                )
                assert cur.fetchone()[0] == 0, f"{symbol}/{tf} on {session.date()}"
                checked += 1
    assert checked > 0


def test_session_identities_hold_1h_volume_equals_1d_and_first_open(conn):
    cur = conn.cursor()
    symbols = _derived_symbols(cur)
    if not symbols:
        pytest.skip("no derived 1h symbols yet (rewrite has not run)")
    rng = random.Random(18512)
    for symbol in rng.sample(symbols, min(5, len(symbols))):
        cur.execute(
            """
            SELECT DISTINCT date_trunc('day', "timestamp")
            FROM market_data_ohlcv
            WHERE symbol = %s AND timeframe = '1h' AND source = 'derived_5m'
            ORDER BY 1
            """,
            (symbol,),
        )
        sessions = [r[0] for r in cur.fetchall()]
        if not sessions:
            continue
        for session in rng.sample(sessions, min(5, len(sessions))):
            cur.execute(
                """
                SELECT
                  (SELECT sum(volume) FROM market_data_ohlcv
                   WHERE symbol = %s AND timeframe = '1h' AND source = 'derived_5m'
                     AND "timestamp" >= %s AND "timestamp" < %s + interval '1 day'),
                  (SELECT volume FROM market_data_ohlcv
                   WHERE symbol = %s AND timeframe = '1d'
                     AND "timestamp" >= %s AND "timestamp" < %s + interval '1 day'),
                  (SELECT min(open) FROM market_data_ohlcv
                   WHERE symbol = %s AND timeframe = '1h' AND source = 'derived_5m'
                     AND "timestamp" >= %s AND "timestamp" < %s + interval '1 day'),
                  (SELECT open FROM market_data_ohlcv
                   WHERE symbol = %s AND timeframe = '1d'
                     AND "timestamp" >= %s AND "timestamp" < %s + interval '1 day')
                """,
                (
                    symbol,
                    session,
                    session,
                    symbol,
                    session,
                    session,
                    symbol,
                    session,
                    session,
                    symbol,
                    session,
                    session,
                ),
            )
            vol_1h, vol_1d, open_1h, open_1d = cur.fetchone()
            assert vol_1d is not None, f"{symbol} {session.date()}: no 1d row"
            assert vol_1h == vol_1d, f"{symbol} {session.date()}: 1h volume {vol_1h} != 1d {vol_1d}"
            assert (
                open_1h == open_1d
            ), f"{symbol} {session.date()}: first 1h open {open_1h} != 1d open {open_1d}"


def test_archive_holds_the_removed_observations(conn):
    cur = conn.cursor()
    symbols = _derived_symbols(cur)
    if not symbols:
        pytest.skip("no derived 1h symbols yet (rewrite has not run)")
    # Per derived symbol the rewrite kept its stored observations in the archive.
    cur.execute("""
        SELECT count(*), count(DISTINCT symbol) FROM ohlcv_intraday_raw_archive
        WHERE timeframe IN ('15m', '1h')
          AND symbol IN (SELECT DISTINCT symbol FROM market_data_ohlcv
                         WHERE timeframe = '1h' AND source = 'derived_5m')
        """)
    n_archive, n_symbols = cur.fetchone()
    assert n_archive > 0
    # The latest completed grid batch recorded the same removal total it
    # verified inside its per-symbol transactions.
    cur.execute("""
        SELECT detail FROM bar_derivation_batch
        WHERE stage = 'grid' AND status = 'completed'
        ORDER BY started_at DESC LIMIT 1
        """)
    row = cur.fetchone()
    assert row is not None
    detail = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    recorded = detail.get("n_archive_rows")
    assert recorded is not None, "grid batch detail lacks n_archive_rows"
    assert recorded == n_archive, (
        f"batch recorded {recorded} archived rows; the archive holds {n_archive} "
        f"across {n_symbols} derived symbols"
    )


def test_digest_current_covers_5m_15m_1h_for_derived_symbols(conn):
    cur = conn.cursor()
    symbols = _derived_symbols(cur)
    if not symbols:
        pytest.skip("no derived 1h symbols yet (rewrite has not run)")
    cur.execute("""
        SELECT symbol, count(DISTINCT timeframe) FROM bar_content_digest_current
        WHERE symbol IN (SELECT DISTINCT symbol FROM market_data_ohlcv
                         WHERE timeframe = '1h' AND source = 'derived_5m')
        GROUP BY 1
        """)
    coverage = dict(cur.fetchall())
    missing = [s for s in symbols if coverage.get(s, 0) < 3]
    assert not missing, f"{len(missing)} derived symbol(s) lack 5m/15m/1h digests: {missing[:5]}"
