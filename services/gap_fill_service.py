#!/usr/bin/env python3
"""
Gap-Fill Service — Self-healing infrastructure for missing 1m RTH bars.

Detects missing 1-minute bars during Regular Trading Hours (09:30-16:00 ET)
for all active symbols, fetches only missing windows from IBKR, and inserts
with ON CONFLICT DO NOTHING for idempotency.

Runs daily at 09:20 ET via systemd timer.
Metrics port: 9119

Usage:
    .venv/bin/python services/gap_fill_service.py [--lookback-days 5] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from zoneinfo import ZoneInfo

import asyncpg
from prometheus_client import Counter, start_http_server

from src.config.settings import Settings, get_active_contracts
from src.core.service_utils import setup_service_logging
from src.providers.ibkr import IBKRProvider

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ET = ZoneInfo("America/New_York")
RTH_OPEN_HOUR, RTH_OPEN_MIN = 9, 30
RTH_CLOSE_HOUR, RTH_CLOSE_MIN = 16, 0
METRICS_PORT = 9119
CRITICAL_GAP_THRESHOLD = 30

# ---------------------------------------------------------------------------
# Prometheus metrics (module-level)
# ---------------------------------------------------------------------------

GAP_FILL_GAPS_DETECTED = Counter(
    "gap_fill_gaps_detected_total",
    "Missing 1m RTH bar windows detected",
    ["symbol"],
)
GAP_FILL_BARS_FETCHED = Counter(
    "gap_fill_bars_fetched_total",
    "1m RTH bars successfully fetched",
    ["symbol"],
)
GAP_FILL_FETCH_FAILED = Counter(
    "gap_fill_fetch_failed_total",
    "Fetch attempts that failed",
    ["symbol"],
)


# ---------------------------------------------------------------------------
# Pure functions (testable without I/O)
# ---------------------------------------------------------------------------


def generate_rth_timestamps(date_et: date) -> list[datetime]:
    """Generate expected 1m bar timestamps for one RTH session (390 bars).

    All returned timestamps are UTC (converted from ET).
    Skips weekends (returns empty list for Saturday/Sunday).

    The bar timestamps represent bar-open times:
      - First bar: 09:30 ET (bar from 09:30 to 09:31)
      - Last bar:  15:59 ET (bar from 15:59 to 16:00)
    """
    if date_et.weekday() >= 5:  # Saturday=5, Sunday=6
        return []
    open_et = datetime(
        date_et.year, date_et.month, date_et.day,
        RTH_OPEN_HOUR, RTH_OPEN_MIN,
        tzinfo=ET,
    )
    close_et = datetime(
        date_et.year, date_et.month, date_et.day,
        RTH_CLOSE_HOUR, RTH_CLOSE_MIN,
        tzinfo=ET,
    )
    result: list[datetime] = []
    ts = open_et
    while ts < close_et:
        result.append(ts.astimezone(UTC))
        ts += timedelta(minutes=1)
    return result  # 390 bars per session


def detect_gaps(expected: list[datetime], actual: set[datetime]) -> list[datetime]:
    """Return timestamps present in expected but missing from actual."""
    return sorted([ts for ts in expected if ts not in actual])


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


async def get_actual_timestamps(
    pool: asyncpg.Pool,
    symbol: str,
    start_utc: datetime,
    end_utc: datetime,
) -> set[datetime]:
    """Query market_data_ohlcv for actual 1m bar timestamps in the window."""
    rows = await pool.fetch(
        """SELECT timestamp FROM market_data_ohlcv
           WHERE symbol = $1 AND timeframe = '1m'
           AND timestamp >= $2 AND timestamp < $3""",
        symbol,
        start_utc,
        end_utc,
    )
    return {row["timestamp"] for row in rows}


async def insert_bars(pool: asyncpg.Pool, bars: list[dict[str, Any]]) -> int:
    """Insert fetched bars with ON CONFLICT DO NOTHING. Returns count inserted."""
    if not bars:
        return 0
    # asyncpg executemany requires Python datetime objects for timestamptz columns.
    # Bar timestamps from IBKRProvider are already timezone-aware UTC datetimes.
    await pool.executemany(
        """INSERT INTO market_data_ohlcv
               (symbol, timeframe, timestamp, open, high, low, close, volume, source)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
           ON CONFLICT DO NOTHING""",
        [
            (
                b["symbol"],
                "1m",
                b["timestamp"],
                b["open"],
                b["high"],
                b["low"],
                b["close"],
                b["volume"],
                b.get("source", "ibkr_gap_fill"),
            )
            for b in bars
        ],
    )
    return len(bars)


# ---------------------------------------------------------------------------
# IBKR fetch
# ---------------------------------------------------------------------------


async def fetch_bars_from_ibkr(
    provider: IBKRProvider,
    instrument: Any,
    missing: list[datetime],
    logger: Any,
) -> list[dict[str, Any]]:
    """Fetch 1m bars from IBKR covering the missing timestamps.

    Groups consecutive missing timestamps into contiguous windows to minimise
    IBKR API calls, then fetches each window. Bars are filtered to only the
    requested timestamps so we don't write data outside the gap.

    Returns a list of bar dicts ready for insert_bars().
    """
    if not missing:
        return []

    symbol = instrument.symbol

    # Build contiguous windows from missing timestamps (1m bars, gap tolerance = 2m)
    windows: list[tuple[datetime, datetime]] = []
    window_start = missing[0]
    window_end = missing[0]

    for ts in missing[1:]:
        if (ts - window_end) <= timedelta(minutes=2):
            window_end = ts
        else:
            windows.append((window_start, window_end + timedelta(minutes=1)))
            window_start = ts
            window_end = ts
    windows.append((window_start, window_end + timedelta(minutes=1)))

    missing_set = set(missing)
    result_bars: list[dict[str, Any]] = []

    for start, end in windows:
        try:
            ohlcv_bars = await provider.fetch_historical_bars(
                symbol=symbol,
                timeframe="1m",
                start=start - timedelta(minutes=1),  # slight buffer
                end=end + timedelta(minutes=1),
                continuous=False,
            )
            for bar in ohlcv_bars:
                # Normalise to UTC-aware if needed
                ts = bar.timestamp
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                else:
                    ts = ts.astimezone(UTC)
                if ts in missing_set:
                    result_bars.append(
                        {
                            "symbol": symbol,
                            "timestamp": ts,
                            "open": bar.open,
                            "high": bar.high,
                            "low": bar.low,
                            "close": bar.close,
                            "volume": bar.volume,
                            "source": "ibkr_gap_fill",
                        }
                    )
        except Exception as exc:
            logger.warning(
                "window_fetch_failed",
                symbol=symbol,
                window_start=start.isoformat(),
                window_end=end.isoformat(),
                error=str(exc),
            )

    return result_bars


# ---------------------------------------------------------------------------
# Gap-fill logic per symbol
# ---------------------------------------------------------------------------


async def fill_gaps_for_symbol(
    pool: asyncpg.Pool,
    provider: IBKRProvider,
    instrument: Any,
    lookback_days: int,
    logger: Any,
    dry_run: bool = False,
) -> int:
    """Detect and fill gaps for one symbol over the lookback window.

    Returns total number of missing bar timestamps detected.
    """
    symbol = instrument.symbol
    now_et = datetime.now(ET)
    total_missing = 0

    for day_offset in range(lookback_days):
        check_date = (now_et - timedelta(days=day_offset + 1)).date()
        expected = generate_rth_timestamps(check_date)
        if not expected:
            continue  # Weekend — skip

        # Window: from first expected bar to just past the last one
        window_start = expected[0]
        window_end = expected[-1] + timedelta(minutes=1)

        actual = await get_actual_timestamps(pool, symbol, window_start, window_end)
        missing = detect_gaps(expected, actual)

        if not missing:
            continue

        total_missing += len(missing)
        logger.info(
            "gaps_found",
            symbol=symbol,
            date=str(check_date),
            missing_count=len(missing),
        )

        if not dry_run:
            try:
                bars = await fetch_bars_from_ibkr(provider, instrument, missing, logger)
                inserted = await insert_bars(pool, bars)
                GAP_FILL_BARS_FETCHED.labels(symbol=symbol).inc(inserted)
                logger.info(
                    "bars_fetched",
                    symbol=symbol,
                    date=str(check_date),
                    count=inserted,
                )
            except Exception as exc:
                GAP_FILL_FETCH_FAILED.labels(symbol=symbol).inc(1)
                logger.error(
                    "fetch_failed",
                    symbol=symbol,
                    date=str(check_date),
                    error=str(exc),
                )

    GAP_FILL_GAPS_DETECTED.labels(symbol=symbol).inc(total_missing)

    if total_missing > CRITICAL_GAP_THRESHOLD:
        logger.critical(
            "systemic_gap_detected",
            symbol=symbol,
            gap_count=total_missing,
            msg=(
                f"CRITICAL: {total_missing} missing bars detected for {symbol}"
                " — possible systemic data collection failure"
            ),
        )

    return total_missing


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def run(args: argparse.Namespace) -> None:
    settings = Settings()
    logger = setup_service_logging("gap-fill")

    try:
        start_http_server(METRICS_PORT)
    except Exception as exc:
        logger.warning("metrics_server_failed", port=METRICS_PORT, error=str(exc))

    pool = await asyncpg.create_pool(settings.database_url)

    instruments = get_active_contracts(settings)
    symbols = [i.symbol for i in instruments]

    logger.info(
        "gap_fill_start",
        symbols=len(symbols),
        lookback_days=args.lookback_days,
        dry_run=args.dry_run,
    )

    # Connect IBKR provider (shared connection for all symbols)
    provider = IBKRProvider(
        host=settings.ib_host,
        port=settings.ib_port,
        client_id=settings.ib_client_id,
        settings=settings,
    )
    connected = await provider.connect()
    if not connected:
        logger.error("ibkr_connect_failed", host=settings.ib_host, port=settings.ib_port)
        await pool.close()
        return

    # Qualify all instruments
    for instrument in instruments:
        qualified = await provider.qualify_instrument(instrument)
        if not qualified:
            logger.warning("qualify_failed", symbol=instrument.symbol)

    total_gaps = 0
    for instrument in instruments:
        try:
            gaps = await fill_gaps_for_symbol(
                pool,
                provider,
                instrument,
                args.lookback_days,
                logger,
                args.dry_run,
            )
            total_gaps += gaps
        except Exception as exc:
            logger.error("symbol_gap_fill_failed", symbol=instrument.symbol, error=str(exc))

    logger.info(
        "gap_fill_complete",
        total_gaps=total_gaps,
        symbols_checked=len(symbols),
    )

    await provider.disconnect()
    await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Gap-fill missing 1m RTH bars")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=5,
        help="Days to check (default: 5)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect gaps only, no fetch",
    )
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
