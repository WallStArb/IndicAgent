"""Batch SQL utilities for auditor agents.

Pure async functions — no Prometheus, Kafka, or logging.
Callers own all observability concerns.

Two public functions:
  batch_bar_completeness(pool, instruments, lookback_days=3)
      → list[BarCompletenessResult]

  batch_signal_coverage(pool, instruments, coverage_tfs, lookback_days=1)
      → list[SignalCoverageResult]

Both use UNNEST arrays to batch all (instrument × date × tf) combinations into
a single DB round-trip.  The LEFT JOIN + GROUP BY in each query guarantees that
zero-bar sessions still produce result rows (actual=0) — a plain GROUP BY on a
nullable join column would silently drop them.

Threat T-63.6-01-A: all UNNEST arrays are passed as asyncpg parameters ($1, $2…).
No string interpolation is used anywhere in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class BarCompletenessResult:
    """Single (symbol, tf, session) bar completeness measurement."""

    symbol: str
    tf: str
    session_start: datetime
    session_end: datetime
    expected: int  # derived from session math in Python
    actual: int


@dataclass
class SignalCoverageResult:
    """Single (symbol, tf, session) signal coverage measurement."""

    symbol: str
    tf: str
    session_start: datetime
    session_end: datetime
    signal_count: int
    p50_lag_ms: float | None
    p95_lag_ms: float | None


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

_BAR_COMPLETENESS_SQL = """
SELECT
    ref.symbol,
    ref.tf,
    ref.session_start,
    ref.session_end,
    ref.expected,
    COUNT(m.timestamp) AS actual
FROM UNNEST($1::text[], $2::text[], $3::timestamptz[], $4::timestamptz[], $5::int[])
    AS ref(symbol, tf, session_start, session_end, expected)
LEFT JOIN market_data_ohlcv m
    ON  m.symbol    = ref.symbol
    AND m.timeframe = ref.tf
    AND m.timestamp >= ref.session_start
    AND m.timestamp <  ref.session_end
GROUP BY ref.symbol, ref.tf, ref.session_start, ref.session_end, ref.expected
"""

_SIGNAL_COVERAGE_SQL = """
SELECT
    ref.symbol,
    ref.tf,
    ref.session_start,
    ref.session_end,
    COUNT(s.feature_ts)                                                    AS signal_count,
    percentile_cont(0.50) WITHIN GROUP (ORDER BY s.pipeline_lag_ms)       AS p50,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY s.pipeline_lag_ms)       AS p95
FROM UNNEST($1::text[], $2::text[], $3::timestamptz[], $4::timestamptz[])
    AS ref(symbol, tf, session_start, session_end)
LEFT JOIN signal_ledger s
    ON  s.symbol     = ref.symbol
    AND s.timeframe  = ref.tf
    AND s.feature_ts >= ref.session_start
    AND s.feature_ts <  ref.session_end
    AND s.pipeline_lag_ms IS NOT NULL
