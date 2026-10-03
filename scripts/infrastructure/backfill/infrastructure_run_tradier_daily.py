#!/usr/bin/env python3
"""infrastructure_run_tradier_daily.py - load daily history from Tradier into market_data_ohlcv.

Tradier is the primary 1d source (owner decision 2026-10-03, migration 438). One request returns a
name's whole history. A name keeps one daily source for its whole history: the load refuses a short
history (PEP, 2026-10-03), a history that starts after existing bars, and a reload that changes more
than infra.tradier.max_changed_bar_ratio of existing bars unless --rebase says the source change is
deliberate. Every attempt writes one ohlcv_load row; a changed canonical bar's old values go to
ohlcv_revision. Fetches run concurrently; writes are serial on one connection.

Every answer lands in D1 first (ohlcv_request/ohlcv_observation, source tradier, route TRADIER, raw
including null volume), beside IBKR's observations, so the two vendors compare by (symbol, date, source).
The canonical write is planned from the fetched bars.

--raw-only lands D1 and stops: no canonical write and no ohlcv_load row, so D2 does not treat the
name as Tradier-owned. Used to backfill raw Tradier for comparison against IBKR.

Usage:
  python scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py            # names with no 1d bars
  python scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py --symbols AAPL,SPY [--rebase]
Exit codes: 0 every name loaded; 1 some names refused or failed (recorded in ohlcv_load).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import numpy as np
import structlog

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from services._batch_utils import load_apr_dict_async
from services.ohlcv_observation_writer import AsyncObservationSink, new_fetch_run_id
from src.config.settings import get_settings
from src.core.service_utils import setup_service_logging
from src.providers.base import RequestRecord
from src.providers.tradier import SOURCE, DailyBar, TradierError, fetch_daily_history, make_client

logger = structlog.get_logger(__name__)

_CALLER = "tradier-daily-loader"
_VALUE_TOLERANCE = 1e-9

# (open, high, low, close, volume, source) of one stored bar
StoredBar = tuple[float, float, float, float, int, str]


@dataclass(frozen=True)
class LoadParams:
    min_session_ratio: float
    first_date_tolerance_days: int
    max_changed_bar_ratio: float
    rebase: bool


@dataclass
class LoadPlan:
    outcome: str  # loaded | short_history | no_data | gated
    detail: str | None
    bars: list[DailyBar] = field(default_factory=list)
    revisions: list[tuple[datetime, StoredBar]] = field(default_factory=list)
    n_new: int = 0
    n_changed: int = 0


def _differs(bar: DailyBar, stored: StoredBar) -> bool:
    o, h, lo, c, v, _ = stored
    return (
        any(
            abs(a - b) > _VALUE_TOLERANCE * max(1.0, abs(b))
            for a, b in ((bar.open, o), (bar.high, h), (bar.low, lo), (bar.close, c))
        )
        or bar.volume != v
    )


def plan_symbol_load(
    fetched: list[DailyBar], existing: dict[datetime, StoredBar], params: LoadParams
) -> LoadPlan:
    """Decide one name's load from its Tradier bars and its stored non-placeholder 1d bars."""
    if not fetched:
        return LoadPlan("no_data", "Tradier returned no bars")
    # volume is NOT NULL in market_data_ohlcv and a missing value is never filled: drop the bar.
    bars = [bar for bar in fetched if bar.volume is not None]
    n_dropped = len(fetched) - len(bars)
    if not bars:
        return LoadPlan("no_data", f"all {len(fetched)} bars had null volume")
    first, last = bars[0].timestamp.date(), bars[-1].timestamp.date()
    weekdays = int(np.busday_count(first, last + timedelta(days=1)))
    ratio = len(bars) / weekdays
    if ratio < params.min_session_ratio:
        return LoadPlan(
            "short_history",
            f"{len(bars)} bars over {weekdays} weekdays ({ratio:.3f} < {params.min_session_ratio})",
        )
    if existing:
        earliest = min(existing).date()
        if first > earliest + timedelta(days=params.first_date_tolerance_days):
            return LoadPlan(
                "short_history",
                f"Tradier starts {first}, existing bars start {earliest} "
                f"(tolerance {params.first_date_tolerance_days} d)",
            )
    revisions: list[tuple[datetime, StoredBar]] = []
    n_new = n_overlap = 0
    for bar in bars:
        stored = existing.get(bar.timestamp)
        if stored is None:
            n_new += 1
            continue
        n_overlap += 1
        if _differs(bar, stored) or stored[5] != SOURCE:
            revisions.append((bar.timestamp, stored))
    changed_ratio = len(revisions) / n_overlap if n_overlap else 0.0
    detail = f"{n_dropped} null-volume bars dropped" if n_dropped else None
    if changed_ratio > params.max_changed_bar_ratio and not params.rebase:
        return LoadPlan(
            "gated",
            f"{len(revisions)} of {n_overlap} existing bars change ({changed_ratio:.3f} > "
            f"{params.max_changed_bar_ratio}); pass --rebase for a deliberate source change",
        )
    return LoadPlan("loaded", detail, bars, revisions, n_new, len(revisions))


