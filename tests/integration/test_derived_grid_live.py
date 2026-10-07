"""Integration: the derived 15m/1h grid on live data (phase 185 plan 12, D-15).

Read-only against the live indicagent DB (skips when unreachable). The plan's
D-15 identity checks after the rewrite:

- no (symbol, session) has 1h rows at two different minutes (the old :00 grid
  and IBKR's :30 grid must never be visible together), scoped to derived
  symbols until todo 449's 5m backfill lets the rewrite reach the rest;
- every derived symbol's 1h rows carry source derived_5m and anchor on the
  session open (minute 30 on a 9:30 open; mcal also encodes real late opens,
  e.g. 9:32 on 2006-12-27, Ford's moment of silence);
- for sampled symbols and sessions, the derived 1h and 15m bars equal a direct
  SQL aggregation of the tradeable 5m (the direct-oracle convention; a thin
  session may aggregate fewer than the full 3/12 constituents - missing is
  missing, the no_fill invariant - and unanswered holes are the
  partial_constituents flag's to mark, not this check's);
- the first derived 1h open of every session equals the session's first
  non-quarantined 5m open, exactly (an internal identity of the grid; it holds
  for every name, whichever source its canonical 1d comes from);
- the derived 1h volume, close and first open agree with IBKR's own SMART
  TRADES 1d observation in D1 (the latest per symbol and date), never with
  canonical 1d: canonical 1d is Tradier for most names and its consolidated
  volume is a different basis (data layer integrity design section 7, volume
  definitions). Agreement is a rate, not an identity: closing-auction prints,
  odd lots, half days and vendor adjustment runs move single sessions. Measured
  2026-10-07 over 1,041,534 sessions on 239 names (plan 185-31): volume within
  1% on 99.30%, 1h volume above 1d by more than 1% on 0.007% (the 5m sum cannot
  structurally exceed the day), close within 1% on 99.78%, first open exact on
  99.86%, largest per-name median volume deficit 0.17%. The thresholds below sit
  under those rates; the worst names (VIXY volume 66%, GE open 88% through its
  2021-2024 corporate actions) are vendor-basis findings for 185-37 and D7, and
  pass only as part of the aggregate;
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

from src.intelligence.bars.sessions import nyse_sessions

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
    # Derived symbols only: the not-yet-derived majority still carries the old
    # stored :00/:30 mix until todo 449's 5m backfill reaches them.
    cur.execute("""
        SELECT count(*) FROM (
            SELECT symbol, date_trunc('day', "timestamp") AS d
            FROM market_data_ohlcv
            WHERE timeframe = '1h' AND volume > 0
              AND symbol IN (SELECT DISTINCT symbol FROM market_data_ohlcv
                             WHERE timeframe = '1h' AND source = 'derived_5m')
            GROUP BY 1, 2
            HAVING count(DISTINCT extract(minute FROM "timestamp")) > 1
        ) x
        """)
    assert cur.fetchone()[0] == 0


def test_derived_symbols_1h_rows_are_derived_and_session_anchored(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT count(*) FROM market_data_ohlcv
        WHERE timeframe = '1h'
          AND symbol IN (SELECT DISTINCT symbol FROM market_data_ohlcv
                         WHERE timeframe = '1h' AND source = 'derived_5m')
          AND source <> 'derived_5m'
        """)
    assert cur.fetchone()[0] == 0
    # Session-anchored, not hard :30: each 1h bar sits an integral number of
    # hours after its session's open (minute-of-hour equals the open's).
    cur.execute("""
        SELECT DISTINCT date_trunc('day', "timestamp")::date AS d,
                        extract(minute FROM "timestamp")::int AS minute
        FROM market_data_ohlcv
        WHERE timeframe = '1h' AND source = 'derived_5m'
        """)
    rows = {tuple(r) for r in cur.fetchall()}
    sessions = nyse_sessions(min(r[0] for r in rows), max(r[0] for r in rows))
    for day, minute in rows:
        assert day in sessions, f"derived 1h bar on non-session date {day}"
        assert minute == sessions[day][0].minute, (
            f"{day}: derived 1h anchored :{minute:02d}, session open "
            f"{sessions[day][0].isoformat()}"
        )


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
                               (array_agg(open ORDER BY "timestamp"))[1] AS open,
                               max(high) AS high, min(low) AS low,
                               (array_agg(close ORDER BY "timestamp" DESC))[1] AS close,
                               sum(volume) AS volume,
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
                       OR der.volume <> agg.volume OR agg.n * 5 > {minutes}
                    """,
                    (session, symbol, session, session, symbol, tf, session, session),
                )
                assert cur.fetchone()[0] == 0, f"{symbol}/{tf} on {session.date()}"
                checked += 1
    assert checked > 0


# Thresholds committed with plan 185-31 from the 2026-10-07 measurement in the module docstring.
_MIN_VOLUME_WITHIN_1PCT = 0.99
_MAX_VOLUME_EXCESS_OVER_1PCT = 0.001
_MIN_CLOSE_WITHIN_1PCT = 0.995
_MIN_OPEN_EXACT = 0.995
_MAX_ABS_MEDIAN_VOLUME_DEFICIT = 0.005


def test_first_1h_open_equals_the_first_5m_open_of_every_session(conn):
    cur = conn.cursor()
    symbols = _derived_symbols(cur)
    if not symbols:
        pytest.skip("no derived 1h symbols yet (rewrite has not run)")
    sampled = random.Random(18512).sample(symbols, min(5, len(symbols)))
    cur.execute(
        """
        WITH h AS (
            SELECT symbol, ("timestamp" AT TIME ZONE 'America/New_York')::date AS d,
                   min("timestamp") AS t0, (array_agg(open ORDER BY "timestamp"))[1] AS o1
            FROM market_data_ohlcv
            WHERE symbol = ANY(%s) AND timeframe = '1h' AND source = 'derived_5m'
            GROUP BY 1, 2
        ), f AS (
            SELECT DISTINCT ON (t.symbol, h.d) t.symbol, h.d, t.open
            FROM market_data_ohlcv_tradeable t
            JOIN h ON h.symbol = t.symbol
                  AND h.d = (t."timestamp" AT TIME ZONE 'America/New_York')::date
                  AND t."timestamp" >= h.t0
            WHERE t.symbol = ANY(%s) AND t.timeframe = '5m'
              AND NOT EXISTS (
                  SELECT 1 FROM bar_quality_flag q
                  WHERE q.symbol = t.symbol AND q.timeframe = '5m'
                    AND q."timestamp" = t."timestamp" AND q.quarantine)
            ORDER BY t.symbol, h.d, t."timestamp"
        )
        SELECT count(*), count(*) FILTER (WHERE f.open IS DISTINCT FROM h.o1)
        FROM h LEFT JOIN f USING (symbol, d)
        """,
        (sampled, sampled),
    )
    n_sessions, n_mismatched = cur.fetchone()
    assert n_sessions > 0
    assert n_mismatched == 0, f"{n_mismatched} of {n_sessions} sessions on {sampled}"


def test_1h_volume_close_and_open_agree_with_ibkr_smart_1d_observations(conn):
    cur = conn.cursor()
    if not _derived_symbols(cur):
        pytest.skip("no derived 1h symbols yet (rewrite has not run)")
    cur.execute(
        """
        WITH derived AS (
            SELECT DISTINCT symbol FROM market_data_ohlcv
            WHERE timeframe = '1h' AND source = 'derived_5m'
        ), obs AS (
            SELECT DISTINCT ON (o.symbol, o.bar_date)
                   o.symbol, o.bar_date, o.open, o.close, o.volume
            FROM ohlcv_observation o
            JOIN ohlcv_request q ON q.request_id = o.request_id
            WHERE o.timeframe = '1d' AND o.route = 'SMART' AND o.what_to_show = 'TRADES'
              AND q.source = 'ibkr' AND q.caller NOT LIKE 'test-%%'
              AND o.symbol IN (SELECT symbol FROM derived)
            ORDER BY o.symbol, o.bar_date, o.fetched_at DESC, o.request_id DESC
        ), h AS (
            SELECT symbol, ("timestamp" AT TIME ZONE 'America/New_York')::date AS d,
                   sum(volume) AS vol,
                   (array_agg(open ORDER BY "timestamp"))[1] AS o1,
                   (array_agg(close ORDER BY "timestamp" DESC))[1] AS c1
            FROM market_data_ohlcv
            WHERE timeframe = '1h' AND source = 'derived_5m'
            GROUP BY 1, 2
        ), j AS (
            SELECT h.symbol, h.vol, obs.volume, h.o1, obs.open, h.c1, obs.close
            FROM h JOIN obs ON obs.symbol = h.symbol AND obs.bar_date = h.d
            WHERE obs.volume > 0
        ), per AS (
            SELECT symbol,
                   percentile_cont(0.5) WITHIN GROUP (
                       ORDER BY (volume - vol)::float8 / volume) AS median_deficit
            FROM j GROUP BY 1
        )
        SELECT count(*),
               avg((abs(vol - volume) <= 0.01 * volume)::int),
               avg((vol > 1.01 * volume)::int),
               avg((abs(c1 - close) <= 0.01 * close)::int),
               avg((o1 = open)::int),
               (SELECT max(abs(median_deficit)) FROM per),
               (SELECT array_agg(symbol ORDER BY symbol) FROM per
                WHERE abs(median_deficit) > %s)
        FROM j
        """,
        (_MAX_ABS_MEDIAN_VOLUME_DEFICIT,),
    )
    n, vol_within, vol_excess, close_within, open_exact, worst_median, off_names = cur.fetchone()
    assert n > 0, "no derived session has an IBKR SMART TRADES 1d observation"
    assert float(vol_within) >= _MIN_VOLUME_WITHIN_1PCT, f"volume within 1%: {vol_within} of {n}"
    assert float(vol_excess) <= _MAX_VOLUME_EXCESS_OVER_1PCT, f"1h above 1d: {vol_excess}"
    assert float(close_within) >= _MIN_CLOSE_WITHIN_1PCT, f"close within 1%: {close_within}"
    assert float(open_exact) >= _MIN_OPEN_EXACT, f"first open exact: {open_exact}"
    assert (
        not off_names
    ), f"median 1h volume deficit beyond {_MAX_ABS_MEDIAN_VOLUME_DEFICIT}: {off_names} (worst {worst_median})"


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
    assert n_symbols > 0
    # The archive holds observations only: no placeholder ever leaks in.
    cur.execute("""
        SELECT count(*) FROM ohlcv_intraday_raw_archive
        WHERE timeframe IN ('15m', '1h') AND source = 'synthetic_fill'
        """)
    assert cur.fetchone()[0] == 0, "synthetic_fill rows in the raw archive"
    # The latest completed grid batch recorded the removal total it verified;
    # rows it newly tagged with its batch_id are a subset of that total (earlier
    # batches' rows keep their own tag under ON CONFLICT DO NOTHING).
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
    cur.execute("""
        SELECT count(*) FROM ohlcv_intraday_raw_archive a
        JOIN bar_derivation_batch b ON b.batch_id = a.batch_id
        WHERE b.started_at = (SELECT max(started_at) FROM bar_derivation_batch
                              WHERE stage = 'grid' AND status = 'completed')
        """)
    tagged = cur.fetchone()[0]
    assert tagged <= recorded, f"batch tagged {tagged} archive rows but recorded {recorded}"


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
