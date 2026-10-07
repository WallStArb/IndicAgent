#!/usr/bin/env python3
"""
infrastructure_run_historical_pipeline.py — historical OHLCV backfill from IBKR

Fetches multi-timeframe OHLCV from IBKR to market_data_ohlcv.
Run for initial system bootstrap or gap-filling.
Requires IBKR Gateway available; uses named contracts (HTF uses continuous).

Every IBKR historical request this process makes holds the ibkr_history_stream
lease first (D-29, phase 185 plan 09): acquired before the first request,
checkpointed after every completed (symbol, timeframe) unit, released at exit.
Bulk tier (the default) yields to any waiter at unit boundaries; priority tier
(the nightly, phase 185 campaigns) yields only to another priority waiter.

Exit codes: 0 success; 1 fetch errors/partial run; 3 could not get the lease
within its wait bound (EXIT_LEASE_TIMEOUT -- the nightly maps this to
failed_lease_timeout).

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
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import structlog

# Set up sys.path BEFORE importing from src
# NOTE: this file is scripts/infrastructure/backfill/<this file> -- 4 parents reach repo
# root (backfill/ -> infrastructure/ -> scripts/ -> root), not 3. A 3-parent count landed
# at scripts/ and made `import src` fail unless PYTHONPATH was already set externally,
# masked because every production invocation sets PYTHONPATH explicitly (systemd
# Environment=, or manual `PYTHONPATH=. python ...`) -- found 2026-08-06 while building
# infrastructure_nightly_backfill.py, whose own correctly-counted 4-parent bootstrap sits
# right next to this file.
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))


from scripts.infrastructure.backfill import _empty_history as empty_history
from scripts.infrastructure.backfill._d1_gaps import (
    detect_gaps_1d_from_d1,
    detect_gaps_from_record,
    load_answered_windows,
    midnight_utc,
    with_overlap_window,
)
from scripts.infrastructure.backfill._derivation_stage import run_derivation_stage
from scripts.infrastructure.backfill._intraday_persist import persist_chunk_atomically
from services.intraday_raw_archive import insert_fetched_archive_rows
from services.ohlcv_ingress_contract import (
    DEFAULT_CALLER,
    DESTINATION_GRID,
    apply_ingress_contract,
)
from services.ohlcv_observation_writer import ObservationSink, new_fetch_run_id
from src.config.contracts import (
    FUTURES_ROLL_CYCLES,
    MONTH_CODE_TO_NUM,
    derive_roll_chain,
    get_expiry_date,
)
from src.config.settings import Settings, get_active_contracts, get_all_futures_contracts
from src.core.bar_normalizer import SOURCE_DERIVED_1M
from src.core.database_manager import DatabaseManager
from src.core.models import AssetClass, ContractMetadata, Instrument
from src.core.resource_lease import LeaseTimeout, ResourceLease, Tier
from src.intelligence.bars.gap_plan import AnsweredWindows, expected_grid_slots
from src.intelligence.bars.sessions import nyse_sessions
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers
from src.providers import IBKRProvider, ibkr
from src.providers.base import EmptyHistory

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


_DEFAULT_TIMEFRAMES = "1d,1h,15m,5m,1m"
_EMPTY_HISTORY_PROVIDER = "ibkr"  # ohlcv_empty_history.provider for this pipeline's fetches
# Timeframes whose fetch persists real provider bars only, every asset class (todo 462,
# plan 185-18): no synthetic fill ever reaches market_data_ohlcv from this pipeline at
# 5m or 1m, and 15m/1h are archive-bound raw observations (plan 12). The interim flag
# that gated this is retired -- it is the default behavior now. 1d joined in task 1b
# (its fetch captures into D1 and stores no bar here at all); 4h joined in plan 185-32,
# so no timeframe keeps a placeholder path (migration 444 refuses synthetic_fill).
_REAL_BARS_ONLY_TFS = frozenset({"5m", "1m", "15m", "1h", "4h", "1d"})
# Timeframes whose gap detection comes from the shared record planner
# (detect_gaps_from_record): expected slots minus stored observations minus recorded
# coverage, with the provider-verified empty span folded in. 1m stays on the legacy
# grid difference until its own record migration; 1d moved to D1 in task 1b
# (detect_gaps_1d_from_d1), so it is planned but never stored.
_RECORD_PLAN_TFS = frozenset({"5m", "15m", "1h"})
# Plan 12 (D-15/D-06): 15m and 1h are archive-bound raw observations. Their fetches
# persist into ohlcv_intraday_raw_archive through services/intraday_raw_archive's
# single-writer module, gap detection reads that archive and expects IBKR's own RTH
# grid, and no synthetic fill is ever produced for them -- the grid readers see is
# derived from 5m by services/bar_derivation.py (the nightly chains it).
_ARCHIVE_TFS = frozenset({"15m", "1h"})
# Dimensions whose members may be deliberately scoped below the full timeframe stack.
_DIMENSIONS_REQUIRING_EXPLICIT_TIMEFRAMES = frozenset({"backfill", "compute_1d"})

# D-29: the single IBKR history stream. Lives beside its consumers, not in
# src/core/ (Ring 0 carries no domain vocabulary).
IBKR_HISTORY_LEASE = "ibkr_history_stream"
# Distinct exit code for "could not get the lease in time" so the nightly can
# map it to failed_lease_timeout (documented in both module docstrings).
EXIT_LEASE_TIMEOUT = 3
_OBSERVATION_CALLER = "historical-pipeline"
_LEASE_APR_KEY = "infra.ibkr_history_lease.priority_wait_minutes"
_OBSERVATION_BATCH_ROWS_KEY = "infra.ohlcv_observation.copy_batch_rows"
_OBSERVATION_BATCH_ROWS_FALLBACK = 50_000  # migration 380 APR seed
_LEASE_PRIORITY_MINUTES_FALLBACK = 240.0  # migration 380 APR seed


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


_MARK_FETCH_COMPLETE_SQL = """
INSERT INTO backfill_status (symbol, tf, fetch_complete, status)
SELECT %(symbol)s, %(tf)s, true, 'pending'
WHERE EXISTS (
    SELECT 1 FROM market_data_ohlcv_tradeable
    WHERE symbol = %(symbol)s AND timeframe = %(tf)s AND timestamp >= %(since)s
)
ON CONFLICT (symbol, tf) DO UPDATE SET fetch_complete = true
"""


def mark_fetch_complete(conn: Any, symbol: str, tf: str, since: datetime) -> None:
    """Record that `symbol`/`tf` fetched without error and has tradeable bars.

    The eligibility promotion predicates (COMPUTE_READY_1D_PREDICATE_SQL and its sibling)
    require backfill_status.fetch_complete; this script used to leave it false, so each
    onboarding batch set it by hand (phase 174 plans 10 and 15, the 2026-09-26 expansion). The
    EXISTS guard keeps a clean fetch that stored nothing from counting as complete; bounding it
    to the fetched window (`since`) lets TimescaleDB skip every older chunk. Only ever sets the
    flag, never clears it; status (the compute checkpoint) is left alone.
    """
    with conn.cursor() as cur:
        cur.execute(_MARK_FETCH_COMPLETE_SQL, {"symbol": symbol, "tf": tf, "since": since})


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


def _load_lease_apr_minutes(settings: Settings) -> float:
    """APR infra.ibkr_history_lease.priority_wait_minutes, with the migration 380
    seed as the fallback when the DB is unreachable (same contract as the loaders
    above)."""
    try:
        conn = connect_db(settings)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT config_value FROM config_state WHERE config_key = %s",
                    (_LEASE_APR_KEY,),
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if row and row[0] is not None:
            return float(row[0])
    except Exception as error:
        print(f"  (APR lease-wait lookup failed, using default: {error})")
    return _LEASE_PRIORITY_MINUTES_FALLBACK


def _lease_wait_seconds(settings: Settings, args: argparse.Namespace) -> float | None:
    """Acquire timeout for the history lease. An explicit --lease-wait-minutes
    wins (the nightly passes its own bound); otherwise priority defaults to the
    APR seed and bulk waits unbounded (a bulk holder re-queues forever by
    design; it has nowhere else to go)."""
    if args.lease_wait_minutes is not None:
        return args.lease_wait_minutes * 60.0
    if args.lease_tier == "priority":
        return _load_lease_apr_minutes(settings) * 60.0
    return None


def _acquire_history_lease(settings: Settings, args: argparse.Namespace) -> ResourceLease:
    """Take the ibkr_history_stream lease before the first IBKR request (D-29).

    The process that talks to IBKR holds the lease, never an orchestrating
    parent. On timeout the lease connection is closed and LeaseTimeout
    propagates (main maps it to EXIT_LEASE_TIMEOUT).
    """
    lease = ResourceLease(
        settings.database_url,
        IBKR_HISTORY_LEASE,
        tier=Tier(args.lease_tier),
        holder=f"{_OBSERVATION_CALLER}:{args.client_id}",
    )
    try:
        lease.acquire(_lease_wait_seconds(settings, args))
    except LeaseTimeout:
        lease.close()
        raise
    return lease


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


def _capture_kwargs(tf: str, sink: Any, fetch_run_id: str) -> dict[str, Any]:
    """Provider fetch kwargs for D1 capture (D-05/D-16/D-20): every timeframe
    reports its requests; only 1d delivers observations, because D1 stores 1d
    bars only -- intraday answers live on as request outcomes for D4 to
    re-verify from."""
    kwargs: dict[str, Any] = {"on_request": sink.on_request, "fetch_run_id": fetch_run_id}
    if tf == "1d":
        kwargs = dict(kwargs, on_observation=sink.on_observation)
    return kwargs


def _flush_capture(sink: Any, settings: Settings) -> tuple[int, int]:
    """Flush the D1 sink, reconnecting its dedicated connection once if it died.

    A flush failure raises (the symbol fails loudly): D-05 rows are raw answers
    that must never be dropped silently.
    """
    try:
        return sink.flush()
    except psycopg.OperationalError:
        sink.reconnect(connect_db(settings))
        return sink.flush()


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

    Depth sources (todo 449, 2026-10-01): archive-bound TFs (15m/1h) are read from
    ohlcv_intraday_raw_archive, where the lane has written since 185-12; grid TFs keep
    the tradeable view. The 1d depth joins the proven floor, so a name with no intraday
    data anywhere still ranks by the history its own 1d series proves fetchable.
    """
    gap_tfs = [tf for tf in ("5m", "15m", "1h") if tf in timeframes]
    if not gap_tfs:
        return contracts

    # Archive-bound TFs track their depth in the raw archive (185-12), not the grid, and a
    # name with no intraday data anywhere scores 0 against a 0-day "proven" floor; its own
    # 1d history stands in instead, so never-touched names rank by real available depth.
    archive_tfs = [tf for tf in gap_tfs if tf in _ARCHIVE_TFS]
    grid_tfs = [tf for tf in gap_tfs if tf not in _ARCHIVE_TFS]
    tf_fetch_config = _load_tf_fetch_config(settings)
    now = datetime.now(UTC)
    gaps: dict[str, float] = {}
    try:
        conn = connect_db(settings)
        try:
            with conn.cursor() as cur:
                rows = []
                if archive_tfs:
                    cur.execute(
                        "SELECT symbol, timeframe, min(timestamp) FROM ohlcv_intraday_raw_archive "
                        "WHERE timeframe = ANY(%s) GROUP BY symbol, timeframe",
                        (archive_tfs,),
                    )
                    rows += cur.fetchall()
                if grid_tfs:
                    # Tradeable view, not the raw table (todo 124) -- purely for clarity, not
                    # a behavior change: normalize_bars() never fabricates a synthetic fill
                    # before a symbol's first real bar (needs a prev_close to seed from), so
                    # min(timestamp) is identical either way.
                    cur.execute(
                        "SELECT symbol, timeframe, min(timestamp) FROM market_data_ohlcv_tradeable "
                        "WHERE timeframe = ANY(%s) GROUP BY symbol, timeframe",
                        (grid_tfs,),
                    )
                    rows += cur.fetchall()
                cur.execute(
                    "SELECT symbol, min(timestamp) FROM market_data_ohlcv_tradeable "
                    "WHERE timeframe = '1d' GROUP BY symbol"
                )
                rows += [(r[0], "1d", r[1]) for r in cur.fetchall()]
        finally:
            conn.close()
        earliest: dict[tuple[str, str], datetime] = {(r[0], r[1]): r[2] for r in rows}
        for c in contracts:
            actual_days = {}
            for tf in gap_tfs:
                actual = earliest.get((c.symbol, tf))
                actual_days[tf] = (now - actual).days if actual else 0
            first_1d = earliest.get((c.symbol, "1d"))
            proven_days = max(
                list(actual_days.values()) + [(now - first_1d).days if first_1d else 0]
            )
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

