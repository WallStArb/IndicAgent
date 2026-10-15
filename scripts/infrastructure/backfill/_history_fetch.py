"""_history_fetch.py -- IBKR history fetch helpers for the phase 189 fetcher.

A helper library with no CLI and no lock of its own. Its only runtime caller is
ohlcv_history_fetcher.py (directly and through _history_fetch_item.py), which holds
FetcherLock for the whole run, so nothing here coordinates the IBKR history stream.
Manual IBKR tools that import a helper (the chunk and rate-limit probe, the intraday
venue recovery) take FetcherLock themselves.

What lives here: per-contract futures discovery and storage, the APR overlays onto
src/providers/ibkr.py's module constants (chunk days, request timeout, retries, venue
fallback, rate limit) and onto this module's batch sizes, the legacy grid gap planner
(detect_gaps, cluster_gap_ranges), the D1 capture kwargs and flush, the roll-chain seed, and the bar store path through the raw-first ingress contract
(store_bars).

Plan 189-08 renamed this module from the historical pipeline CLI script (`git log
--follow` shows its history) and removed its CLI, the two-tier IBKR history lease, the
legacy gap ranking (now _fetch_queue.coverage_gap_days) and the fetch_complete
bookkeeping writer (promotion reads bar_integrity verdicts since plan 185-41).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import structlog

from services.complete_bar_gate import keep_complete, read_settle
from services.ohlcv_ingress_contract import DEFAULT_CALLER, apply_raw_contract
from services.ohlcv_raw_writer import RawRow
from src.config.contracts import (
    FUTURES_ROLL_CYCLES,
    MONTH_CODE_TO_NUM,
    derive_roll_chain,
    get_expiry_date,
)
from src.config.settings import Settings, get_active_contracts
from src.core.database_manager import DatabaseManager
from src.core.models import AssetClass, ContractMetadata, Instrument
from src.intelligence.bars.gap_plan import AnsweredWindows, expected_grid_slots
from src.intelligence.bars.vendor_kind import label_to_vendor_kind
from src.providers import IBKRProvider, ibkr

_log = structlog.get_logger(__name__)


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


# Timeframes whose gap detection comes from the shared record planner
# (detect_gaps_from_record): expected slots minus stored observations minus recorded
# coverage, with the provider-verified empty span folded in. 1m stays on the legacy
# grid difference until its own record migration; 1d is planned from the recorded
# daily answers (detect_gaps_1d_from_d1).
_RECORD_PLAN_TFS = frozenset({"5m", "15m", "1h"})
_OBSERVATION_BATCH_ROWS_KEY = "infra.ohlcv_observation.copy_batch_rows"
_OBSERVATION_BATCH_ROWS_FALLBACK = 50_000  # migration 380 APR seed


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
        db_conn: psycopg connection
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
        cur.executemany(sql, params)
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

            asked_at = datetime.now(UTC)
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
                db_conn,
                bar_dicts,
                instrument.symbol,
                timeframe,
                actual_symbol=contract_sym,
                asked_at=asked_at,
                request_end=contract_end,
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


def _load_ibkr_retry_config(settings: Settings) -> None:
    """Overlay the APR-configured retry/backoff/no-data-confirmation constants
    (migration 235) onto ibkr._RETRY_COUNT / _RETRY_BACKOFF_BASE_S /
    _NO_DATA_CONFIRMATION_CHUNKS in place. Same fallback contract as the loaders
    above -- falls back to the hardcoded defaults if the APR keys aren't present
    or the DB is unreachable.
    """
    try:
        conn = connect_db(settings)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT config_key, config_value FROM config_state "
                    "WHERE config_key IN ("
                    "'infra.ibkr.retry_count', "
                    "'infra.ibkr.retry_backoff_base_s', "
                    "'infra.ibkr.no_data_confirmation_chunks')"
                )
                rows = dict(cur.fetchall())
        finally:
            conn.close()
        if "infra.ibkr.retry_count" in rows:
            ibkr._RETRY_COUNT = int(rows["infra.ibkr.retry_count"])
        if "infra.ibkr.retry_backoff_base_s" in rows:
            ibkr._RETRY_BACKOFF_BASE_S = int(rows["infra.ibkr.retry_backoff_base_s"])
        if "infra.ibkr.no_data_confirmation_chunks" in rows:
            ibkr._NO_DATA_CONFIRMATION_CHUNKS = int(rows["infra.ibkr.no_data_confirmation_chunks"])
    except Exception as error:
        print(f"  (APR retry-config lookup failed, using hardcoded defaults: {error})")


def _fetch_start(end_dt: datetime, fetch_days: int) -> datetime:
    """Start of a fetch_days-deep window: fetch_days calendar dates including end_dt's, from
    midnight UTC. end_dt minus fetch_days floored to midnight would span fetch_days + 1 dates,
    and where the depth equals the chunk size (1d: 7300 and 7300) the backward walk spent a
    second request on that one extra date, doubling 1d requests."""
    return (end_dt - timedelta(days=fetch_days - 1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def _load_ibkr_venue_fallback_config(settings: Settings) -> None:
    """Overlay the APR-configured former-venue recovery parameters (migration 374, todo 433)
    onto ibkr._VENUE_FALLBACK_EXCHANGES / _VENUE_FALLBACK_TIMEFRAMES /
    _VENUE_FALLBACK_MIN_GAP_DAYS / _VENUE_FALLBACK_STORE_BARS in place. Same fallback contract as the loaders above --
    falls back to the hardcoded defaults if the APR keys aren't present or the DB is
    unreachable.
    """
    try:
        conn = connect_db(settings)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT config_key, config_value FROM config_state "
                    "WHERE config_key LIKE 'infra.ibkr.venue_fallback.%'"
                )
                rows = dict(cur.fetchall())
        finally:
            conn.close()
        if "infra.ibkr.venue_fallback.exchanges" in rows:
            ibkr._VENUE_FALLBACK_EXCHANGES = list(
                json.loads(rows["infra.ibkr.venue_fallback.exchanges"])
            )
        if "infra.ibkr.venue_fallback.timeframes" in rows:
            ibkr._VENUE_FALLBACK_TIMEFRAMES = set(
                json.loads(rows["infra.ibkr.venue_fallback.timeframes"])
            )
        if "infra.ibkr.venue_fallback.min_gap_days" in rows:
            ibkr._VENUE_FALLBACK_MIN_GAP_DAYS = int(rows["infra.ibkr.venue_fallback.min_gap_days"])
        if "infra.ibkr.venue_fallback.store_bars" in rows:
            ibkr._VENUE_FALLBACK_STORE_BARS = rows["infra.ibkr.venue_fallback.store_bars"] == "true"
    except Exception as error:
        print(f"  (APR venue-fallback lookup failed, using hardcoded defaults: {error})")


def _load_ibkr_rate_limit_config(settings: Settings) -> None:
    """Overlay the APR-configured historical-data rate-limit parameters
    (infra.ibkr.rate_limit_max_requests / infra.ibkr.rate_limit_window_sec,
    migration 276) onto ibkr._IBKR_HIST_RATE_LIMIT / ibkr._IBKR_HIST_WINDOW_S in
    place, same pattern as the loaders above -- _hist_rate_limiter.acquire() reads
    these module constants fresh on every call. Same fallback contract as the
    loaders above -- falls back to the hardcoded defaults (55 requests / 600s
    window) if the APR keys aren't present or the DB is unreachable.
    """
    try:
        conn = connect_db(settings)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT config_key, config_value FROM config_state "
                    "WHERE config_key IN ("
                    "'infra.ibkr.rate_limit_max_requests', "
                    "'infra.ibkr.rate_limit_window_sec', "
                    "'infra.ibkr.rate_limit_max_requests_by_tf')"
                )
                rows = dict(cur.fetchall())
        finally:
            conn.close()
        ibkr.apply_hist_rate_limit_config(rows)
    except Exception as error:
        print(f"  (APR rate-limit lookup failed, using hardcoded defaults: {error})")


def _load_observation_batch_rows(settings: Settings) -> int:
    """APR infra.ohlcv_observation.copy_batch_rows (migration 380 seed as the
    fallback), same overlay contract as the loaders above."""
    try:
        conn = connect_db(settings)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT config_value FROM config_state WHERE config_key = %s",
                    (_OBSERVATION_BATCH_ROWS_KEY,),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if row and row[0] is not None:
            return int(row[0])
    except Exception as error:
        print(f"  (APR observation batch-rows lookup failed, using default: {error})")
    return _OBSERVATION_BATCH_ROWS_FALLBACK


def _capture_kwargs(sink: Any, fetch_run_id: str) -> dict[str, Any]:
    """Provider fetch kwargs for request capture (D-05/D-16/D-20): every timeframe reports its
    requests to the fetch ledger sink. The 1d caller adds `on_observation` (the persister's
    handler), because only the daily answer carries the route and what_to_show that decide its
    raw kind; intraday chunks arrive through on_chunk."""
    return {"on_request": sink.on_request, "fetch_run_id": fetch_run_id}


def _flush_capture(sink: Any, settings: Settings) -> tuple[int, int]:
    """Flush the fetch ledger sink, reconnecting its dedicated connection once if it died.

    A flush failure raises (the symbol fails loudly): D-05 request rows must never be
    dropped silently.
    """
    try:
        return sink.flush()
    except psycopg.OperationalError:
        sink.reconnect(connect_db(settings))
        return sink.flush()


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
        python scripts/infrastructure/backfill/ohlcv_history_fetcher.py --seed-roll-chain
    """
    log = _log

    # Collect unique futures base symbols (order-preserving via dict.fromkeys)
    futures_bases: list[str] = list(
        dict.fromkeys(
            inst.base
            for inst in get_active_contracts(settings, dimension="compute")
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


_TF_MINUTES: dict[str, int] = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}


def detect_gaps(
    db_conn: Any,
    symbol: str,
    timeframe: str,
    start_dt: datetime,
    end_dt: datetime,
    session_id: str,
    exchange: str,
    answered: AnsweredWindows | None = None,
    *,
    vendor: str,
) -> list[tuple[datetime, datetime]]:
    """Detect gaps in `vendor`'s own raw OHLCV rows, restricted to expected session slots.

    Uses session-aware slot generation so maintenance windows and market
    closures are not reported as gaps.  Returns contiguous missing ranges
    ready for use as IBKR fetch windows.

    Plan 185-18 task 1a moved 5m/15m/1h to the shared record planner
    (detect_gaps_from_record, fed by gap_plan.plan_gaps); this grid
    difference stays as the legacy fallback for 1m, 4h and 1d (1d migrates
    in task 1b).

    `answered` is the provider-answered request coverage (todo 462). With no placeholder rows
    stored, a slot the provider answered "nothing traded" is otherwise indistinguishable from
    one never asked, and would be re-requested every run. A covered slot is not a gap.
    """
    expected = expected_grid_slots(session_id, exchange, timeframe, start_dt, end_dt)
    if not expected:
        return []

    with db_conn.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT "timestamp" FROM ohlcv_raw
               WHERE symbol = %s AND timeframe = %s AND vendor = %s
                 AND "timestamp" >= %s AND "timestamp" <= %s""",
            (symbol, timeframe, vendor, start_dt, end_dt),
        )
        rows = cur.fetchall()
        actual: set[datetime] = {
            r[0].replace(tzinfo=UTC) if r[0].tzinfo is None else r[0] for r in rows
        }

    interval = timedelta(minutes=_TF_MINUTES[timeframe])
    missing = [
        ts
        for ts in expected
        if ts not in actual and not (answered is not None and answered.covers(ts, interval))
    ]
    if not missing:
        return []

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


# [2026-08-11] A symbol with a genuine listing-history boundary (recent IPO,
# spin-off, relisting -- e.g. AA/Alcoa Corporation only trades from 2016-10-18,
# nothing before exists at IBKR under this contract) produces one permanent,
# never-fillable gap range at the start of the requested window, alongside
# unrelated small gaps elsewhere (e.g. a 1-day incremental catch-up near "now").
# Naive min/max bounding across ALL gap ranges collapses these into one giant
# request spanning the already-fully-populated middle -- every backfill re-run
# then re-requests the entire history from IBKR even though only a sliver near
# the front or back is actually missing. The ingress write contract (plan 185-39)
# keeps this correct (identical rows are not rewritten), just wasteful of real,
# rate-limited IBKR request budget on every run.
# Cluster gap ranges by proximity instead: ranges separated by more than this
# many days of already-present data get their own IBKR request rather than
# forcing a single request to re-cover the gap between them.
_GAP_CLUSTER_MAX_DAYS = 90


def _load_gap_cluster_max_days_config(settings: Settings) -> None:
    """Overlay infra.backfill.gap_cluster_max_days (migration 313) onto
    _GAP_CLUSTER_MAX_DAYS in place, same pattern as the _load_ibkr_* loaders above.
    Falls back to the hardcoded default (90) if the APR key isn't present or the DB
    is unreachable.
    """
    global _GAP_CLUSTER_MAX_DAYS
    try:
        conn = connect_db(settings)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT config_value FROM config_state "
                    "WHERE config_key = 'infra.backfill.gap_cluster_max_days'"
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if row is not None:
            _GAP_CLUSTER_MAX_DAYS = int(row[0])
    except Exception as error:
        print(f"  (APR gap_cluster_max_days lookup failed, using hardcoded default: {error})")


def cluster_gap_ranges(
    gaps: list[tuple[datetime, datetime]], max_gap_days: int | None = None
) -> list[tuple[datetime, datetime]]:
    """Merge nearby gap ranges into fetch windows, keeping distant ones separate.

    `gaps` must be sorted ascending (detect_gaps already returns them that way).
    Returns one (start, end) fetch-window tuple per cluster.

    max_gap_days defaults to the CURRENT _GAP_CLUSTER_MAX_DAYS module global, read
    at call time rather than bound as a def-time default -- a plain `= _GAP_CLUSTER_
    MAX_DAYS` default would freeze the value at import time and silently ignore any
    later _load_gap_cluster_max_days_config() APR overlay for every caller that
    doesn't pass max_gap_days explicitly.
    """
    if not gaps:
        return []
    max_gap = timedelta(days=max_gap_days if max_gap_days is not None else _GAP_CLUSTER_MAX_DAYS)
    clusters: list[list[tuple[datetime, datetime]]] = [[gaps[0]]]
    for g in gaps[1:]:
        if g[0] - clusters[-1][-1][1] <= max_gap:
            clusters[-1].append(g)
        else:
            clusters.append([g])
    return [(cluster[0][0], cluster[-1][1]) for cluster in clusters]


def connect_db(settings: Settings) -> Any:
    """Create a synchronous psycopg connection from Settings DSN."""
    conn = psycopg.connect(settings.database_url)
    conn.autocommit = True
    return conn


def store_bars(
    conn: Any,
    bars: list[dict],
    symbol: str,
    timeframe: str,
    actual_symbol: str | None = None,
    *,
    asked_at: datetime | None = None,
    request_end: datetime | None = None,
    caller: str = DEFAULT_CALLER,
) -> int:
    """Offer bars to ohlcv_raw through the raw-first ingress contract. Returns the rows offered.

    Complete bars only (second review of 191-07, finding 5): `asked_at` is when the caller asked
    (a lower bound on the answer time) and `request_end` the end it asked for; a bar that was
    still forming, straddles the end or closes the session before the settle delay is held back
    (logged with its values by services/complete_bar_gate; these callers have no request row).
    A caller that passes no `asked_at` is judged at the time of this call: an upper bound on the
    answer time, seconds after it. Only services/backfill_feature_factory relies on that, because
    editing it renames every feature unit it writes (its own file is in its code key); todo 535.

    Args:
        conn: psycopg connection
        bars: List of bar dicts with timestamp, open, high, low, close, volume and source (the
            bar source label, mapped to (vendor, kind) by vendor_kind; a label with no pair raises)
        symbol: Used for contract lookup (e.g., current active contract)
        timeframe: Timeframe string
        actual_symbol: If provided, stores bars under this symbol instead of `symbol`.
            Enables per-contract storage when fetching historical contracts.

    The write is one transaction: the load row, the raw rows and the canonical selection commit
    together or not at all. Rows are written last-wins by serve time (D-191-N; fourth review of
    191-07, finding 1): their served_at is `asked_at` (else this call's time), and a value the
    vendor served later than that stays in raw. These ad hoc callers (the per-contract opt-in mode, the backfill feature factory, the
    venue recovery and the chunk probe) have no ohlcv_request ledger row: the raw rows carry a
    fresh request_id.

    Refuses timeframe "1d" outright (plan 185-18 task 1b): the fetcher's 1d answers arrive with a
    route and what_to_show (the persister's on_observation), which decide their raw kind; a bare
    bar dict has neither.
    """
    if not bars:
        return 0
    if timeframe == "1d":
        raise RuntimeError(
            "store_bars refuses timeframe 1d: a daily answer's raw kind comes from its route "
            "and what_to_show, which the fetcher's observation handler carries"
        )
    with conn.cursor() as cur:
        settle = read_settle(cur)
    answered_at = asked_at or datetime.now(UTC)
    bars, _partial, _text = keep_complete(
        bars,
        timeframe,
        answered_at=answered_at,
        request_end=request_end,
        settle=settle,
        symbol=actual_symbol or symbol,
        caller=caller,
    )
    if not bars:
        return 0
    store_symbol = actual_symbol or symbol
    rows = []
    for b in bars:
        vendor, kind = label_to_vendor_kind(b["source"])
        rows.append(
            RawRow(
                timestamp=b["timestamp"],
                symbol=store_symbol,
                timeframe=timeframe,
                vendor=vendor,
                kind=kind,
                open=b["open"],
                high=b["high"],
                low=b["low"],
                close=b["close"],
                volume=None if b["volume"] is None else int(b["volume"]),
            )
        )
    with conn.transaction():
        # served_at is the caller's answer time; without one, this call's time (seconds after
        # the answer it was handed), never the database write time.
        result = apply_raw_contract(
            conn, rows, caller=caller, request_id=uuid.uuid4(), answered_at=answered_at
        )
    if result.n_unselected:
        raise RuntimeError(
            f"store_bars: {symbol} {timeframe}: {result.n_unselected} slots reached raw but no "
            "ranked vendor selects them (no bar_source_policy span ranks this vendor)"
        )
    return len(rows)