_SELECT_EXISTING_SQL = """
SELECT "timestamp", open, high, low, close, volume, source
FROM market_data_ohlcv
WHERE symbol = $1 AND timeframe = '1d' AND source <> 'synthetic_fill'
"""

_SELECT_MISSING_SQL = """
SELECT i.symbol FROM instruments i
WHERE i.is_active AND i.contract_details->>'asset_class' = 'equity'
  AND NOT EXISTS (SELECT 1 FROM market_data_ohlcv m
                  WHERE m.symbol = i.symbol AND m.timeframe = '1d' AND m.source <> 'synthetic_fill')
  AND NOT EXISTS (SELECT 1 FROM ohlcv_load l WHERE l.symbol = i.symbol AND l.outcome = 'loaded')
ORDER BY i.symbol
"""

_SELECT_NO_RAW_SQL = """
SELECT i.symbol FROM instruments i
WHERE i.is_active AND i.contract_details->>'asset_class' = 'equity'
  AND NOT EXISTS (SELECT 1 FROM ohlcv_request r
                  WHERE r.symbol = i.symbol AND r.source = 'tradier' AND r.outcome = 'bars')
ORDER BY i.symbol
"""

_INSERT_LOAD_SQL = """
INSERT INTO ohlcv_load (load_id, symbol, timeframe, source, requested_start, requested_end, outcome,
                        n_bars, n_new, n_changed, first_bar, last_bar, detail, caller)
VALUES ($1, $2, '1d', $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
"""

_INSERT_REVISION_SQL = """
INSERT INTO ohlcv_revision (load_id, symbol, timeframe, "timestamp", old_open, old_high, old_low,
                            old_close, old_volume, old_source)
VALUES ($1, $2, '1d', $3, $4, $5, $6, $7, $8, $9)
"""

# A placeholder (synthetic_fill) on the key is replaced by the real bar, as in D2's upsert.
_UPSERT_SQL = """
INSERT INTO market_data_ohlcv ("timestamp", symbol, timeframe, open, high, low, close, volume, source)
VALUES ($1, $2, '1d', $3, $4, $5, $6, $7, $8)
ON CONFLICT ("timestamp", symbol, timeframe) DO UPDATE SET
    open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low, close = EXCLUDED.close,
    volume = EXCLUDED.volume, source = EXCLUDED.source
"""


async def _record_load(
    conn: Any,
    symbol: str,
    start: date,
    end: date,
    plan: LoadPlan,
    n_fetched: int,
    outcome: str | None = None,
    detail: str | None = None,
) -> None:
    load_id = uuid.uuid4()
    outcome = outcome or plan.outcome
    detail = detail or plan.detail
    stored = plan.bars if outcome == "loaded" else []
    async with conn.transaction():
        await conn.execute(
            _INSERT_LOAD_SQL,
            load_id,
            symbol,
            SOURCE,
            start,
            end,
            outcome,
            len(stored) if stored else n_fetched,
            plan.n_new if stored else 0,
            plan.n_changed if stored else 0,
            stored[0].timestamp.date() if stored else None,
            stored[-1].timestamp.date() if stored else None,
            detail,
            _CALLER,
        )
        if stored:
            await conn.executemany(
                _INSERT_REVISION_SQL,
                [(load_id, symbol, ts, *old[:5], old[5]) for ts, old in plan.revisions],
            )
            await conn.executemany(
                _UPSERT_SQL,
                [
                    (b.timestamp, symbol, b.open, b.high, b.low, b.close, b.volume, SOURCE)
                    for b in stored
                ],
            )