# Measured 2026-08-11 against live psycopg3 (not EXPLAIN, which re-plans every call
# and overstates the gap): a single multi-row VALUES INSERT per 1000-row batch runs
# ~2x faster than the same rows via executemany()'s one-tuple-per-statement template
# (0.0265ms/row vs 0.0515ms/row, 20k-row live benchmark). This is a different approach
# than forward_return_writer.py's chunked executemany() (which relies on psycopg 3.1+
# batching executemany() internally -- see ic_engine.py's comment on that same
# tradeoff) -- the live benchmark here shows executemany()'s internal batching still
# leaves real per-statement overhead that a genuine multi-row VALUES statement avoids,
# at least for this bulk-insert shape. Not yet reconciled with those other call sites
# or promoted to a shared helper -- see todo 301.
_STORE_BATCH_SIZE = 1000
_STORE_ROW_PLACEHOLDERS = "(" + ",".join(["%s"] * 9) + ")"
# Plain multi-row INSERT of new rows (plan 185-39): the ingress write contract classifies a chunk
# against the stored rows first, so a conflict never reaches this statement.
_STORE_VALUES_SQL = (
    "INSERT INTO market_data_ohlcv "
    "(timestamp, symbol, timeframe, open, high, low, close, volume, source) VALUES "
    "{values}"
)
# The same insert for the changed set: the latest answer wins, and the contract has already
# written the replaced values to ohlcv_revision. An upsert, not a raw UPDATE of the compressed
# hypertable, so the market_data_ohlcv writer boundary allow-list stays empty.
_STORE_REPLACE_SQL = (
    _STORE_VALUES_SQL + " ON CONFLICT (timestamp, symbol, timeframe) DO UPDATE SET "
    "open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low, close = EXCLUDED.close, "
    "volume = EXCLUDED.volume, source = EXCLUDED.source"
)