GROUP BY ref.symbol, ref.tf, ref.session_start, ref.session_end
"""


# ---------------------------------------------------------------------------
# HTF timeframe minutes (mirrors bar_auditor_agent._HTF_TIMEFRAME_MINUTES)
# "1d" excluded — daily bar completeness has different semantics.
# ---------------------------------------------------------------------------

# Import lazily to avoid circular-import risk; constants are identical to bar_accumulator.
_HTF_TIMEFRAME_MINUTES: dict[str, int] = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


async def batch_bar_completeness(
    pool,
    instruments: list,
    lookback_days: int = 3,
) -> list[BarCompletenessResult]:
    """Detect bar completeness for all (instrument × date × tf) combinations.

    Replaces the nested for-loop in BarAuditorAgent._detect_gaps that issued
    one DB round-trip per (instrument, date) pair — 354 round-trips → 1.

    Session window math (TradingSession boundaries) is computed in Python so
    that non-trading days are excluded before the query is even issued.

    Args:
        pool:          asyncpg connection pool
        instruments:   list of Instrument objects (must have .symbol, .trading_session)
        lookback_days: number of past calendar days to check (default 3)

    Returns:
        List of BarCompletenessResult — one entry per (symbol, tf, session).
        Sessions with zero bars have actual=0 (guaranteed by LEFT JOIN).
    """
    today = date.today()

    # Build UNNEST arrays
    symbols: list[str] = []
    tfs: list[str] = []
    session_starts: list[datetime] = []
    session_ends: list[datetime] = []
    expecteds: list[int] = []

    for instrument in instruments:
        session = instrument.trading_session
        for days_back in range(1, lookback_days + 1):
            target_date = today - timedelta(days=days_back)
            window = session.session_window_for_date(target_date)
            if window[0] is None or window[1] is None:
                continue  # non-trading day — skip

            session_start, session_end = window
            total_minutes = int((session_end - session_start).total_seconds() / 60)
            expected_1m = max(0, total_minutes - session._break_minutes())
            if expected_1m == 0:
                continue

            # 1m row
            symbols.append(instrument.symbol)
            tfs.append("1m")
            session_starts.append(session_start)
            session_ends.append(session_end)
            expecteds.append(expected_1m)

            # HTF rows
            for tf_name, tf_minutes in _HTF_TIMEFRAME_MINUTES.items():
                expected_htf = expected_1m // tf_minutes
                if expected_htf == 0:
                    continue
                symbols.append(instrument.symbol)
                tfs.append(tf_name)
                session_starts.append(session_start)
                session_ends.append(session_end)
                expecteds.append(expected_htf)

    if not symbols:
        return []

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            _BAR_COMPLETENESS_SQL,
            symbols,
            tfs,
            session_starts,
            session_ends,
            expecteds,
        )

    return [
        BarCompletenessResult(
            symbol=row["symbol"],
            tf=row["tf"],
            session_start=row["session_start"],
            session_end=row["session_end"],
            expected=row["expected"],
            actual=int(row["actual"]),
        )
        for row in rows
    ]


async def batch_signal_coverage(
    pool,
    instruments: list,
    coverage_tfs: list[str],
    lookback_days: int = 1,
) -> list[SignalCoverageResult]:
    """Measure signal coverage + pipeline lag for all (instrument × tf) pairs.

    Replaces two sequential loops in SignalAuditorAgent._check_coverage and
    _check_pipeline_lag — 472 round-trips → 1.

    Uses yesterday's session window by default (lookback_days=1).

    Args:
        pool:          asyncpg connection pool
        instruments:   list of Instrument objects
        coverage_tfs:  list of timeframe strings to check (e.g. ["1m", "5m"])
        lookback_days: number of past calendar days to check (default 1)

    Returns:
        List of SignalCoverageResult — one entry per (symbol, tf, session).
        Zero-signal sessions have signal_count=0 and p50/p95 = None.
    """
    today = date.today()

    symbols: list[str] = []
    tfs: list[str] = []
    session_starts: list[datetime] = []
    session_ends: list[datetime] = []

    for instrument in instruments:
        session = instrument.trading_session
        for days_back in range(1, lookback_days + 1):
            target_date = today - timedelta(days=days_back)
            window = session.session_window_for_date(target_date)
            if window[0] is None or window[1] is None:
                continue  # non-trading day — skip

            session_start, session_end = window

            for tf in coverage_tfs:
                symbols.append(instrument.symbol)
                tfs.append(tf)
                session_starts.append(session_start)
                session_ends.append(session_end)

    if not symbols:
        return []

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            _SIGNAL_COVERAGE_SQL,
            symbols,
            tfs,
            session_starts,
            session_ends,
        )

    return [
        SignalCoverageResult(
            symbol=row["symbol"],
            tf=row["tf"],
            session_start=row["session_start"],
            session_end=row["session_end"],
            signal_count=int(row["signal_count"]),
            p50_lag_ms=float(row["p50"]) if row["p50"] is not None else None,
            p95_lag_ms=float(row["p95"]) if row["p95"] is not None else None,
        )
        for row in rows
    ]
