#!/usr/bin/env python3
"""
infrastructure_run_historical_pipeline.py — historical OHLCV backfill from IBKR

Fetches multi-timeframe OHLCV from IBKR to market_data_ohlcv.
Run for initial system bootstrap or gap-filling.
Requires IBKR Gateway available; uses named contracts (HTF uses continuous).

The I1-I7 intelligence-replay stage (populating the archived signal_events/
trade_frames/intelligence_features tables) was removed 2026-07-08 — confirmed
dead (0 rows, all writer services inactive) via two independent investigations.
The full I1-I7 plugin corpus remains preserved in src/intelligence/archive/ for
any future reimplementation; see git history on this file for the removed
replay orchestration if ever needed for reference.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
import structlog

# Set up sys.path BEFORE importing from src
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


from src.config.contracts import (
    FUTURES_ROLL_CYCLES,
    MONTH_CODE_TO_NUM,
    derive_roll_chain,
    get_expiry_date,
)
from src.config.settings import Settings, get_active_contracts, get_all_futures_contracts
from src.core.bar_normalizer import (
    SOURCE_DERIVED_1M,
    SOURCE_SYNTHETIC_FILL,
    generate_session_slots,
    normalize_bars,
)
from src.core.database_manager import DatabaseManager
from src.core.models import AssetClass, ContractMetadata, Instrument
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers
from src.providers import IBKRProvider, ibkr

_logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Per-Contract Futures Storage — Renaissance-style canonical truth
# ---------------------------------------------------------------------------
#
# Functions for discovering contract chains and storing per-contract data.
# The continuous contract fetch (ContFuture + ADJUSTED_LAST) is kept as a
# fallback for backward compatibility until per-contract mode is enabled via flag.
#
# Renaissance Principle: Store raw per-contract data as canonical truth.
# Continuous series are derived layers, not storage format.
# Roll methodology is proprietary IP — baked-in continuous series prevent future optimization.


def _parse_contract_symbol(symbol: str) -> tuple[str, str, int] | None:
    """Parse a futures contract symbol into (base, month_code, year).

    Examples:
        "ESH6" -> ("ES", "H", 2026)
        "ESZ5" -> ("ES", "Z", 2025)
        "CLJ6" -> ("CL", "J", 2026)
        "CLM6" -> ("CL", "M", 2026)

    Returns None if not a valid futures contract symbol.
    """
    if len(symbol) < 3:
        return None
    # Last char is year digit (e.g., "6" for 2026)
    try:
        year_digit = int(symbol[-1])
        year = 2000 + year_digit
    except ValueError:
        return None

    # Second-to-last char is month code (e.g., "H" for March)
    month_code = symbol[-2].upper()
    if month_code not in MONTH_CODE_TO_NUM:
        return None

    # Everything before the month code is the base symbol
    base = symbol[:-2]

    return (base, month_code, year)


_CONTRACT_PREFIX_OVERRIDES: dict[str, str] = {"VIX": "VX"}


def _generate_contract_symbols(base: str, start_year: int, end_year: int) -> list[str]:
    """Generate all contract symbols for a base symbol between years.

    Uses FUTURES_ROLL_CYCLES for the correct expiry cycle per product.
    Returns list in chronological order (oldest first).

    Args:
        base: Base symbol (e.g., "ES", "NQ", "CL")
        start_year: Starting year (e.g., 2019)
        end_year: Ending year (e.g., 2026)
    """
    if base not in FUTURES_ROLL_CYCLES:
        return []
    cycle = FUTURES_ROLL_CYCLES[base]
    prefix = _CONTRACT_PREFIX_OVERRIDES.get(base, base)
    contracts: list[tuple[int, int, str]] = []  # (year, month_num, symbol)
    for year in range(start_year, end_year + 1):
        for code in cycle:
            month_num = MONTH_CODE_TO_NUM[code]
            symbol = f"{prefix}{code}{year % 10}"
            contracts.append((year, month_num, symbol))
    contracts.sort(key=lambda x: (x[0], x[1]))
    return [c[2] for c in contracts]


def _upsert_contract_metadata(db_conn: Any, metadata: list[ContractMetadata]) -> int:
    """Upsert contract metadata records.

    Args:
        db_conn: psycopg2 connection
        metadata: List of ContractMetadata objects

    Returns:
        Number of records upserted.
    """
    if not metadata:
        return 0

    sql = """
        INSERT INTO contract_metadata (
            symbol, base_symbol, asset_class, expiry_date, first_notice_date,
            roll_from, roll_to, roll_date, roll_gap, exchange
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (symbol) DO UPDATE SET
            base_symbol = EXCLUDED.base_symbol,
            asset_class = EXCLUDED.asset_class,
            expiry_date = EXCLUDED.expiry_date,
            first_notice_date = EXCLUDED.first_notice_date,
            roll_from = EXCLUDED.roll_from,
            roll_to = EXCLUDED.roll_to,
            roll_date = EXCLUDED.roll_date,
            roll_gap = EXCLUDED.roll_gap,
            exchange = EXCLUDED.exchange,
            updated_at = NOW()
    """

    params = [
        (
            m.symbol,
            m.base_symbol,
            m.asset_class.value,
            m.expiry_date,
            m.first_notice_date,
            m.roll_from,
            m.roll_to,
            m.roll_date,
            m.roll_gap,
            m.exchange,
        )
        for m in metadata
    ]

    with db_conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, params)
    db_conn.commit()
    return len(params)


async def fetch_per_contract(
    provider: IBKRProvider,
    instrument: Any,  # Instrument object
    timeframe: str,
    fetch_days: int,
    end_dt: datetime,
    db_conn: Any,
) -> tuple[int, list[ContractMetadata]]:
    """Fetch per-contract raw data for a futures base symbol.

    Instead of using ContFuture + ADJUSTED_LAST (back-adjusted continuous),
    this function fetches each individual contract in the roll chain and stores
    bars under their correct symbols.

    Args:
        provider: Connected IBKRProvider instance
        instrument: Current Instrument object (e.g., for ESH6)
        timeframe: Timeframe to fetch
        fetch_days: Number of days to fetch
        end_dt: End datetime for fetch
        db_conn: Database connection for storage

    Returns:
        (total_bars_fetched, metadata_list)
    """
    parsed = _parse_contract_symbol(instrument.symbol)
    if not parsed:
        return (0, [])

    base, _current_month, current_year = parsed

    overall_start = (end_dt - timedelta(days=fetch_days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start_year = overall_start.year

    contract_symbols = _generate_contract_symbols(base, start_year, current_year)

    metadata_list: list[ContractMetadata] = []
    total_bars = 0
    prev_expiry_dt: datetime | None = None

    for i, contract_sym in enumerate(contract_symbols):
        prefix = _CONTRACT_PREFIX_OVERRIDES.get(base, base)
        # Strip prefix to get month code + year digit
        suffix = contract_sym[len(prefix) :]  # e.g. "N6" from "CLN6"
        month_code = suffix[0]
        year_digit = int(suffix[1])
        # Recover 4-digit year: disambiguate via start/end range
        contract_year = current_year - (current_year % 10) + year_digit
        if contract_year > current_year:
            contract_year -= 10

        month_num = MONTH_CODE_TO_NUM[month_code]
        expiry_d = get_expiry_date(base, month_num, contract_year)
        expiry_dt = datetime.combine(expiry_d, datetime.min.time()).replace(tzinfo=UTC)

        # Each contract's active window: from previous contract's expiry to this one's expiry.
        # Clip to [overall_start, end_dt].
        contract_start = (prev_expiry_dt + timedelta(days=1)) if prev_expiry_dt else overall_start
        contract_start = max(contract_start, overall_start)
        contract_end = min(expiry_dt, end_dt)

        roll_from = contract_symbols[i - 1] if i > 0 else None
        roll_to = contract_symbols[i + 1] if i < len(contract_symbols) - 1 else None
        prev_expiry_dt = expiry_dt

        if contract_start >= contract_end:
            continue  # contract entirely outside our window

        contract_instrument = Instrument(
            symbol=contract_sym,
            name=f"{base} {month_num} {contract_year}",
            asset_class=AssetClass.FUTURES,
            exchange=instrument.exchange,
            session_id=instrument.session_id,
        )

        try:
            qualified = await provider.qualify_instrument(contract_instrument)
            if not qualified:
                print(f"    {contract_sym}: skip (qualify failed)")
                continue

            ohlcv_bars = await provider.fetch_historical_bars(
                symbol=contract_sym,
                timeframe=timeframe,
                start=contract_start,
                end=contract_end,
                continuous=False,
            )

            # Convert bar dicts
            bar_dicts = [
                {
                    "timestamp": b.timestamp,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                    "source": b.source,
                }
                for b in ohlcv_bars
            ]

            # Store bars under actual contract symbol
            n = store_bars(
                db_conn, bar_dicts, instrument.symbol, timeframe, actual_symbol=contract_sym
            )
            total_bars += n

            if n > 0:
                metadata = ContractMetadata(
                    symbol=contract_sym,
                    base_symbol=base,
                    asset_class=AssetClass.FUTURES,
                    expiry_date=expiry_dt,
                    first_notice_date=None,
                    roll_from=roll_from,
                    roll_to=roll_to,
                    roll_date=contract_start,
                    roll_gap=None,
                    exchange=instrument.exchange,
                )
                metadata_list.append(metadata)
                print(f"    {contract_sym}/{timeframe}: {n} bars")

            await asyncio.sleep(1)  # IBKR pacing between contracts

        except Exception as e:
            print(f"    {contract_sym}: error — {e}")

    # Upsert all metadata
    if metadata_list:
        _upsert_contract_metadata(db_conn, metadata_list)

    return (total_bars, metadata_list)


# Per-TF fetch config: (days_of_history, use_continuous_contract)
#
# Design rationale (Renaissance framing):
#   Goal: enough signal outcomes per (TF × regime × plugin) cell to fit stable logistic
#   regression for CIS weight adaptation. With 17 I7 plugins × ~3 regime types = 51 cells/TF,
#   we need ~20 outcomes/cell minimum → 1,020 signal outcomes per TF at statistical significance.
#
#   Signal fire rate: ~24 symbols × 2 signals/week = ~48 signals/week per TF (conservative).
#   Binding constraints per TF:
#     - HMM/GARCH: needs ~500+ bars for stable parameter estimation (1h/1d primary concern)
#     - Regime cycle coverage: need 2–3 full regime transitions to observe hit+miss per plugin
#     - CIS calibration: enough signal volume per cell for logistic regression to be meaningful
#
# Per-TF fetch config: (days_of_history, use_continuous_contract).
# NOTE: use_continuous only applies to FUTURES (see fetch loop at ~line 2376). For equities
# and ETFs, the chunked named-contract path is always used regardless of this flag.
_TF_FETCH_CONFIG: dict[str, tuple[int, bool]] = {
    # 1d: maximum available history. Only ~252 bars/year so 7300d (20yr) = ~5.2k bars/symbol —
    #     negligible storage. IBKR has clean data to 2005 (SPY probe 2026-06-19, minor gap
    #     at 20yr edge). Spans dot-com bust recovery, GFC, QE era, 2022 rate shock, AI mania.
    "1d": (7300, True),
    # 1h: HMM/GARCH anchor TF. 7300d (20yr) matches 1d depth — reaches back to 2006, capturing
    #     the GFC in addition to European debt crisis, QE1/QE2/QE3, taper tantrum (2013),
    #     2018 rate tantrum, COVID crash + recovery, zero-rate era, 2022 rate shock, and AI
    #     mania. Confirmed available via SPY probe 2026-07-02 (175,191 bars, 2006-07-07 to
    #     present); prior 5475d (15yr) was a deliberate cap, not a proven IBKR ceiling.
    #     ~35k bars/symbol, well clear of the 20k IC observation floor. use_continuous=False:
    #     IBKR ContFuture + ADJUSTED_LAST requires endDateTime="" (no chunking possible),
    #     timing out on COMEX instruments. Chunked named-contract path (_MAX_CHUNK_DAYS=364)
    #     is reliable across all exchanges.
    "1h": (7300, False),
    # 15m: bridges intraday and swing. 7300d (20yr) matches 1d/1h depth — reaches back to
    #     2006, same era coverage as 1h (GFC through AI mania). Confirmed available via SPY
    #     probe 2026-07-02 (700,770 bars, 2006-07-07 to present); prior 3650d/5475d caps were
    #     storage-tradeoff choices, not a proven IBKR ceiling. ~35k bars/symbol.
    "15m": (7300, True),
    # 5m: intraday + swing structure. 7300d (20yr) matches 1d/1h/15m depth — reaches back to
    #     2006. Was artificially capped at 1631d (4.5yr), then 3650d, then 5475d; each was a
    #     storage-tradeoff choice, not a proven IBKR ceiling. Confirmed available via SPY
    #     probe 2026-07-02 (2,102,364 bars, 2006-07-07 to present). ~105k bars/symbol/year.
    "5m": (7300, True),
    # 1m: intraday micro-patterns (time-of-day, session open/close, day-of-week). These
    #     repeat on weekly/monthly cycles so 90d captures all patterns with good repetition.
    #     ~75k bars/symbol. IBKR confirmed 10yr retention (SPY probe 2026-06-19) — 90d is
    #     a deliberate storage/compute tradeoff, not a retention constraint.
    "1m": (90, True),
}


def _load_tf_fetch_config(settings: Settings) -> dict[str, tuple[int, bool]]:
    """Overlay APR-configured backfill depths (infra.backfill.depth_days.*) onto
    _TF_FETCH_CONFIG defaults. Falls back to the hardcoded defaults above if the
    APR keys aren't present (e.g. migration 191 not yet applied) or the DB is
    unreachable — this is a one-shot CLI script, not a daemon, so no cache pre-warm.
    """
    config = dict(_TF_FETCH_CONFIG)
    try:
        conn = connect_db(settings)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT config_key, config_value FROM config_state "
                    "WHERE config_key LIKE 'infra.backfill.depth_days.%'"
                )
                rows = cur.fetchall()
        finally:
            conn.close()
        for key, value in rows:
            tf = key.rsplit(".", 1)[-1]
            if tf in config:
                config[tf] = (int(value), config[tf][1])
    except Exception as error:
        print(f"  (APR backfill-depth lookup failed, using hardcoded defaults: {error})")
    return config


def _load_ibkr_chunk_days_config(settings: Settings) -> None:
    """Overlay APR-configured chunk-size limits (infra.ibkr.chunk_days.*) onto
    ibkr._MAX_CHUNK_DAYS in place (migration 197). Same fallback contract as
    _load_tf_fetch_config above — falls back to the hardcoded defaults already in
    ibkr._MAX_CHUNK_DAYS if the APR keys aren't present or the DB is unreachable.
    """
    try:
        conn = connect_db(settings)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT config_key, config_value FROM config_state "
                    "WHERE config_key LIKE 'infra.ibkr.chunk_days.%'"
                )
                rows = cur.fetchall()
        finally:
            conn.close()
        for key, value in rows:
            tf = key.rsplit(".", 1)[-1]
            if tf in ibkr._MAX_CHUNK_DAYS:
                ibkr._MAX_CHUNK_DAYS[tf] = int(value)
    except Exception as error:
        print(f"  (APR chunk-days lookup failed, using hardcoded defaults: {error})")


def _load_ibkr_hist_timeout_config(settings: Settings) -> None:
    """Overlay the APR-configured outer request timeout (migration 199) onto
    ibkr._HIST_REQUEST_TIMEOUT_SEC in place. Same fallback contract as the loaders
    above -- falls back to the hardcoded default if the APR key isn't present or
    the DB is unreachable.
    """
    try:
        conn = connect_db(settings)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT config_value FROM config_state "
                    "WHERE config_key = 'infra.ibkr.historical_request_timeout_sec'"
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if row:
            ibkr._HIST_REQUEST_TIMEOUT_SEC = float(row[0])
    except Exception as error:
        print(f"  (APR hist-timeout lookup failed, using hardcoded default: {error})")

    try:
        conn = connect_db(settings)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT config_value FROM config_state "
                    "WHERE config_key = 'infra.ibkr.contract_details_timeout_sec'"
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if row:
            ibkr._CONTRACT_DETAILS_TIMEOUT_SEC = float(row[0])
    except Exception as error:
        print(f"  (APR contract-details-timeout lookup failed, using hardcoded default: {error})")


def _reorder_contracts_by_gap(
    contracts: list[Any], settings: Settings, timeframes: list[str]
) -> list[Any]:
    """Sort contracts by largest *recoverable* 5m/15m/1h history shortfall first.

    44 of 80 core ETFs have 5m truncated to 2022-01-03 while their own 15m/1h reach
    back to 2016/2011 against the same 20yr infra.backfill.depth_days.* target — a
    prior run's artifact, not an inception boundary. Scoring against the raw target
    would also rank young ETFs (e.g. IBIT, inception 2024) at the top, since they're
    "behind" on all three TFs identically — but that's a real inception wall, not
    fetchable data, and IBKR pacing makes wasting a cycle there expensive. Instead,
    each symbol's own deepest timeframe stands in for its true available history:
    shortfall = that proven depth minus a TF's actual depth. Young-ETF shortfalls
    collapse to ~0 (all TFs equally shallow); the 44-symbol 5m/15m split does not.
    """
    gap_tfs = [tf for tf in ("5m", "15m", "1h") if tf in timeframes]
    if not gap_tfs:
        return contracts

    tf_fetch_config = _load_tf_fetch_config(settings)
    now = datetime.now(UTC)
    gaps: dict[str, float] = {}
    try:
        conn = connect_db(settings)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT symbol, timeframe, min(timestamp) FROM market_data_ohlcv "
                    "WHERE timeframe = ANY(%s) GROUP BY symbol, timeframe",
                    (gap_tfs,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()
        earliest: dict[tuple[str, str], datetime] = {(r[0], r[1]): r[2] for r in rows}
        for c in contracts:
            actual_days = {}
            for tf in gap_tfs:
                actual = earliest.get((c.symbol, tf))
                actual_days[tf] = (now - actual).days if actual else 0
            proven_days = max(actual_days.values())
            gap_days = 0.0
            for tf in gap_tfs:
                target_days = tf_fetch_config.get(tf, (0, False))[0]
                ceiling = min(proven_days, target_days)
                gap_days += max(0, ceiling - actual_days[tf])
            gaps[c.symbol] = gap_days
    except Exception as error:
        print(f"  (gap-based reorder failed, keeping default order: {error})")
        return contracts

    ordered = list(contracts)
    ordered.sort(
        key=lambda c: (
            1 if c.asset_class == AssetClass.FX else 0,
            -gaps.get(c.symbol, 0.0),
            c.symbol,
        )
    )
    return ordered


# FX and crypto: IBKR *can* return higher-TF bars for major pairs (EURUSD, GBPUSD, etc.).
# The named fetch above attempts all TFs directly. This deep 1m window + derivation is
# a fallback for any TFs that IBKR didn't return bars for (e.g. exotic pairs, thin crypto).
#   FX (IDEALPRO/MIDPOINT): up to ~6 months of 1m available. 180d → ~1,300 derived 1h bars.
#   Crypto (PAXOS/AGGTRADES): Paxos data reliable for ~90d. 90d → ~2,160 derived 1h bars.
_1M_DAYS_FX: int = 180
_1M_DAYS_CRYPTO: int = 90


# ---------------------------------------------------------------------------
# Seed roll chain — populate contract_metadata with 3-contract chains
# ---------------------------------------------------------------------------

_SEED_ROLL_CHAIN_SQL = """
INSERT INTO contract_metadata (symbol, base_symbol, asset_class, roll_from, roll_to, is_front_month)
VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (symbol) DO UPDATE SET
    roll_from = EXCLUDED.roll_from,
    roll_to = EXCLUDED.roll_to,
    is_front_month = EXCLUDED.is_front_month,
    updated_at = NOW()
"""


async def seed_roll_chain(settings: Settings, db: DatabaseManager) -> None:
    """Populate contract_metadata with 3-contract roll chains for all futures instruments.

    For each unique futures base symbol in settings.contracts:
    1. Derives a 3-contract chronological chain via derive_roll_chain()
    2. UPSERTs each contract row with is_front_month=True for the first,
       False for the subsequent two
    3. ON CONFLICT (symbol) DO UPDATE ensures idempotent runs

    Non-futures instruments (equity, FX, crypto) are skipped.
    DB errors per base symbol are caught and logged — other symbols continue.

    Usage:
        python scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py --seed-roll-chain
    """
    import structlog

    log = structlog.get_logger(__name__)

    # Collect unique futures base symbols (order-preserving via dict.fromkeys)
    futures_bases: list[str] = list(
        dict.fromkeys(
            inst.base
            for inst in get_active_contracts(settings)
            if inst.asset_class == AssetClass.FUTURES and inst.base
        )
    )

    if not futures_bases:
        print("No futures base symbols found in settings — nothing to seed.")
        return

    total_contracts = 0
    for base_symbol in futures_bases:
        try:
            chain = derive_roll_chain(base_symbol)
            params: list[tuple] = []
            for i, contract in enumerate(chain):
                is_front_month = i == 0
                params.append(
                    (
                        contract["symbol"],
                        contract["base_symbol"],
                        "futures",
                        contract.get("roll_from"),
                        contract.get("roll_to"),
                        is_front_month,
                    )
                )
            await db.execute_batch(_SEED_ROLL_CHAIN_SQL, params)
            total_contracts += len(params)
            log.debug(
                "roll_chain_seeded",
                base=base_symbol,
                contracts=[c["symbol"] for c in chain],
                front_month=chain[0]["symbol"] if chain else None,
            )
        except Exception as error:
            log.error("seed_roll_chain_error", base=base_symbol, error=str(error))
            print(f"  [ERROR] seed_roll_chain: {base_symbol} — {error}")

    print(
        f"Roll chain seeded: {len(futures_bases)} base symbols, {total_contracts} contracts total"
    )
    log.info(
        "seed_roll_chain_complete",
        base_count=len(futures_bases),
        contract_count=total_contracts,
    )


# ---------------------------------------------------------------------------
# DB fetch/store layer
# ---------------------------------------------------------------------------

_FETCH_BARS_SQL = """
SELECT timestamp, open, high, low, close, volume, source
FROM market_data_ohlcv
WHERE symbol = %s AND timeframe = %s
ORDER BY timestamp ASC
"""

_FETCH_BARS_SINCE_SQL = """
SELECT timestamp, open, high, low, close, volume, source
FROM market_data_ohlcv
WHERE symbol = %s AND timeframe = %s AND timestamp >= %s
ORDER BY timestamp ASC
"""

_FETCH_BARS_BASE_SQL = """
SELECT timestamp, open, high, low, close, volume, source
FROM market_data_ohlcv
WHERE symbol LIKE %s AND timeframe = %s
ORDER BY timestamp ASC
"""

_FETCH_BARS_BASE_SINCE_SQL = """
SELECT timestamp, open, high, low, close, volume, source
FROM market_data_ohlcv
WHERE symbol LIKE %s AND timeframe = %s AND timestamp >= %s
ORDER BY timestamp ASC
"""

_STORE_SQL = """
INSERT INTO market_data_ohlcv
    (timestamp, symbol, timeframe, open, high, low, close, volume, source)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (timestamp, symbol, timeframe) DO NOTHING
"""

_TF_MINUTES: dict[str, int] = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}


def detect_gaps(
    db_conn: Any,
    symbol: str,
    timeframe: str,
    start_dt: datetime,
    end_dt: datetime,
    session_id: str,
    exchange: str,
) -> list[tuple[datetime, datetime]]:
    """Detect gaps in OHLCV data, restricted to expected session slots.

    Uses session-aware slot generation so maintenance windows and market
    closures are not reported as gaps.  Returns contiguous missing ranges
    ready for use as IBKR fetch windows.
    """
    expected = generate_session_slots(session_id, exchange, timeframe, start_dt, end_dt)
    if not expected:
        return []

    with db_conn.cursor() as cur:
        cur.execute(
            """SELECT timestamp FROM market_data_ohlcv
               WHERE symbol = %s AND timeframe = %s
                 AND timestamp >= %s AND timestamp <= %s""",
            (symbol, timeframe, start_dt, end_dt),
        )
        rows = cur.fetchall()
        actual: set[datetime] = {
            r[0].replace(tzinfo=UTC) if r[0].tzinfo is None else r[0] for r in rows
        }

    missing = [ts for ts in expected if ts not in actual]
    if not missing:
        return []

    interval = timedelta(minutes=_TF_MINUTES[timeframe])
    ranges: list[tuple[datetime, datetime]] = []
    run_start = missing[0]
    run_end = missing[0]
    for ts in missing[1:]:
        if ts - run_end == interval:
            run_end = ts
        else:
            ranges.append((run_start, run_end))
            run_start = run_end = ts
    ranges.append((run_start, run_end))
    return ranges


def connect_db(settings: Settings) -> Any:
    """Create a synchronous psycopg2 connection from Settings DSN."""
    conn = psycopg2.connect(dsn=settings.database_url)
    conn.autocommit = True
    return conn


def aggregate_bars_from_1m(bars_1m: list[dict], target_tf: str) -> list[dict]:
    """Aggregate 1m OHLCV bars to a higher timeframe by flooring to window boundaries."""
    minutes = _TF_MINUTES[target_tf]
    windows: dict[datetime, list[dict]] = {}
    for bar in bars_1m:
        ts = bar["timestamp"]
        if minutes < 1440:
            # Floor using total elapsed minutes from midnight so multi-hour TFs (e.g. 4h)
            # snap to correct boundaries. Minute-only floor (ts.minute // minutes) breaks
            # for any TF where minutes >= 60 because ts.hour is left unchanged.
            total = ts.hour * 60 + ts.minute
            floored_total = (total // minutes) * minutes
            floored = ts.replace(
                hour=floored_total // 60,
                minute=floored_total % 60,
                second=0,
                microsecond=0,
            )
        else:
            floored = ts.replace(hour=0, minute=0, second=0, microsecond=0)
        windows.setdefault(floored, []).append(bar)

    result = []
    for window_start in sorted(windows):
        w = windows[window_start]
        result.append(
            {
                "timestamp": window_start,
                "open": w[0]["open"],
                "high": max(b["high"] for b in w),
                "low": min(b["low"] for b in w),
                "close": w[-1]["close"],
                "volume": sum(b.get("volume", 0) or 0 for b in w),
                "source": SOURCE_DERIVED_1M,
            }
        )
    return result


def fetch_bars(conn: Any, symbol: str, timeframe: str, since: datetime | None = None) -> list[dict]:
    """Fetch stored OHLCV bars for *symbol* + *timeframe*, ordered oldest-first.

    For futures contracts (e.g. ESM6), also stitches bars from all historical
    contract symbols sharing the same base (ESH6, ESZ5, …) so full history is
    available regardless of which contract was front-month at fetch time.
    Duplicate timestamps across contracts are deduplicated (last-seen wins).

    Args:
        since: If provided, only fetch bars on or after this timestamp.
    """
    parsed = _parse_contract_symbol(symbol)
    is_futures = parsed is not None

    # Determine query and params based on contract type
    if is_futures:
        base_pattern = f"{parsed[0]}%"
        query = _FETCH_BARS_BASE_SINCE_SQL if since else _FETCH_BARS_BASE_SQL
        params = (base_pattern, timeframe, since) if since else (base_pattern, timeframe)
    else:
        query = _FETCH_BARS_SINCE_SQL if since else _FETCH_BARS_SQL
        params = (symbol, timeframe, since) if since else (symbol, timeframe)

    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

    bars = [
        {
            "timestamp": row[0] if row[0].tzinfo else row[0].replace(tzinfo=UTC),
            "symbol": symbol,
            "timeframe": timeframe,
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
            "source": row[6] or "historical_backfill",
        }
        for row in rows
    ]

    if is_futures:
        # Deduplicate by timestamp — last-seen wins (SQL already ordered by timestamp ASC)
        seen: dict[datetime, dict] = {b["timestamp"]: b for b in bars}
        return list(seen.values())  # Preserves insertion order (Python 3.7+)

    return bars


def store_bars(
    conn: Any,
    bars: list[dict],
    symbol: str,
    timeframe: str,
    actual_symbol: str | None = None,
) -> int:
    """Upsert bars into market_data_ohlcv. Returns count inserted.

    Args:
        conn: psycopg2 connection
        bars: List of bar dicts with timestamp, open, high, low, close, volume
        symbol: Used for contract lookup (e.g., current active contract)
        timeframe: Timeframe string
        actual_symbol: If provided, stores bars under this symbol instead of `symbol`.
            Enables per-contract storage when fetching historical contracts.
    """
    if not bars:
        return 0
    # Use actual_symbol if provided (for historical contracts), otherwise use symbol
    store_symbol = actual_symbol or symbol
    params = [
        (
            b["timestamp"],
            store_symbol,
            timeframe,
            b["open"],
            b["high"],
            b["low"],
            b["close"],
            b["volume"],
            b.get("source", "historical_backfill"),
        )
        for b in bars
    ]
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, _STORE_SQL, params)
    conn.commit()
    return len(params)


# Normalization pass
# ---------------------------------------------------------------------------


def run_normalize(
    db_conn: Any,
    contracts: list[Any],
    timeframes: list[str],
) -> None:
    """One-time pass: fill gaps in existing market_data_ohlcv with synthetic
    flat bars so the table holds a complete canonical grid.

    Idempotent — existing rows are never overwritten (ON CONFLICT DO NOTHING).
    """
    print("\nNormalization pass — filling gaps in market_data_ohlcv")
    print(f"  Symbols   : {[c.symbol for c in contracts]}")
    print(f"  Timeframes: {timeframes}")

    total_inserted = 0

    for instrument in contracts:
        for tf in timeframes:
            rows = fetch_bars(db_conn, instrument.symbol, tf)
            if not rows:
                print(f"  {instrument.symbol}/{tf}: no existing rows — skipping")
                continue

            start = min(b["timestamp"] for b in rows)
            end = max(b["timestamp"] for b in rows)

            canonical = normalize_bars(
                rows,
                symbol=instrument.symbol,
                timeframe=tf,
                start=start,
                end=end,
            )

            new_bars = [b for b in canonical if b["source"] == SOURCE_SYNTHETIC_FILL]

            if not new_bars:
                print(f"  {instrument.symbol}/{tf}: already canonical ({len(rows)} rows)")
                continue

            n = store_bars(db_conn, new_bars, instrument.symbol, tf)
            total_inserted += n
            print(
                f"  {instrument.symbol}/{tf}: inserted {n} synthetic fills "
                f"(was {len(rows)} rows, now {len(rows) + n})"
            )

    print(f"\nNormalization complete: {total_inserted} synthetic fills inserted")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Historical Backfill — fetch IBKR bars")
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Max days to fetch for ALL timeframes (default: per-TF config defaults).",
    )
    parser.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated symbols, e.g. ESH6,NQH6 (default: all active)",
    )
    parser.add_argument(
        "--timeframes",
        default="1d,1h,15m,5m,1m",
        help="Comma-separated timeframes (default: 1m,5m,15m,1h,4h,1d)",
    )
    parser.add_argument("--client-id", type=int, default=40, help="IBKR client ID (default: 40)")
    parser.add_argument(
        "--include-rolled",
        action="store_true",
        help=(
            "Include rolled/expired futures contracts (not just is_front_month=true). "
            "Non-futures instruments are always included regardless of this flag."
        ),
    )
    parser.add_argument(
        "--per-contract",
        action="store_true",
        help="Fetch per-contract raw data (Renaissance style) instead of back-adjusted continuous. "
        "Requires reseed after. Disabled by default for backward compatibility.",
    )
    parser.add_argument(
        "--seed-roll-chain",
        action="store_true",
        help="Populate contract_metadata with 3-contract roll chain per active futures base "
        "symbol. Sets is_front_month=True for the current front-month contract. "
        "Idempotent — safe to run multiple times.",
    )
    parser.add_argument(
        "--normalize",
        action="store_true",
        default=False,
        help="Fill gaps in existing market_data_ohlcv rows with synthetic flat bars. "
        "Idempotent — safe to re-run. Combines with --symbols to limit scope.",
    )
    args = parser.parse_args()

    settings = Settings()

    # --seed-roll-chain: populate contract_metadata roll chains and exit
    if args.seed_roll_chain:
        from src.core.database_manager import DatabaseManager as _DM

        async def _seed() -> None:
            db = _DM(settings.database_url)
            await db.initialize()
            await seed_roll_chain(settings, db)
            await db.close()

        asyncio.run(_seed())
        return

    timeframes = [t.strip() for t in args.timeframes.split(",") if t.strip()]

    # Filter contracts
    if getattr(args, "include_rolled", False):
        # All futures (rolled + front-month) + non-futures from get_active_contracts
        all_futures = get_all_futures_contracts(settings)
        active = get_active_contracts(settings)
        futures_symbols = {c.symbol for c in all_futures}
        non_futures = [c for c in active if c.symbol not in futures_symbols]
        contracts = all_futures + non_futures
    else:
        contracts = get_active_contracts(settings)
    if args.symbols:
        wanted = {s.strip() for s in args.symbols.split(",") if s.strip()}
        # Match on full contract symbol (e.g. ESM6) OR base symbol (e.g. ES)
        contracts = [
            c
            for c in contracts
            if c.symbol in wanted or (_parse_contract_symbol(c.symbol) or (None,))[0] in wanted
        ]
        if not contracts:
            print(f"No matching contracts for: {args.symbols}")
            return

    contracts = _reorder_contracts_by_gap(contracts, settings, timeframes)

    tf_fetch_config = _load_tf_fetch_config(settings)
    _load_ibkr_chunk_days_config(settings)
    _load_ibkr_hist_timeout_config(settings)

    print("Historical Backfill Pipeline")
    print(f"  Contracts : {[c.symbol for c in contracts]}")
    print(f"  Timeframes: {timeframes}")
    tf_depths = {
        tf: (min(tf_fetch_config[tf][0], args.days) if args.days else tf_fetch_config[tf][0])
        for tf in timeframes
        if tf in tf_fetch_config
    }
    print(f"  TF depths : {tf_depths}")
    print()

    db_conn = connect_db(settings)

    if args.normalize:
        run_normalize(db_conn, contracts, timeframes)
        db_conn.close()
        return

    async def _run_fetch_stage() -> tuple[int, int, list[str]]:
        nonlocal db_conn
        provider = IBKRProvider(
            host=settings.ib_host,
            port=settings.ib_port,
            client_id=args.client_id,
        )
        if not await provider.connect():
            print("Cannot connect to TWS — aborting fetch stage")
            return -1, 0, []

        end_dt = datetime.now(tz=UTC)
        total_bars = 0
        # [rca_analysis 2026-07-05, F5] Per-(symbol, tf) fetch exceptions below are
        # caught and printed but previously just swallowed — main() would still
        # unconditionally print "Backfill complete." regardless of how many of these
        # fired. Tracked here so the caller can propagate a nonzero exit code instead
        # of silently declaring success with real holes.
        fetch_errors = 0
        # [todo 051] Symbols skipped outright (IBKR reconnect or qualify failure) —
        # tracked separately from fetch_errors so the final summary can name them,
        # not just count them.
        skipped_symbols: list[str] = []
        fetch_tfs = [tf for tf in timeframes if tf in tf_fetch_config]
        print(f"  Fetching TFs: {fetch_tfs}")
        print()
        try:
            for instrument in contracts:
                try:
                    db_conn.cursor().execute("SELECT 1")
                except Exception:
                    print("  DB connection stale — reconnecting before next symbol...")
                    try:
                        db_conn.close()
                    except Exception:
                        pass
                    db_conn = connect_db(settings)
                try:
                    # [todo 051] qualify_instrument swallows IBKR socket-disconnect
                    # exceptions and returns False the same as a genuine "contract not
                    # found" — from here that's indistinguishable. is_connected() is the
                    # actual disconnect signal: reconnect on it before treating the
                    # symbol as unqualifiable, instead of silently skipping every
                    # remaining symbol for the rest of the run (previously only db_conn
                    # was reconnected — the IBKR socket never was).
                    if not provider.is_connected():
                        print("  IBKR connection lost — reconnecting...")
                        if not await provider.connect():
                            print(f"  {instrument.symbol}: skipped (IBKR reconnect failed)")
                            fetch_errors += 1
                            skipped_symbols.append(instrument.symbol)
                            await asyncio.sleep(2)
                            continue
                        print("  IBKR reconnected.")
                    qualified = await provider.qualify_instrument(instrument)
                    if not qualified:
                        print(f"  {instrument.symbol}: skipped (qualify failed)")
                        fetch_errors += 1
                        skipped_symbols.append(instrument.symbol)
                        continue

                    # Per-contract mode for futures: fetch each contract in roll chain
                    if args.per_contract and instrument.asset_class == AssetClass.FUTURES:
                        print(f"  {instrument.symbol}: per-contract mode (Renaissance-style)")
                        for tf in fetch_tfs:
                            fetch_days, _ = tf_fetch_config[tf]
                            if args.days:
                                fetch_days = min(fetch_days, args.days)
                            print(f"  {instrument.symbol}/{tf} (per-contract, {fetch_days}d):")
                            bars, metadata = await fetch_per_contract(
                                provider=provider,
                                instrument=instrument,
                                timeframe=tf,
                                fetch_days=fetch_days,
                                end_dt=end_dt,
                                db_conn=db_conn,
                            )
                            total_bars += bars
                        continue  # Skip the standard continuous fetch loop

                    # Standard mode: use continuous contract for longer timeframes
                    fetched_tfs: set[str] = set()  # TFs that got bars from IBKR directly
                    for tf in fetch_tfs:
                        fetch_days, use_continuous = tf_fetch_config[tf]
                        if args.days:
                            fetch_days = min(fetch_days, args.days)

                        start_dt = (end_dt - timedelta(days=fetch_days)).replace(
                            hour=0, minute=0, second=0, microsecond=0
                        )

                        gaps = detect_gaps(
                            db_conn,
                            instrument.symbol,
                            tf,
                            start_dt,
                            end_dt,
                            session_id=instrument.session_id,
                            exchange=instrument.exchange,
                        )
                        if not gaps:
                            print(f"  {instrument.symbol}/{tf}: no gaps found.")
                            fetched_tfs.add(tf)
                            continue

                        # Bound the fetch to the actual missing span instead of the
                        # full configured window — a symbol with 10y already loaded
                        # that needs 20y should only request the missing 10y, not
                        # re-request data IBKR has already given us.
                        gap_start = min(g[0] for g in gaps)
                        gap_end = max(g[1] for g in gaps)
                        print(
                            f"  {instrument.symbol}/{tf}: {len(gaps)} gaps detected, "
                            f"fetching {gap_start.date()} to {gap_end.date()}..."
                        )

                        # Skip continuous contracts for short windows (no rolls needed)
                        use_cont = (
                            use_continuous
                            and (fetch_days > 14)
                            and (instrument.asset_class == AssetClass.FUTURES)
                        )

                        # Fetch the gap-bounded window in one call; the provider chunks
                        # at _MAX_CHUNK_DAYS[tf] (364d for 4h/1h/1d) with 10s between
                        # chunks. Per-gap (rather than per-run) fetching sent N×IBKR
                        # requests + N×2s sleep for trivially small windows — absurdly
                        # slow on initial backfill — so gaps within one run are still
                        # coalesced into a single request. ON CONFLICT DO NOTHING makes
                        # this idempotent regardless.
                        # [rca_analysis 2026-07-05, F1/F2] Persist each chunk's real
                        # bars as soon as they arrive, in addition to the full-window
                        # normalize_bars()+store_bars() pass below. Without this, DB
                        # growth (and thus the external stall watchdog's heartbeat) only
                        # happens once per (symbol, tf), after the entire — potentially
                        # many-chunk, many-minute — fetch completes, and a kill mid-fetch
                        # discards all in-memory progress for that (symbol, tf). This
                        # writes raw real bars only (no synthetic fill, which needs the
                        # full window's prev_close carried across chunk boundaries — see
                        # normalize_bars). ON CONFLICT DO NOTHING in store_bars makes the
                        # later full-window pass re-affirming these rows a safe no-op.
                        async def _persist_chunk(
                            chunk_bars: list, _tf: str = tf, _symbol: str = instrument.symbol
                        ) -> None:
                            nonlocal db_conn
                            if not chunk_bars:
                                return
                            chunk_dicts = [
                                {
                                    "timestamp": b.timestamp,
                                    "open": b.open,
                                    "high": b.high,
                                    "low": b.low,
                                    "close": b.close,
                                    "volume": b.volume,
                                    "source": b.source,
                                }
                                for b in chunk_bars
                            ]
                            try:
                                db_conn.cursor().execute("SELECT 1")
                            except Exception:
                                try:
                                    db_conn.close()
                                except Exception:
                                    pass
                                db_conn = connect_db(settings)
                            store_bars(db_conn, chunk_dicts, _symbol, _tf)

                        try:
                            ohlcv_bars = await provider.fetch_historical_bars(
                                symbol=instrument.symbol,
                                timeframe=tf,
                                start=gap_start,
                                end=gap_end,
                                continuous=use_cont,
                                on_chunk=_persist_chunk,
                            )
                            bar_dicts = [
                                {
                                    "timestamp": b.timestamp,
                                    "open": b.open,
                                    "high": b.high,
                                    "low": b.low,
                                    "close": b.close,
                                    "volume": b.volume,
                                    "source": b.source,
                                }
                                for b in ohlcv_bars
                            ]
                            canonical = normalize_bars(
                                bar_dicts,
                                symbol=instrument.symbol,
                                timeframe=tf,
                                start=gap_start,
                                end=gap_end,
                            )
                            try:
                                db_conn.cursor().execute("SELECT 1")
                            except Exception:
                                try:
                                    db_conn.close()
                                except Exception:
                                    pass
                                db_conn = connect_db(settings)
                            n = store_bars(db_conn, canonical, instrument.symbol, tf)
                            total_bars += n
                            if n > 0:
                                fetched_tfs.add(tf)
                            print(
                                f"  {instrument.symbol}/{tf}: stored {n} bars "
                                f"({len(gaps)} gaps filled)"
                            )
                        except Exception as e:
                            fetch_errors += 1
                            print(f"  {instrument.symbol}/{tf}: fetch error — {e}")

                    # FX and crypto: fetch deeper 1m window and derive any TFs
                    # that IBKR didn't return bars for in the named fetch above.
                    if instrument.asset_class in (AssetClass.FX, AssetClass.CRYPTO):
                        missing_tfs = [
                            tf for tf in ("5m", "15m", "1h", "1d") if tf not in fetched_tfs
                        ]
                        if missing_tfs:
                            deep_days = (
                                _1M_DAYS_FX
                                if instrument.asset_class == AssetClass.FX
                                else _1M_DAYS_CRYPTO
                            )
                            deep_start = (end_dt - timedelta(days=deep_days)).replace(
                                hour=0, minute=0, second=0, microsecond=0
                            )
                            try:
                                deep_bars = await provider.fetch_historical_bars(
                                    symbol=instrument.symbol,
                                    timeframe="1m",
                                    start=deep_start,
                                    end=end_dt,
                                    continuous=False,
                                )
                                deep_dicts = [
                                    {
                                        "timestamp": b.timestamp,
                                        "open": b.open,
                                        "high": b.high,
                                        "low": b.low,
                                        "close": b.close,
                                        "volume": b.volume,
                                        "source": b.source,
                                    }
                                    for b in deep_bars
                                ]
                                canonical_1m = normalize_bars(
                                    deep_dicts,
                                    symbol=instrument.symbol,
                                    timeframe="1m",
                                    start=deep_start,
                                    end=end_dt,
                                )
                                n = store_bars(db_conn, canonical_1m, instrument.symbol, "1m")
                                print(f"  {instrument.symbol}/1m (deep {deep_days}d): {n} bars")
                            except Exception as e:
                                fetch_errors += 1
                                print(f"  {instrument.symbol}/1m deep fetch error — {e}")
                            bars_1m = fetch_bars(db_conn, instrument.symbol, "1m")
                            if bars_1m:
                                for derived_tf in missing_tfs:
                                    aggregated = aggregate_bars_from_1m(bars_1m, derived_tf)
                                    n = store_bars(
                                        db_conn, aggregated, instrument.symbol, derived_tf
                                    )
                                    total_bars += n
                                    sym = instrument.symbol
                                    print(f"  {sym}/{derived_tf} (derived from 1m): {n} bars")
                            else:
                                print(f"  {instrument.symbol}: no 1m bars — skipping derivation")
                        else:
                            sym = instrument.symbol
                            print(f"  {sym}: all TFs fetched from IBKR — skipping derivation")

                    # 4h bars are fetched directly from IBKR at 730d depth above.
                    # No derivation needed: 1m only covers 14d (named contract, no rolls)
                    # which is inferior in both depth and price series to the direct fetch.
                    # Gaps in IBKR 4h data are handled by the gap detection + refetch path.

                except Exception as e:
                    fetch_errors += 1
                    print(f"  {instrument.symbol}: error — {e}")
                    try:
                        db_conn.cursor().execute("SELECT 1")
                    except Exception:
                        print("  DB connection lost — reconnecting...")
                        try:
                            db_conn.close()
                        except Exception:
                            pass
                        db_conn = connect_db(settings)
                await asyncio.sleep(2)  # IBKR pacing between instruments
        finally:
            await provider.disconnect()
        return total_bars, fetch_errors, skipped_symbols

    total_bars, fetch_errors, skipped_symbols = asyncio.run(_run_fetch_stage())
    if total_bars == -1:
        db_conn.close()
        return

    n_requested = len(contracts)
    n_skipped = len(skipped_symbols)
    print(f"\nStage 1 complete: {total_bars:,} total bars stored, {fetch_errors} fetch error(s)\n")
    if skipped_symbols:
        print(
            f"{n_skipped}/{n_requested} symbols skipped outright "
            f"(IBKR reconnect or qualify failure): {skipped_symbols}\n"
        )
    # [rca_analysis 2026-07-05, F5] Don't silently print "Backfill complete." when
    # real fetch errors occurred — that string is exactly what backfill_retry_loop.sh
    # greps for to decide the run was clean. A nonzero exit here makes the retry loop
    # correctly treat this as incomplete and try again, instead of declaring victory
    # over silent holes.
    if fetch_errors > 0:
        print(
            f"Backfill FINISHED WITH {fetch_errors} FETCH ERROR(S) — "
            "not declaring complete. See error lines above."
        )
        JOB_COMPLETED_TOTAL.add(1, {"job": "historical-backfill", "status": "partial"})
        db_conn.close()
        flush_and_shutdown_metrics()
        sys.exit(1)

    JOB_COMPLETED_TOTAL.add(1, {"job": "historical-backfill", "status": "success"})
    db_conn.close()
    flush_and_shutdown_metrics()
    print("\nBackfill complete.")


if __name__ == "__main__":
    try:
        init_otel_providers("historical-backfill")
    except OTelInitError as error:
        print(f"[warn] OTel init failed — metrics disabled: {error}")
    main()