def _load_ohlcv_insert_batch_size_config(settings: Settings) -> None:
    """Overlay infra.backfill.ohlcv_insert_batch_size (migration 313) onto
    _STORE_BATCH_SIZE in place, same pattern as the _load_ibkr_* loaders above --
    store_bars() reads this module constant fresh on every call. Falls back to the
    hardcoded default (1000) if the APR key isn't present, isn't a positive int, or
    the DB is unreachable. A non-positive value must never reach store_bars(): 0
    makes range(0, len(params), 0) raise on every insert, and a negative value makes
    the chunk loop yield zero iterations, so store_bars() would silently write
    nothing while still returning len(params) -- callers would log "N bars stored"
    and mark the tf fetched (fetched_tfs.add(tf)) for data that was never persisted.
    """
    global _STORE_BATCH_SIZE
    try:
        conn = connect_db(settings)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT config_value FROM config_state "
                    "WHERE config_key = 'infra.backfill.ohlcv_insert_batch_size'"
                )
                row = cur.fetchone()
        finally:
            conn.close()
        if row is not None:
            value = int(row[0])
            if value < 1:
                print(
                    f"  (APR ohlcv_insert_batch_size={value} is not positive, "
                    "using hardcoded default 1000)"
                )
            else:
                _STORE_BATCH_SIZE = value
    except Exception as error:
        print(f"  (APR ohlcv_insert_batch_size lookup failed, using hardcoded default: {error})")


_TF_MINUTES: dict[str, int] = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}


def real_bars_only_for(tf: str) -> bool:
    """Whether `tf`'s fetch persists real provider bars only (no synthetic fill).

    15m/1h are archive-bound raw observations since plan 12 (a placeholder is
    never an observation, and the archive insert refuses synthetic fills
    outright); plan 185-18 made 5m and 1m real bars only for every asset class
    (todo 462), retiring the interim flag that used to gate it. Task 1b took 1d
    further still: its answers are captured into D1 and nothing is stored here
    at all (store_bars refuses 1d). Plan 185-32 added 4h, the last placeholder
    path, so every timeframe stores real bars only; migration 444 makes the
    database refuse a synthetic_fill row.
    """
    return tf in _REAL_BARS_ONLY_TFS