async def _land_in_d1(
    conn: Any,
    sink: AsyncObservationSink,
    fetch_run_id: str,
    symbol: str,
    end: date,
    start: date,
    result: list[DailyBar] | str,
    requested_at: datetime,
) -> None:
    """Raw answer (or failure) into D1 before any canonical decision."""
    failed = isinstance(result, str)
    bars = [] if failed else result
    record = RequestRecord(
        request_id=str(uuid.uuid4()),
        fetch_run_id=fetch_run_id,
        symbol=symbol,
        timeframe="1d",
        route="TRADIER",
        what_to_show="TRADES",
        primary_exchange=None,
        window_start=datetime(start.year, start.month, start.day, tzinfo=UTC),
        window_end=datetime(end.year, end.month, end.day, tzinfo=UTC),
        ib_req_id=None,
        outcome="failed" if failed else ("bars" if bars else "no_data"),
        error_code=None,
        error_text=result if failed else None,
        n_bars=len(bars),
        client_id=None,
        requested_at=requested_at,
        answered_at=datetime.now(UTC),
    )
    sink.on_request(record)
    if bars:
        sink.on_observation(record, bars)
    await sink.flush(conn)


async def run(symbols: list[str] | None, rebase: bool, raw_only: bool) -> int:
    settings = get_settings()
    conn = await asyncpg.connect(settings.database_url)
    try:
        apr = await load_apr_dict_async(conn, ["infra.tradier.%"])
        params = LoadParams(
            min_session_ratio=float(apr["infra.tradier.min_session_ratio"]),
            first_date_tolerance_days=int(apr["infra.tradier.first_date_tolerance_days"]),
            max_changed_bar_ratio=float(apr["infra.tradier.max_changed_bar_ratio"]),
            rebase=rebase,
        )
        start = date.fromisoformat(apr["infra.tradier.history_start"])
        end = datetime.now(UTC).date() - timedelta(days=1)  # completed sessions only
        default_sql = _SELECT_NO_RAW_SQL if raw_only else _SELECT_MISSING_SQL
        todo = symbols or [r["symbol"] for r in await conn.fetch(default_sql)]
        logger.info(
            "tradier_daily.start",
            n_symbols=len(todo),
            rebase=rebase,
            start=str(start),
            end=str(end),
        )
        semaphore = asyncio.Semaphore(int(apr["infra.tradier.concurrency"]))
        client = make_client(
            settings.tradier_base_url,
            settings.tradier_api_token,
            float(apr["infra.tradier.request_timeout_s"]),
        )

        async def fetch(symbol: str) -> tuple[str, list[DailyBar] | str]:
            async with semaphore:
                try:
                    return symbol, await fetch_daily_history(client, symbol, start, end)
                except TradierError as error:
                    return symbol, str(error)

        counts: dict[str, int] = {}
        sink = AsyncObservationSink(caller=_CALLER, source=SOURCE)
        fetch_run_id = new_fetch_run_id()
        async with client:
            for pending in asyncio.as_completed([fetch(s) for s in todo]):
                symbol, result = await pending
                await _land_in_d1(
                    conn, sink, fetch_run_id, symbol, end, start, result, datetime.now(UTC)
                )
                if raw_only:
                    outcome = "failed" if isinstance(result, str) else "raw_landed"
                    counts[outcome] = counts.get(outcome, 0) + 1
                    continue
                if isinstance(result, str):
                    plan = LoadPlan("failed", result)
                    await _record_load(conn, symbol, start, end, plan, 0)
                else:
                    rows = await conn.fetch(_SELECT_EXISTING_SQL, symbol)
                    existing = {
                        r["timestamp"]: (
                            r["open"],
                            r["high"],
                            r["low"],
                            r["close"],
                            r["volume"],
                            r["source"],
                        )
                        for r in rows
                    }
                    plan = plan_symbol_load(result, existing, params)
                    await _record_load(conn, symbol, start, end, plan, len(result))
                counts[plan.outcome] = counts.get(plan.outcome, 0) + 1
                logger.info(
                    "tradier_daily.symbol",
                    symbol=symbol,
                    outcome=plan.outcome,
                    n_bars=len(plan.bars),
                    n_new=plan.n_new,
                    n_changed=plan.n_changed,
                    detail=plan.detail,
                )
        logger.info("tradier_daily.done", **counts)
        print(f"tradier daily load: {counts}")
        return 0 if set(counts) <= {"loaded", "raw_landed"} else 1
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--symbols", help="comma-separated; default: active equities with no 1d bars"
    )
    parser.add_argument(
        "--rebase", action="store_true", help="deliberate source change: skip the changed-bar gate"
    )
    parser.add_argument(
        "--raw-only",
        action="store_true",
        help="land D1 raw observations only: no canonical write, no ohlcv_load row",
    )
    args = parser.parse_args()
    setup_service_logging("logs/tradier_daily_loader.log")
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()] if args.symbols else None
    return asyncio.run(run(symbols, args.rebase, args.raw_only))


if __name__ == "__main__":
    sys.exit(main())