def detect_gaps(
    db_conn: Any,
    symbol: str,
    timeframe: str,
    start_dt: datetime,
    end_dt: datetime,
    session_id: str,
    exchange: str,
    answered: AnsweredWindows | None = None,
) -> list[tuple[datetime, datetime]]:
    """Detect gaps in OHLCV data, restricted to expected session slots.

    Uses session-aware slot generation so maintenance windows and market
    closures are not reported as gaps.  Returns contiguous missing ranges
    ready for use as IBKR fetch windows.

    Plan 185-18 task 1a moved 5m/15m/1h to the shared record planner
    (detect_gaps_from_record, fed by gap_plan.plan_gaps); this grid
    difference stays as the legacy fallback for 1m, 4h and 1d (1d migrates
    in task 1b). 15m/1h read the archive (plan 12): their stored bars live in
    ohlcv_intraday_raw_archive, so market_data_ohlcv would report every slot
    missing and refetch everything.

    `answered` is the provider-answered request coverage (todo 462). With no placeholder rows
    stored, a slot the provider answered "nothing traded" is otherwise indistinguishable from
    one never asked, and would be re-requested every run. A covered slot is not a gap.
    """
    expected = expected_grid_slots(session_id, exchange, timeframe, start_dt, end_dt)
    if not expected:
        return []

    stored_table = (
        "ohlcv_intraday_raw_archive" if timeframe in _ARCHIVE_TFS else "market_data_ohlcv"
    )
    with db_conn.cursor() as cur:
        cur.execute(
            f"""SELECT timestamp FROM {stored_table}
               WHERE symbol = %s AND timeframe = %s
                 AND timestamp >= %s AND timestamp <= %s""",
            (symbol, timeframe, start_dt, end_dt),
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


def _write_market_data_batches(sql_template: str, cur: Any, params: list[tuple]) -> None:
    for i in range(0, len(params), _STORE_BATCH_SIZE):
        chunk = params[i : i + _STORE_BATCH_SIZE]
        sql = sql_template.format(values=",".join([_STORE_ROW_PLACEHOLDERS] * len(chunk)))
        cur.execute(sql, [value for row in chunk for value in row])


def _insert_market_data_rows(cur: Any, params: list[tuple]) -> int:
    """Write one chunk to market_data_ohlcv by the ingress write contract (plan 185-39; the
    default store_bars destination, 5m/1m from plan 185-18 on; 15m/1h route to the archive and
    1d is refused outright in task 1b).

    Stored rows for the chunk's keys are read and each row is classified new, changed or
    unchanged by exact value: new rows are inserted, changed rows are rewritten with their old
    values recorded in ohlcv_revision, unchanged rows are not written, and one ohlcv_load row
    (source ibkr) records the counts. A chunk that revises more than the refusal ratio raises
    RevisionRefused before any write. Returns the rows offered (the persist helper's coverage
    arithmetic depends on that).
    """
    return apply_ingress_contract(
        cur,
        params,
        destination=DESTINATION_GRID,
        caller=DEFAULT_CALLER,
        write_new=lambda c, rows: _write_market_data_batches(_STORE_VALUES_SQL, c, rows),
        write_changed=lambda c, rows: _write_market_data_batches(_STORE_REPLACE_SQL, c, rows),
    )


def _insert_archive_rows(cur: Any, params: list[tuple]) -> int:
    """Archive destination for 15m/1h fetched chunks (plan 12): routes through
    services/intraday_raw_archive, the table's single writer (base is NULL on
    fetched bars; batch_id stays NULL). Accepts both call shapes: store_bars'
    9-column row tuples and the atomic persist helper's 10-column rows (base
    already included)."""
    rows = params if len(params[0]) == 10 else [row + (None,) for row in params]
    return insert_fetched_archive_rows(cur, rows, batch_size=_STORE_BATCH_SIZE)


def store_bars(
    conn: Any,
    bars: list[dict],
    symbol: str,
    timeframe: str,
    actual_symbol: str | None = None,
    write_rows: Any | None = None,
) -> int:
    """Upsert bars into the destination for `timeframe`. Returns count inserted.

    Args:
        conn: psycopg connection
        bars: List of bar dicts with timestamp, open, high, low, close, volume
        symbol: Used for contract lookup (e.g., current active contract)
        timeframe: Timeframe string
        actual_symbol: If provided, stores bars under this symbol instead of `symbol`.
            Enables per-contract storage when fetching historical contracts.
        write_rows: (cur, params) -> int for the destination's own insert; defaults
            to the market_data_ohlcv multi-row insert. 15m/1h callers pass the
            archive writer (plan 12); plan 18's persist helper takes the same
            function as a parameter, so this module owns no bar-table INSERT for
            the archive path.

    Refuses timeframe "1d" outright (plan 185-18 task 1b): market_data_ohlcv's
    1d rows belong to services/bar_derivation's daily stage (D-06/D-15 single
    writer); this pipeline captures 1d answers into D1 only. The per-contract
    opt-in mode is the one remaining caller that can hit this -- its per-
    contract except prints the refusal.
    """
    if not bars:
        return 0
    if timeframe == "1d":
        raise RuntimeError(
            "store_bars refuses timeframe 1d: market_data_ohlcv 1d rows are owned by "
            "services/bar_derivation's daily stage (plan 185-18 task 1b); this "
            "pipeline captures 1d answers into D1 only"
        )
    if write_rows is None:
        write_rows = _insert_market_data_rows
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
        write_rows(cur, params)
    conn.commit()
    return len(params)


# ---------------------------------------------------------------------------
# Daily derivation stage (plan 185-18 task 1b)
# ---------------------------------------------------------------------------


def _run_daily_stage(symbols: list[str]) -> int:
    """Derive the 1d grid rows for `symbols` through services/bar_derivation.py.

    Since task 1b this pipeline's 1d fetch captures answers into D1 and stores
    no bar; bar_derivation's daily stage is the single writer of 1d rows in
    market_data_ohlcv (D-06/D-15). main() invokes it once per run, over every
    symbol whose 1d windows were asked, and a nonzero return code fails the
    run loudly -- a silent skip would leave the run "complete" with no 1d rows.
    """
    return run_derivation_stage("daily", "--symbols", ",".join(symbols), "--apply")


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
        default=None,
        help=(
            f"Comma-separated timeframes (default: {_DEFAULT_TIMEFRAMES}). Required with "
            "--dimension backfill/compute_1d."
        ),
    )
    parser.add_argument("--client-id", type=int, default=40, help="IBKR client ID (default: 40)")
    parser.add_argument(
        "--fetch-run-id",
        default=None,
        help=(
            "Label every D1 request of this invocation with this id instead of a new one, so "
            "the caller (the nightly) can name the run it asks split detection to judge."
        ),
    )
    parser.add_argument(
        "--overlap-sessions",
        type=int,
        default=0,
        help=(
            "1d only: also re-ask the last N sessions D1 already answers, so a fresh "
            "observation overlaps an earlier one and a split shows as a constant price "
            "ratio (plan 185-22, D-21). The nightly passes APR "
            "infra.bar_derivation.overlap_sessions; 0 (default) asks gaps only."
        ),
    )
    parser.add_argument(
        "--lease-tier",
        choices=("bulk", "priority"),
        default="bulk",
        help=(
            "ibkr_history_stream lease tier (D-29). bulk (the default, the todo 449 "
            "chain and manual fetches) yields to any waiter at (symbol, tf) unit "
            "boundaries; priority (the nightly, phase 185 campaigns) yields only to "
            "another priority waiter."
        ),
    )
    parser.add_argument(
        "--lease-wait-minutes",
        type=float,
        default=None,
        help=(
            "Bound the initial lease acquire at this many minutes (the nightly passes "
            "infra.ibkr_history_lease.nightly_wait_minutes). Default: unbounded for "
            "bulk, the APR priority_wait_minutes seed for priority. Exit code "
            f"{EXIT_LEASE_TIMEOUT} on timeout."
        ),
    )
    parser.add_argument(
        "--dimension",
        default="compute",
        choices=("backfill", "compute", "compute_1d", "live"),
        help=(
            "get_active_contracts() dimension used to select non-futures instruments "
            "(default: compute). Use 'backfill' to include is_active=true symbols that are "
            "not yet compute_eligible, e.g. a symbol just onboarded via onboard_instrument(); "
            "'backfill' and 'compute_1d' also require an explicit --timeframes, normally "
            "the APR compute stack (feature.factory.target_timeframes: 5m,15m,1h,1d at "
            "the time of writing) or 1d for a 1d-only cohort."
        ),
    )
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

    if args.timeframes is None:
        if args.dimension in _DIMENSIONS_REQUIRING_EXPLICIT_TIMEFRAMES:
            parser.error(
                f"--dimension {args.dimension} requires an explicit --timeframes: it includes "
                "symbols deliberately kept off the full timeframe stack (e.g. the 1d-only "
                "D-09 cohort), and the default would fetch every timeframe for them."
            )
        args.timeframes = _DEFAULT_TIMEFRAMES
    timeframes = [t.strip() for t in args.timeframes.split(",") if t.strip()]

    # Filter contracts
    if getattr(args, "include_rolled", False):
        # All futures (rolled + front-month) + non-futures from get_active_contracts
        all_futures = get_all_futures_contracts(settings)
        active = get_active_contracts(settings, dimension=args.dimension)
        futures_symbols = {c.symbol for c in all_futures}
        non_futures = [c for c in active if c.symbol not in futures_symbols]
        contracts = all_futures + non_futures
    else:
        contracts = get_active_contracts(settings, dimension=args.dimension)
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
    _load_ibkr_retry_config(settings)
    _load_ibkr_venue_fallback_config(settings)
    _load_ibkr_rate_limit_config(settings)
    _load_ohlcv_insert_batch_size_config(settings)
    _load_gap_cluster_max_days_config(settings)

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

    # Provider-verified empty history (migration 354): loaded once per run. A fresh range is
    # subtracted from the detected gaps; a stale one is re-verified by fetching it.
    empty_ranges = empty_history.load(db_conn, _EMPTY_HISTORY_PROVIDER)
    empty_reverify_days = empty_history.load_reverify_days(db_conn)
    run_started_at = datetime.now(UTC)

    fresh_heads = empty_history.load_fresh_heads(
        db_conn, _EMPTY_HISTORY_PROVIDER, empty_reverify_days
    )
    first_bars = empty_history.load_first_bars(db_conn, [c.symbol for c in contracts])
    n_head_floored = 0
    n_empty_history_skipped = 0

    def _finish(status: str, message: str, exit_code: int | None) -> None:
        print(message)
        JOB_COMPLETED_TOTAL.add(1, {"job": "historical-backfill", "status": status})
        db_conn.close()
        flush_and_shutdown_metrics()
        if exit_code is not None:
            sys.exit(exit_code)

    # D-29: one IBKR history stream per account. This process (the one that
    # talks to IBKR, never an orchestrating parent) holds the lease before its
    # first request and checkpoints it after every completed (symbol, tf) unit.
    try:
        lease = _acquire_history_lease(settings, args)
    except LeaseTimeout as error:
        _finish(
            "failed_lease_timeout",
            f"Backfill FAILED — could not acquire the {IBKR_HISTORY_LEASE} lease "
            f"within its wait bound: {error}",
            EXIT_LEASE_TIMEOUT,
        )
        return

    # D-05/D-16 capture: one fetch_run_id per invocation, one dedicated
    # connection for D1 so a capture failure never leaves a half-committed
    # market_data_ohlcv write behind it.
    fetch_run_id = args.fetch_run_id or new_fetch_run_id()
    sink_conn = connect_db(settings)
    sink = ObservationSink(
        sink_conn,
        caller=_OBSERVATION_CALLER,
        max_buffer_rows=_load_observation_batch_rows(settings),
    )
    print(f"  fetch_run_id: {fetch_run_id} (lease tier {args.lease_tier})")

    async def _run_fetch_stage() -> tuple[int, int, list[str], dict[str, datetime]]:
        nonlocal db_conn, n_head_floored, n_empty_history_skipped
        provider = IBKRProvider(
            host=settings.ib_host,
            port=settings.ib_port,
            client_id=args.client_id,
        )
        if not await provider.connect():
            print("Cannot connect to TWS — aborting fetch stage")
            return -1, 0, [], {}

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
        # Task 1b: symbols whose 1d windows were asked this run, with the 1d
        # fetch start per symbol. The daily derivation stage runs over these
        # after a clean fetch, and fetch_complete is marked per symbol only
        # once the stage wrote its rows.
        touched_1d: dict[str, datetime] = {}
        # Symbols whose oldest 1d window was asked this run: their ohlcv_empty_history row
        # is reconciled from the recorded answers once D1 holds them (plan 185-19, D-20).
        reconcile_1d: set[str] = set()
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
                            lease.checkpoint()
                        continue  # Skip the standard continuous fetch loop

                    # Head floor (migration 355): nothing exists before the provider's
                    # earliest data point, so no timeframe's gap search starts earlier. Looked
                    # up once per symbol, only when its stored history does not already reach
                    # the deepest requested start; a failed lookup means no floor this run
                    # and is retried next run, never stored.
                    # Not for futures: the head is the named front-month contract's, while
                    # their long timeframes are fetched from the continuous contract, whose
                    # history reaches years further back.
                    is_futures = instrument.asset_class == AssetClass.FUTURES
                    head_ts = None if is_futures else fresh_heads.get(instrument.symbol)
                    depth_days = {
                        t: (
                            min(tf_fetch_config[t][0], args.days)
                            if args.days
                            else tf_fetch_config[t][0]
                        )
                        for t in fetch_tfs
                    }
                    deepest_days = max(depth_days.values())
                    first_bar = first_bars.get(instrument.symbol)
                    # A floor saves requests only when some timeframe needs more than one
                    # chunk. Where every timeframe is one request (1d: 20 years in one), the
                    # lookup would cost a request and save none.
                    single_request = all(
                        depth_days[t] <= ibkr._MAX_CHUNK_DAYS.get(t, 0) for t in fetch_tfs
                    )
                    if (
                        not is_futures
                        and not single_request
                        and head_ts is None
                        and (first_bar is None or first_bar > end_dt - timedelta(days=deepest_days))
                    ):
                        head_ts, head_error = await provider.get_head_timestamp(instrument.symbol)
                        if head_ts is not None:
                            empty_history.record_head(
                                db_conn, instrument.symbol, _EMPTY_HISTORY_PROVIDER, head_ts
                            )
                            fresh_heads[instrument.symbol] = head_ts
                        else:
                            print(
                                f"  {instrument.symbol}: no provider head this run "
                                f"({head_error}); no floor applied"
                            )

                    # Standard mode: use continuous contract for longer timeframes
                    fetched_tfs: set[str] = set()  # TFs that got bars from IBKR directly
                    for tf in fetch_tfs:
                        fetch_days, use_continuous = tf_fetch_config[tf]
                        if args.days:
                            fetch_days = min(fetch_days, args.days)

                        start_dt = _fetch_start(end_dt, fetch_days)
                        # Snapped to midnight UTC: the head is the first trade's time (e.g.
                        # 13:30), while a 1d bar is stamped 00:00 and an intraday bucket may
                        # start before it -- clamping to the raw head would skip the listing
                        # day's own bars forever. Flooring to the date skips less, never more.
                        head_floor = (
                            head_ts.replace(hour=0, minute=0, second=0, microsecond=0)
                            if head_ts is not None
                            else None
                        )
                        if head_floor is not None and head_floor > start_dt:
                            start_dt = head_floor
                            n_head_floored += 1
                        interval = timedelta(minutes=_TF_MINUTES[tf])
                        # Plan 12: 15m/1h persist into the archive through its
                        # single-writer module; real bars only is forced for them
                        # (no synthetic fill is ever produced for an archive tf).
                        archive_tf = tf in _ARCHIVE_TFS
                        write_rows = _insert_archive_rows if archive_tf else None
                        real_bars_only = real_bars_only_for(tf)
                        # Task 1b: 1d answers are D1 captures (no bar store, no
                        # fetch-complete mark; the daily derivation stage owns
                        # both). Every 1d special case below derives from this
                        # one property, like archive_tf and real_bars_only.
                        d1_capture = tf == "1d"
                        empty = empty_ranges.get((instrument.symbol, tf))

                        def _note_empty_skip(
                            skipped: Any,
                            _symbol: str = instrument.symbol,
                            _tf: str = tf,
                        ) -> None:
                            nonlocal n_empty_history_skipped
                            n_empty_history_skipped += 1
                            print(
                                f"  {_symbol}/{_tf}: skipping provider-verified "
                                f"empty history {skipped.empty_from.date()} to "
                                f"{skipped.empty_through.date()} (verified "
                                f"{skipped.verified_at.date()})"
                            )

                        if d1_capture:
                            # 1d planning is defined on the NYSE session grid
                            # (sessions.py has one calendar). A non-NYSE name
                            # here would get NYSE- holidays planned as gaps --
                            # permanent silent holes -- so refuse loudly until
                            # a second calendar exists (asset_agnostic: the
                            # calendar is data dispatched by session_id, and
                            # today the dispatch table has exactly one row).
                            if getattr(instrument, "session_id", "nyse") != "nyse":
                                raise ValueError(
                                    f"1d gap planning is NYSE-only; {instrument.symbol} "
                                    f"has session_id={instrument.session_id!r}"
                                )
                            # Plan 185-18 task 1b: 1d asks come from D1 -- session
                            # dates with neither a TRADES observation nor a covering
                            # definitive no_data window -- through the same plan_gaps
                            # rule every other timeframe uses. The wrapper returns
                            # end-exclusive (date, date) ranges; widened here to
                            # midnight-UTC datetimes so the window loop, the
                            # clustering and the provider call stay timeframe-
                            # agnostic. Nothing from these fetches is stored: the
                            # answers are D1 rows, and the daily derivation stage
                            # (chained after a clean run) writes the grid rows.
                            gaps_d = detect_gaps_1d_from_d1(
                                db_conn,
                                instrument.symbol,
                                start_dt.date(),
                                end_dt.date(),
                                nyse_sessions(start_dt.date(), end_dt.date()),
                                empty=empty,
                                now=run_started_at,
                                reverify_days=empty_reverify_days,
                                min_confirmations=ibkr._NO_DATA_CONFIRMATION_CHUNKS,
                                on_skip=_note_empty_skip,
                            )
                            if args.overlap_sessions > 0:
                                # Sessions back from end, with calendar slack for
                                # weekends and holidays (about 1.6 calendar days each).
                                overlap_days = int(args.overlap_sessions * 1.6) + 10
                                gaps_d = with_overlap_window(
                                    gaps_d,
                                    nyse_sessions(
                                        end_dt.date() - timedelta(days=overlap_days),
                                        end_dt.date(),
                                    ),
                                    end_dt.date(),
                                    args.overlap_sessions,
                                )
                            gaps = [(midnight_utc(s), midnight_utc(e)) for s, e in gaps_d]
                        elif tf in _RECORD_PLAN_TFS:
                            # Plan 185-18: the shared planner decides the asks --
                            # expected slots minus stored observations minus
                            # recorded coverage, with the provider-verified empty
                            # span folded in under the same freshness gate the
                            # legacy path applies.
                            gaps = detect_gaps_from_record(
                                db_conn,
                                instrument.symbol,
                                tf,
                                start_dt,
                                end_dt,
                                expected_grid_slots(
                                    instrument.session_id,
                                    instrument.exchange,
                                    tf,
                                    start_dt,
                                    end_dt,
                                ),
                                empty=empty,
                                now=run_started_at,
                                reverify_days=empty_reverify_days,
                                min_confirmations=ibkr._NO_DATA_CONFIRMATION_CHUNKS,
                                on_skip=_note_empty_skip,
                            )
                        else:
                            gaps = detect_gaps(
                                db_conn,
                                instrument.symbol,
                                tf,
                                start_dt,
                                end_dt,
                                session_id=instrument.session_id,
                                exchange=instrument.exchange,
                                answered=(
                                    # 1m is real bars only (todo 462): its answered
                                    # windows are the only thing standing between a
                                    # definitive no_data span and re-asking it forever.
                                    load_answered_windows(db_conn, instrument.symbol, tf)
                                    if real_bars_only
                                    else None
                                ),
                            )
                            kept = empty_history.apply_empty_range(
                                gaps,
                                empty,
                                run_started_at,
                                empty_reverify_days,
                                interval,
                                ibkr._NO_DATA_CONFIRMATION_CHUNKS,
                            )
                            if kept != gaps:
                                _note_empty_skip(empty)
                            gaps = kept
                        if not gaps:
                            print(f"  {instrument.symbol}/{tf}: no gaps found.")
                            fetched_tfs.add(tf)
                            lease.checkpoint()
                            continue

                        # Cluster nearby gap ranges into fetch windows instead of one
                        # min/max-bounded request for the whole run — a permanent
                        # pre-listing void (recent IPO/spin-off/relisting) sitting next
                        # to an unrelated small gap elsewhere must not force a single
                        # request re-covering the already-complete data between them.
                        # See cluster_gap_ranges()'s docstring/comment for the AA case
                        # that surfaced this. Genuinely nearby gaps (the common case)
                        # still coalesce into one request, same as before.
                        windows = cluster_gap_ranges(gaps, max_gap_days=_GAP_CLUSTER_MAX_DAYS)
                        print(
                            f"  {instrument.symbol}/{tf}: {len(gaps)} gaps detected across "
                            f"{len(windows)} window(s)..."
                        )

                        # Skip continuous contracts for short windows (no rolls needed)
                        use_cont = (
                            use_continuous
                            and (fetch_days > 14)
                            and (instrument.asset_class == AssetClass.FUTURES)
                        )

                        # [rca_analysis 2026-07-05, F1/F2] Persist each chunk's real
                        # bars as soon as they arrive, in addition to the full-window
                        # normalize_bars()+store_bars() pass below. Without this, DB
                        # growth (and thus the external stall watchdog's heartbeat) only
                        # happens once per (symbol, tf), after the entire — potentially
                        # many-chunk, many-minute — fetch completes, and a kill mid-fetch
                        # discards all in-memory progress for that (symbol, tf). This
                        # writes raw real bars only (no synthetic fill, which needs the
                        # full window's prev_close carried across chunk boundaries — see
                        # normalize_bars). The ingress write contract in store_bars makes the
                        # later full-window pass re-affirming these rows a no-op (identical
                        # rows are classified unchanged and not written).
                        # Archive tfs record the request ids the provider reports,
                        # so each chunk's bars and its answer commit atomically
                        # (todo 462): the record fires before on_chunk, so by the
                        # time _persist_chunk runs its ids are all captured.
                        window_request_ids: list[Any] = []
                        capture_kwargs = _capture_kwargs(tf, sink, fetch_run_id)
                        # Plan 185-18: 5m joins the archive timeframes on the atomic
                        # request-and-bars persist -- its rows land in the canonical
                        # grid through the pipeline's own market_data_ohlcv insert,
                        # so a recorded 5m answer never outruns its stored rows
                        # either (todo 462).
                        atomic_chunk_tf = archive_tf or tf == "5m"
                        if atomic_chunk_tf:
                            base_on_request = capture_kwargs["on_request"]

                            def _recording_on_request(
                                record: Any,
                                _base: Any = base_on_request,
                                _ids: list[Any] = window_request_ids,
                            ) -> None:
                                _base(record)
                                _ids.append(record.request_id)

                            capture_kwargs["on_request"] = _recording_on_request

                        async def _persist_chunk(
                            chunk_bars: list,
                            _tf: str = tf,
                            _symbol: str = instrument.symbol,
                            _atomic: bool = atomic_chunk_tf,
                            _archive: bool = archive_tf,
                            _request_ids: list[Any] = window_request_ids,
                        ) -> None:
                            nonlocal db_conn
                            if not chunk_bars:
                                return
                            try:
                                db_conn.cursor().execute("SELECT 1")
                            except Exception:
                                try:
                                    db_conn.close()
                                except Exception:
                                    pass
                                db_conn = connect_db(settings)
                            if _atomic:
                                # One transaction for the answer and its bars: a
                                # recorded request never outruns its stored rows.
                                request_rows = sink.take_requests(list(_request_ids))
                                _request_ids.clear()
                                if _archive:
                                    archive_rows = [
                                        (
                                            b.timestamp,
                                            _symbol,
                                            _tf,
                                            b.open,
                                            b.high,
                                            b.low,
                                            b.close,
                                            b.volume,
                                            b.source,
                                            None,
                                        )
                                        for b in chunk_bars
                                    ]
                                    persist_chunk_atomically(
                                        db_conn,
                                        request_rows=request_rows,
                                        archive_rows=archive_rows,
                                        write_archive_rows=_insert_archive_rows,
                                    )
                                    return
                                grid_rows = [
                                    (
                                        b.timestamp,
                                        _symbol,
                                        _tf,
                                        b.open,
                                        b.high,
                                        b.low,
                                        b.close,
                                        b.volume,
                                        b.source,
                                    )
                                    for b in chunk_bars
                                ]
                                persist_chunk_atomically(
                                    db_conn,
                                    request_rows=request_rows,
                                    archive_rows=grid_rows,
                                    write_archive_rows=_insert_market_data_rows,
                                )
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
                            store_bars(db_conn, chunk_dicts, _symbol, _tf)

                        # Fetch each cluster's window separately — the provider still
                        # chunks each one at _MAX_CHUNK_DAYS[tf] internally with 10s
                        # between chunks. The ingress write contract makes every window
                        # idempotent regardless of cluster boundaries.
                        #
                        # tf_window_failed tracks whether ANY window for this tf raised.
                        # Before gap-range clustering there was always exactly one window
                        # per (symbol, tf), so a single fetched_tfs.add(tf) on success was
                        # correct. Now multiple windows can exist per tf, and one window's
                        # success must not mask another window's failure -- if any window
                        # errors, the tf still has a real unfilled gap and must stay (or
                        # become) a candidate for the FX/crypto 1m-derivation fallback below.
                        tf_window_failed = False
                        for gap_start, gap_end in windows:
                            # Only the oldest window can be pre-history; its walk's ending in
                            # definitive no-data answers is what ohlcv_empty_history records.
                            observed: list[EmptyHistory] = []
                            is_oldest_window = (gap_start, gap_end) == windows[0]
                            # A legacy (inclusive) gap range ends at its last missing
                            # slot's START, but a request ending there returns bars
                            # that finish by then, so that slot's bar is never asked
                            # for (and a one-slot gap issues no request at all).
                            # 1m keeps the extension through the slot's end, capped
                            # at now so a bar still forming stays a gap. The record
                            # planner's windows (5m/15m/1h) are already end-exclusive:
                            # gap_end IS the last missing slot's end, asked for as-is.
                            fetch_end = min(gap_end + interval, end_dt) if tf == "1m" else gap_end
                            try:
                                ohlcv_bars = await provider.fetch_historical_bars(
                                    symbol=instrument.symbol,
                                    timeframe=tf,
                                    start=gap_start,
                                    end=fetch_end,
                                    continuous=use_cont,
                                    # Task 1b: a 1d fetch persists nothing per chunk
                                    # -- its answers are D1 rows (requests recorded,
                                    # observations delivered); every other timeframe
                                    # keeps its atomic (or store) chunk persist.
                                    on_chunk=None if d1_capture else _persist_chunk,
                                    on_empty_history=observed.append if is_oldest_window else None,
                                    **capture_kwargs,
                                )
                                # A chunk that failed every retry does not raise; the
                                # window is incomplete all the same.
                                if getattr(provider, "last_fetch_failed_chunks", 0):
                                    tf_window_failed = True
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
                                if d1_capture:
                                    # Task 1b: D1-only. The provider delivered the
                                    # answers as recorded requests and observations;
                                    # no bar is stored here -- the daily derivation
                                    # stage owns the 1d grid rows. Count the bars so
                                    # the run summary still reflects what arrived.
                                    total_bars += len(bar_dicts)
                                    if bar_dicts:
                                        fetched_tfs.add(tf)
                                        # Only a window that delivered bars owes a
                                        # derivation pass: an all-no_data symbol
                                        # has no observations to derive (and the
                                        # changed-since probe agrees it is not
                                        # due), so routing it into --symbols
                                        # would pay a full derive for nothing.
                                        touched_1d[instrument.symbol] = start_dt
                                    print(
                                        f"  {instrument.symbol}/1d: {len(bar_dicts)} bars "
                                        f"captured to D1 (window {gap_start.date()} to "
                                        f"{gap_end.date()}; grid rows owned by the daily "
                                        f"derivation stage)"
                                    )
                                else:
                                    try:
                                        db_conn.cursor().execute("SELECT 1")
                                    except Exception:
                                        try:
                                            db_conn.close()
                                        except Exception:
                                            pass
                                        db_conn = connect_db(settings)
                                    n = store_bars(
                                        db_conn,
                                        bar_dicts,
                                        instrument.symbol,
                                        tf,
                                        write_rows=write_rows,
                                    )
                                    total_bars += n
                                    if n > 0:
                                        fetched_tfs.add(tf)
                                    print(
                                        f"  {instrument.symbol}/{tf}: stored {n} bars "
                                        f"(window {gap_start.date()} to {gap_end.date()})"
                                    )
                                if is_oldest_window and not use_cont:
                                    if d1_capture:
                                        # D4 is a derived fact: the answers are D1 rows
                                        # after the flush, so the 1d row is reconciled
                                        # from ohlcv_request, not the in-memory walk.
                                        reconcile_1d.add(instrument.symbol)
                                    else:
                                        empty_history.reconcile(
                                            db_conn,
                                            instrument.symbol,
                                            tf,
                                            _EMPTY_HISTORY_PROVIDER,
                                            (gap_start, gap_end),
                                            observed[-1] if observed else None,
                                            empty,
                                            # chunk boundaries sit a day apart
                                            timedelta(days=1) + interval,
                                        )
                            except Exception as e:
                                fetch_errors += 1
                                tf_window_failed = True
                                print(
                                    f"  {instrument.symbol}/{tf} "
                                    f"[{gap_start.date()}-{gap_end.date()}]: fetch error — {e}"
                                )
                        if tf_window_failed:
                            fetched_tfs.discard(tf)
                        elif not d1_capture:
                            mark_fetch_complete(db_conn, instrument.symbol, tf, start_dt)
                        # 1d marks after the daily derivation stage wrote its rows:
                        # the EXISTS guard reads market_data_ohlcv_tradeable, which
                        # this run populates only through the stage (task 1b).
                        lease.checkpoint()

                    # FX and crypto: fetch deeper 1m window and derive any TFs
                    # that IBKR didn't return bars for in the named fetch above.
                    # 1d left this fallback in task 1b: the daily grid rows are
                    # the derivation's (store_bars refuses 1d), reached through
                    # D1 and the daily stage like every other asset class.
                    if instrument.asset_class in (AssetClass.FX, AssetClass.CRYPTO):
                        missing_tfs = [tf for tf in ("5m", "15m", "1h") if tf not in fetched_tfs]
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
                                # 1m is real bars only (todo 462, plan 185-18): the
                                # deep window's real bars are stored as returned --
                                # no synthetic fill reaches market_data_ohlcv at 1m
                                # from here either.
                                n = store_bars(db_conn, deep_dicts, instrument.symbol, "1m")
                                print(f"  {instrument.symbol}/1m (deep {deep_days}d): {n} bars")
                            except Exception as e:
                                fetch_errors += 1
                                print(f"  {instrument.symbol}/1m deep fetch error — {e}")
                            bars_1m = fetch_bars(db_conn, instrument.symbol, "1m")
                            if bars_1m:
                                for derived_tf in missing_tfs:
                                    aggregated = aggregate_bars_from_1m(bars_1m, derived_tf)
                                    n = store_bars(
                                        db_conn,
                                        aggregated,
                                        instrument.symbol,
                                        derived_tf,
                                        write_rows=(
                                            _insert_archive_rows
                                            if derived_tf in _ARCHIVE_TFS
                                            else None
                                        ),
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

                    # D1 flush once per symbol after its fetches return (D-05): a
                    # failure raises, the symbol fails loudly rather than dropping
                    # raw answers. One structlog line per symbol with the counts.
                    n_requests, n_observations = _flush_capture(sink, settings)
                    _logger.info(
                        "historical_pipeline.d1_captured",
                        symbol=instrument.symbol,
                        n_requests=n_requests,
                        n_observations=n_observations,
                    )
                    if n_requests or n_observations:
                        print(
                            f"  {instrument.symbol}: D1 capture {n_requests} request(s), "
                            f"{n_observations} observation(s)"
                        )
                    if instrument.symbol in reconcile_1d:
                        counts = empty_history.reconcile_empty_history(
                            db_conn, "1d", _EMPTY_HISTORY_PROVIDER, symbols=[instrument.symbol]
                        )
                        if any(counts.values()):
                            _logger.info(
                                "historical_pipeline.empty_history_reconciled",
                                symbol=instrument.symbol,
                                **counts,
                            )

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
        return total_bars, fetch_errors, skipped_symbols, touched_1d

    try:
        total_bars, fetch_errors, skipped_symbols, touched_1d = asyncio.run(_run_fetch_stage())
        if total_bars == -1:
            # IBKR connect failed before any fetch was attempted. A bare `return` here
            # exits 0 (main() is called plainly, not via sys.exit(main())) -- the nightly
            # wrapper and backfill_retry_loop.sh both read that as success even though
            # zero bars were fetched. Found 2026-08-10: the nightly timer fired at
            # 02:00 UTC, still inside the ~4-4.5hr post-restart IBKR outage window, and
            # got logged as "nightly_backfill.success".
            _finish("failed", "Backfill FAILED — could not connect to IBKR. See error above.", 1)
            return

        n_requested = len(contracts)
        n_skipped = len(skipped_symbols)
        print(
            f"\nStage 1 complete: {total_bars:,} total bars stored, {fetch_errors} fetch error(s)\n"
        )
        print(
            f"  Provider head floor applied to {n_head_floored} symbol/tf(s); provider-verified "
            f"empty history skipped for {n_empty_history_skipped}\n"
        )
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
            _finish(
                "partial",
                f"Backfill FINISHED WITH {fetch_errors} FETCH ERROR(S) — "
                "not declaring complete. See error lines above.",
                1,
            )
            return

        if touched_1d:
            # Task 1b: the 1d answers above went to D1 only. The daily derivation
            # stage writes the 1d grid rows for exactly the symbols whose windows
            # were asked; a failure here fails the run loudly (exit 1) so a silent
            # skip can never declare "complete" with no 1d rows. fetch_complete is
            # marked per symbol only after the stage succeeded -- the EXISTS guard
            # reads the rows the stage just wrote.
            daily_symbols = sorted(touched_1d)
            print(f"\nStage 2: daily derivation stage for {len(daily_symbols)} symbol(s)")
            if _run_daily_stage(daily_symbols) != 0:
                _finish(
                    "failed",
                    "Backfill FAILED: the daily derivation stage failed, so no 1d rows "
                    "were written for this run's fetches. See its output above.",
                    1,
                )
                return
            for symbol in daily_symbols:
                mark_fetch_complete(db_conn, symbol, "1d", touched_1d[symbol])

        _finish("success", "\nBackfill complete.", None)
    except LeaseTimeout as error:
        # A checkpoint re-acquire (yielding to a waiter) can also time out.
        _finish(
            "failed_lease_timeout",
            f"Backfill FAILED — lost the {IBKR_HISTORY_LEASE} lease and could not "
            f"re-acquire it within its wait bound: {error}",
            EXIT_LEASE_TIMEOUT,
        )
        return
    finally:
        # Best effort: a symbol that died mid-fetch may have left buffered rows.
        # Flushes are otherwise exactly once per symbol (D-05); this one only
        # fires when pending rows exist.
        if sink.pending():
            try:
                _flush_capture(sink, settings)
            except Exception as error:  # noqa: BLE001 - never mask the primary failure
                print(f"  (final D1 flush failed: {error})")
        lease.release()
        lease.close()
        sink_conn.close()


if __name__ == "__main__":
    try:
        init_otel_providers("historical-backfill")
    except OTelInitError as error:
        print(f"[warn] OTel init failed — metrics disabled: {error}")
    main()
