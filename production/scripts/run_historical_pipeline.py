#!/usr/bin/env python3
"""
Historical Backfill Pipeline

Version: 1.4
Status: current
Last Updated: 2026-06-06

Stage 1 (--fetch-only): Fetches multi-timeframe OHLCV bars from IBKR and stores
them in market_data_ohlcv. Short timeframes use named contracts; longer timeframes
use back-adjusted continuous contracts (ContFuture + ADJUSTED_LAST) to span rolls.

    Timeframe  Default depth  Notes
    1m         14 days        Named contract, no rolls
    5m         90 days        Named contract (chunked, IBKR limit)
    15m        180 days       Continuous adjusted (default) or per-contract (--per-contract)
    1h         365 days       Continuous adjusted (default) or per-contract (--per-contract)
    1d         2555 days      Continuous adjusted (default) or per-contract (--per-contract)

    Use --days N to cap ALL timeframes at N days (e.g. --days 2 for a gap-fill).

Stage 2 (--replay-only): Reads each timeframe's native stored bars and replays
them through the full I1→I2→I3→I4→I5→SMC→I6→I7 pipeline to populate
signal_events + trade_frames and intelligence_features.

Replaces: production/scripts/simple_seeder.py (retired)

Usage:
    python production/scripts/run_historical_pipeline.py
    python production/scripts/run_historical_pipeline.py --fetch-only
    python production/scripts/run_historical_pipeline.py --replay-only
    python production/scripts/run_historical_pipeline.py --symbols ESH6,NQH6

    # Per-contract mode (Renaissance-style raw data storage):
    python production/scripts/run_historical_pipeline.py --fetch-only --per-contract --symbols ESH6

    # Gap-fill: fetch last 2 days across ALL TFs (not just 1m), then replay only those 2 days:
    python production/scripts/run_historical_pipeline.py --fetch-only --symbols EURUSD,BTCUSD --days 2
    python production/scripts/run_historical_pipeline.py --replay-only --symbols EURUSD,BTCUSD --days 2

    python production/scripts/run_historical_pipeline.py --replay-only --clean  # delete old signals

--days behaviour:
    When provided, caps ALL timeframe fetch depths at that value (not just 1m).
    Also limits the replay stage to bars within that window.
    Omit --days for full-history replay or default per-TF fetch depths.

--per-contract mode:
    Fetches each individual futures contract in the roll chain instead of back-adjusted
    continuous series. Data is stored under the correct contract symbol (e.g., ESH6, ESZ5).
    This is the Renaissance-standard approach: raw per-contract data is canonical truth,
    continuous series are derived layers.
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import json
import math
import sys
import time
import uuid
from collections import defaultdict, deque
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, NamedTuple

import psycopg2
import psycopg2.extras
import structlog

# Set up sys.path BEFORE importing from src
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd

from src.config.contracts import MONTH_CODE_TO_NUM, derive_roll_chain
from src.config.settings import Settings, get_active_contracts, get_all_futures_contracts
from src.core.bar_normalizer import (
    SOURCE_DERIVED_1M,
    SOURCE_SYNTHETIC_FILL,
    generate_session_slots,
    normalize_bars,
)
from src.core.database_manager import DatabaseManager
from src.core.models import AssetClass, ContractMetadata, Instrument
from src.core.service_utils import TF_SECONDS, min_bars_for_tf
from src.core.service_utils import bar_close_ts as compute_bar_close_ts
from src.intelligence.pipeline.seed_constants import (
    _I3_NUMERIC_KEYS as _SEED_NUMERIC_KEYS,
)
from src.intelligence.pipeline.seed_constants import (
    _I3_SEED_COLS as _SEED_COLS,
)
from src.intelligence.pipeline.seed_constants import (
    _I3_SEED_QUERY_PG as _SEED_QUERY_PG,
)
from src.intelligence.pipeline.signal_processor import annotate_signal_with_context
from src.intelligence.plugins import registry
from src.intelligence.plugins.mixins import incremental_compute
from src.intelligence.register_plugins import register_all_plugins
from src.intelligence.schemas import FEATURE_SCHEMA_VERSION
from src.intelligence.setup_performance_updater import _compute_perf_multipliers
from src.intelligence.trading.aggregator import AggregatedResult, aggregate
from src.intelligence.trading.signal_schema import SIGNAL_SCHEMA_VERSION, make_signal_id
from src.observability.metrics import flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers
from src.persistence.repository.signal_events_repository import LedgerEntry
from src.providers import IBKRProvider

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


def _generate_contract_symbols(base: str, start_year: int, end_year: int) -> list[str]:
    """Generate all contract symbols for a base symbol between years.

    Returns list in chronological order (oldest first).
    Only generates quarterly contracts (H, M, U, Z) for major index futures.

    Args:
        base: Base symbol (e.g., "ES", "NQ", "CL")
        start_year: Starting year (e.g., 2019)
        end_year: Ending year (e.g., 2026)
    """
    contracts = []
    for year in range(start_year, end_year + 1):
        for month_code in ["H", "M", "U", "Z"]:  # Quarterly cycle
            symbol = f"{base}{month_code}{year % 100}"  # "ESH6" for 2026
            contracts.append(symbol)
    return contracts


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
        # Not a futures contract symbol, skip per-contract logic
        return (0, [])

    base, current_month, current_year = parsed

    # Determine start year based on fetch_days (rough approximation)
    # 2555 days = 7 years, so go back to 2019 for full backfill
    start_year = current_year - (fetch_days // 365)

    # Generate contract chain for this base symbol
    contract_symbols = _generate_contract_symbols(base, start_year, current_year)

    # Filter to only include contracts within our fetch window
    # Also include current contract even if outside window (for continuity)
    metadata_list: list[ContractMetadata] = []

    total_bars = 0

    # For each contract, try to qualify and fetch
    for i, contract_sym in enumerate(contract_symbols):
        # Determine contract expiry from month code and year
        month_code = contract_sym[-2]
        year_digit = int(contract_sym[-1])
        contract_year = 2000 + year_digit

        # Simple expiry: 3rd Friday of expiry month (CME equity index futures)
        # This is an approximation - IBKR provides accurate expiry in contract details
        month_num = MONTH_CODE_TO_NUM[month_code]
        # Find 3rd Friday of the month
        first_day = date(contract_year, month_num, 1)
        first_friday = (4 - first_day.weekday()) % 7 + 1
        expiry_date = datetime.combine(
            date(contract_year, month_num, first_friday + 7), datetime.min.time()
        ).replace(tzinfo=UTC)

        # Roll date: when this contract became active (previous contract expiry + 1 day)
        if i > 0:
            roll_date = expiry_date.replace(day=1)  # Approximate first of month
        else:
            roll_date = None  # Oldest contract in chain

        # Create Instrument for this contract
        contract_instrument = Instrument(
            symbol=contract_sym,
            name=f"{base} {month_num} {contract_year}",
            asset_class=AssetClass.FUTURES,
            exchange=instrument.exchange,
            session_id=instrument.session_id,
        )

        # Try to qualify the contract
        try:
            qualified = await provider.qualify_instrument(contract_instrument)
            if not qualified:
                print(f"    {contract_sym}: skip (qualify failed)")
                continue

            # Fetch bars for this contract
            start_dt = (end_dt - timedelta(days=fetch_days)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            ohlcv_bars = await provider.fetch_historical_bars(
                symbol=contract_sym,
                timeframe=timeframe,
                start=start_dt,
                end=end_dt,
                continuous=False,  # Always named contract for per-contract mode
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
                # Build roll chain links
                roll_from = contract_symbols[i - 1] if i > 0 else None
                roll_to = contract_symbols[i + 1] if i < len(contract_symbols) - 1 else None

                # Create metadata entry
                metadata = ContractMetadata(
                    symbol=contract_sym,
                    base_symbol=base,
                    asset_class=AssetClass.FUTURES,
                    expiry_date=expiry_date,
                    first_notice_date=None,  # Would need IBKR contract details
                    roll_from=roll_from,
                    roll_to=roll_to,
                    roll_date=roll_date,
                    roll_gap=None,  # Computed after both contracts fetched
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


# ---------------------------------------------------------------------------
# Plugin lists — sourced from register_plugins (single source of truth)
# ---------------------------------------------------------------------------
from src.intelligence.register_plugins import (
    TIER_I1,
    TIER_I2,
    TIER_I3,
    TIER_I4,
    TIER_I5,
    TIER_I6,
    TIER_I7,
    TIER_SMC,
)

I1_PLUGINS = TIER_I1
I2_PLUGINS = TIER_I2
I3_PLUGINS = TIER_I3
I4_PLUGINS = TIER_I4
I5_PLUGINS = TIER_I5
SMC_PLUGINS = TIER_SMC
I6_PLUGINS = TIER_I6
I7_PLUGINS = TIER_I7

DEFAULT_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]
# Larger than live service batch (50) — replay has no latency pressure and benefits from
# fewer commits over millions of bars.
_FEATURE_BATCH_SIZE = 2000

# Plugin error tracking — count failures per plugin name, emit on first occurrence.
# Never suppress silently: a crashing plugin produces missing features and garbage signals.
_plugin_error_counts: dict[str, int] = defaultdict(int)


def _log_plugin_error(name: str, symbol: str, tf: str, error: Exception) -> None:
    _plugin_error_counts[name] += 1
    if _plugin_error_counts[name] == 1:
        print(f"  [plugin error] {name} ({symbol}/{tf}): {error}")


# Per-plugin cumulative wall-clock seconds spent in incremental_compute across
# the whole replay. Proves the dispatch speedup and surfaces any remaining hot
# plugin. Aggregated via _accumulate_plugin_time; reported by _report_plugin_times.
_plugin_timings: dict[str, float] = defaultdict(float)


def _accumulate_plugin_time(name: str, t0: float) -> None:
    _plugin_timings[name] += time.perf_counter() - t0


def _report_plugin_times() -> None:
    if not _plugin_timings:
        return
    ranked = sorted(_plugin_timings.items(), key=lambda kv: kv[1], reverse=True)
    total = sum(_plugin_timings.values())
    print(f"  [plugin timing] total={total:.1f}s  top:")
    for name, secs in ranked[:12]:
        print(f"    {name:<36} {secs:7.2f}s ({100 * secs / total:5.1f}%)")


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
# Named contract for 1m (IBKR ~35d limit on front-month futures); continuous back-adjusted for rest.
_TF_FETCH_CONFIG: dict[str, tuple[int, bool]] = {
    # 1m: named contract (no roll crossings). 30d = ~1 calendar month = ~11,700 bars,
    #     capturing time-of-day, day-of-week, and monthly intraday patterns. Well within
    #     IBKR's ~35d named contract limit; 5 chunks at 6d each.
    "1m": (30, True),
    # 5m: Continuous back-adjusted. 90 days covers
    #     3 months of intraday + weekly regime cycles, yielding ~600+ signals — enough to
    #     populate all 51 regression cells with statistically meaningful outcomes.
    "5m": (90, True),
    # 15m: Continuous back-adjusted. 180 days = 6 months
    #     captures both weekly seasonality and monthly roll-driven regime shifts. Yields
    #     ~1,150+ signals, giving ~22 outcomes/cell — above the 20/cell minimum.
    "15m": (180, True),
    # 1h: the HMM/GARCH anchor TF. ~6.5 bars/day/symbol. 365 days = 1 full calendar year:
    #     captures seasonal cycles (Q1 earnings, summer lull, year-end), yields ~2,379 bars
    #     (4× the 500-bar HMM floor) and ~2,300+ signals for robust CIS calibration.
    #     use_continuous=False: same reason as 5m/15m — IBKR ContFuture + ADJUSTED_LAST
    #     requires endDateTime="" (no chunking possible), so a single 365D request times out
    #     on COMEX instruments. Chunked named-contract path (_MAX_CHUNK_DAYS=364) sends two
    #     requests (364d + 1d) — no roll adjustment, but data reliably lands for all exchanges.
    "1h": (365, False),
    # 4h: ~1.625 bars/day/symbol (equity RTH). 730 days (2yr) clears the 1000-real-bar floor
    #     (~1,186 bars) for reliable HMM/GARCH estimation across all session types.
    "4h": (730, True),
    # 1d: macro regime coverage. 1 bar/day/symbol. 2555 days = 7 years reaches back to 2019 —
    #     the last clean pre-distortion baseline before COVID, zero-rate era, QE infinity,
    #     2022 rate shock, and AI mania. Capturing these distinct macro regimes is essential
    #     for the HMM to learn what "normal" looks like and gate signals accordingly.
    #     Yields ~1,764 bars (3.5× HMM floor) and spans 5 full macro regime transitions.
    "1d": (2555, True),
}

# FX and crypto: IBKR *can* return higher-TF bars for major pairs (EURUSD, GBPUSD, etc.).
# The named fetch above attempts all TFs directly. This deep 1m window + derivation is
# a fallback for any TFs that IBKR didn't return bars for (e.g. exotic pairs, thin crypto).
#   FX (IDEALPRO/MIDPOINT): up to ~6 months of 1m available. 180d → ~1,300 derived 1h bars.
#   Crypto (PAXOS/AGGTRADES): Paxos data reliable for ~90d. 90d → ~2,160 derived 1h bars.
_1M_DAYS_FX: int = 180
_1M_DAYS_CRYPTO: int = 90


def run_i1_plugins(
    bar_history: deque,
    symbol: str,
    timeframe: str,
    plugin_states: dict[tuple[str, str, str], dict],
    df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Run all I1 indicator plugins on the current bar history.

    Returns empty dict if fewer than MIN_BARS are available (indicators
    need warmup history to produce meaningful values).

    Args:
        plugin_states: per-(name, symbol, tf) state dict; mutated in place to
            isolate stateful plugins (GARCH, HMM, Kalman) across symbols.
        df: pre-built DataFrame for bar_history; constructed here if not provided.
    """
    if len(bar_history) < min_bars_for_tf(timeframe):
        return {}

    if df is None:
        df = pd.DataFrame(list(bar_history))
    frames: dict[str, Any] = {"main": df, "features": {}}
    features: dict[str, Any] = {}

    for name in I1_PLUGINS:
        try:
            plugin = registry.get_indicator(name)
            state_key = (name, symbol, timeframe)
            state = plugin_states.setdefault(state_key, {})
            t0 = time.perf_counter()
            out = incremental_compute(plugin, frames, state)
            _accumulate_plugin_time(name, t0)
            # Persist seeded/updated state extracted from the result. compute_full
            # attaches a fresh _state (from _seed_state); compute_next attaches the
            # same mutated dict it received. This write-back is what makes the next
            # bar take the incremental branch -- mirrors executor._collect_plugin_results.
            plugin_states[state_key] = out.get("_state", state)
            if out:
                features.update(
                    {k: v for k, v in out.items() if isinstance(v, (int, float, str, bool))}
                )
                frames["features"] = features
        except Exception as error:
            _log_plugin_error(name, symbol, timeframe, error)

    return features


def run_analysis_pipeline(
    frames: dict[str, Any],
    intelligence_cache: dict[str, dict[str, Any]],
    symbol: str,
    timeframe: str,
    plugin_states: dict[tuple[str, str, str], dict],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Run I2 → I3 → I4 → I5 → SMC → I6 plugins in tier order.

    Mutates frames["features"] in-place (same as market_analysis_service).
    Caches result in intelligence_cache[symbol][timeframe] for I6 cross-TF plugin.

    Args:
        plugin_states: per-(name, symbol, tf) state dict; mutated in place to
            isolate stateful plugins (GARCH, HMM, Kalman) across symbols.

    Returns:
        Tuple of (merged intelligence dict, per-tier output dict).
    """
    features = dict(frames.get("features", {}))
    frames["features"] = features
    intelligence: dict[str, Any] = {}
    tiered: dict[str, dict[str, Any]] = {}

    tier_sequence = [
        (I2_PLUGINS, "I2"),
        (I3_PLUGINS, "I3"),
        (I4_PLUGINS, "I4"),
        (I5_PLUGINS, "I5"),
        (SMC_PLUGINS, "SMC"),
        (I6_PLUGINS, "I6"),
    ]

    for plugin_names, tier_label in tier_sequence:
        tier_key_lower = tier_label.lower()
        for name in plugin_names:
            try:
                plugin = registry.get_pattern(name)
                state_key = (name, symbol, timeframe)
                state = plugin_states.setdefault(state_key, {})
                t0 = time.perf_counter()
                out = incremental_compute(plugin, frames, state)
                _accumulate_plugin_time(name, t0)
                plugin_states[state_key] = out.get("_state", state)  # write-back is load-bearing
                if out:
                    # Strip private plugin keys (e.g. _state used by GARCH/HMM/Kalman
                    # for state carry-over) before updating the typed tiered dict.
                    # Pydantic schemas use extra="forbid", so _state causes ValidationError
                    # in _build_intelligence_event and silently kills feature production.
                    public_out = {k: v for k, v in out.items() if not k.startswith("_")}
                    intelligence.update(public_out)
                    tiered.setdefault(tier_key_lower, {}).update(public_out)
                    features.update(public_out)
                    frames["features"] = features
                    # Mirror live executor (executor.py:709): stamp each tier's output
                    # as frames[tier_key] so cross-tier plugins (e.g. I6 CTF) can read
                    # structured tier dicts rather than the flat merged features dict.
                    # Without this, frames["i3"] is None inside I6.compute_full() →
                    # cur_trend=0 → ctf_score=0.0 on every bar (A7 root cause).
                    frames[tier_key_lower] = tiered[tier_key_lower]
            except Exception as error:
                _log_plugin_error(name, symbol, timeframe, error)

    intelligence_cache.setdefault(symbol, {})[timeframe] = intelligence
    return intelligence, tiered


# ---------------------------------------------------------------------------
# Intelligence features — sync DB insert (mirrors feature_writer_service with %s placeholders)
# ---------------------------------------------------------------------------

_FEATURE_KEY_COLS = ("ts", "symbol", "tf")
_FEATURE_DATA_COLS = (
    "platform",
    "source",
    "schema_version",
    "bar",
    "technical_indicators",
    "pattern_detections",
    "regime_features",
    "confluence_scores",
    "smc",
    "cross_timeframe_context",
    "composite_events",
)


def _feature_insert_sql(overwrite: bool) -> str:
    cols = ", ".join(_FEATURE_KEY_COLS + _FEATURE_DATA_COLS)
    conflict = (
        "DO UPDATE SET " + ", ".join(f"{c} = EXCLUDED.{c}" for c in _FEATURE_DATA_COLS)
        if overwrite
        else "DO NOTHING"
    )
    return (
        f"INSERT INTO intelligence_features ({cols}) VALUES %s"
        f" ON CONFLICT (ts, symbol, tf) {conflict}"
    )


# Per-row template for execute_values — JSONB casts must be explicit per column.
_INSERT_FEATURE_SYNC_TEMPLATE = (
    "(%s, %s, %s, %s, %s, %s,"
    " %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb)"
)


def _build_intelligence_event(
    bar: dict,
    i1_features: dict,
    tiered: dict[str, dict],
    symbol: str,
    tf: str,
    ts: datetime,
) -> Any:
    """Build IntelligenceEvent from per-bar pipeline outputs.

    Returns None on any exception (never crashes the replay loop).
    source is always 'backfill'.

    Args:
        bar: dict with keys 'open', 'high', 'low', 'close', 'volume'
        i1_features: flat dict of I1 indicator outputs (extra='allow' model)
        tiered: per-tier output dict from run_analysis_pipeline — keys i2/i3/i4/i5/smc/i6
        symbol: contract symbol (e.g. 'ESH6')
        tf: timeframe string (e.g. '1m')
        ts: bar timestamp (timezone-aware datetime)
    """
    try:
        from src.intelligence.schemas import (
            I1Indicators,
            I2Events,
            I3Structure,
            I4Context,
            I5Patterns,
            I6Confluence,
            IntelligenceEvent,
            OHLCVBar,
            SMCContext,
        )

        return IntelligenceEvent(
            ts=ts,
            symbol=symbol,
            tf=tf,
            source="backfill",
            bar_close_ts=compute_bar_close_ts(ts, tf),  # always set; i1/computed_at left None
            bar=OHLCVBar(
                o=float(bar["open"]),
                h=float(bar["high"]),
                l=float(bar["low"]),
                c=float(bar["close"]),
                v=int(bar["volume"]),
            ),
            i1=I1Indicators(**i1_features),
            i2=I2Events(**tiered.get("i2", {})),
            i3=I3Structure(**tiered.get("i3", {})),
            i4=I4Context(**tiered.get("i4", {})),
            i5=I5Patterns(**tiered.get("i5", {})),
            smc=SMCContext(**tiered.get("smc", {})),
            i6=I6Confluence(**tiered.get("i6", {})),
        )
    except Exception as error:
        print(f"  [feature_build_error] {symbol}/{tf}@{ts}: {type(error).__name__}: {error}")
        return None


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively replace float NaN/Inf with None so json.dumps produces valid JSONB."""
    import math

    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    return obj


def _event_to_sync_params(event: Any) -> tuple:
    """Serialize IntelligenceEvent to a 14-element tuple for psycopg2 batch insert.

    Column order matches _FEATURE_KEY_COLS + _FEATURE_DATA_COLS:
      ts, symbol, tf, platform, source, schema_version,
      bar, technical_indicators, pattern_detections, regime_features,
      confluence_scores, smc, cross_timeframe_context, composite_events
    """
    return (
        event.ts,  # datetime — psycopg2 native
        event.symbol,
        event.tf,
        event.platform,
        event.source,
        event.schema_version,
        json.dumps(_sanitize_for_json(event.bar.model_dump())),  # bar
        json.dumps(_sanitize_for_json(event.i1.model_dump())),  # i1
        json.dumps(_sanitize_for_json(event.i5.model_dump(exclude_none=True))),  # i5
        json.dumps(_sanitize_for_json(event.i3.model_dump(exclude_none=True))),  # i3
        json.dumps(_sanitize_for_json(event.i4.model_dump(exclude_none=True))),  # i4
        json.dumps(_sanitize_for_json(event.smc.model_dump(exclude_none=True))),  # smc
        json.dumps(
            _sanitize_for_json(event.i6.model_dump(exclude_none=True))
        ),  # cross_timeframe_context
        json.dumps(_sanitize_for_json(event.i2.model_dump(exclude_none=True))),  # i2
    )


def _insert_features_sync(conn: Any, rows: list, overwrite: bool = False) -> None:
    """Synchronous psycopg2 batch insert into intelligence_features.

    Uses execute_values() (single multi-row INSERT) rather than execute_batch()
    (N separate statements) for ~3-5x throughput on large replay batches.

    Args:
        conn: psycopg2 connection
        rows: list of 14-element tuples from _event_to_sync_params()
        overwrite: if True, use DO UPDATE to replace stale rows with freshly
            computed values. Use when I1-I6 was recomputed from source bars.
            If False (default), DO NOTHING skips existing rows (gap-fill only).
    """
    if not rows:
        return
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur, _feature_insert_sql(overwrite), rows, template=_INSERT_FEATURE_SYNC_TEMPLATE
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Signal generation + sync DB insert
# ---------------------------------------------------------------------------

MARKET_CONTEXT_KEYS = (
    "trend_regime",
    "volatility_regime",
    "trend_confidence",
    "atr_14",
    "rsi_14",
    "ctf_score",
    "swing_pattern",
    "trend_strength",
    "volatility_percentile",
    "hmm_regime_state",
)

# uuid5 namespace for deterministic frame_id generation — same as migrate_signal_ledger.py
_FRAME_ID_NS = uuid.NAMESPACE_DNS


def _direction_text(direction_int: int) -> str:
    """Convert direction integer (1/-1) to text ('long'/'short') for signal_events."""
    return "long" if direction_int == 1 else "short"


def _make_frame_id(signal_id: str, entry_type: str) -> str:
    """Deterministic frame_id — same signal_id + entry_type always produces same UUID."""
    return str(uuid.uuid5(_FRAME_ID_NS, f"{signal_id}:{entry_type}"))


_INSERT_SIGNAL_EVENTS_SYNC_SQL = """
INSERT INTO signal_events (
    signal_id, ts, symbol, tf, setup_plugin, direction,
    raw_confidence, calibrated_confidence, cis_score, weights_version,
    factor_scores, context_features,
    ctf_score, ctf_confirmed, zone_friction_score,
    hmm_regime_at_fire, plugin_regime_type, garch_sigma_at_fire,
    is_shadow, is_backfill, status, signal_schema_version,
    ttl_bars, expires_at, signal_computed_at, feature_ts
) VALUES %s
ON CONFLICT (signal_id, ts) DO NOTHING
"""

_INSERT_SIGNAL_EVENTS_SYNC_TEMPLATE = (
    "(%s::uuid, %s, %s, %s, %s, %s,"
    " %s, %s, %s, %s,"
    " %s::jsonb, %s::jsonb,"
    " %s, %s, %s,"
    " %s, %s, %s,"
    " %s, TRUE, %s, %s,"
    " %s, %s, %s, %s)"
)

_INSERT_TRADE_FRAMES_SYNC_SQL = """
INSERT INTO trade_frames (
    frame_id, signal_id, signal_ts, entry_type, direction,
    entry_price, stop_price, target_price, r_multiple,
    ttl_bars, expires_at, counterfactual_pnl_r, was_selected, frame_details
) VALUES %s
ON CONFLICT (frame_id) DO NOTHING
"""

_INSERT_TRADE_FRAMES_SYNC_TEMPLATE = (
    "(%s::uuid, %s::uuid, %s, %s, %s," " %s, %s, %s, %s," " %s, %s, NULL, %s, %s::jsonb)"
)


def _build_ledger_entries(
    result: AggregatedResult,
    symbol: str,
    timeframe: str,
    timestamp: datetime,
    features: dict[str, Any],
    feature_ts: datetime | None = None,
    feature_tf: str | None = None,
    bar_history: Any = None,
) -> list[LedgerEntry]:
    """Convert an AggregatedResult into LedgerEntry objects for DB insertion.

    Args:
        result: aggregated I7 signals
        symbol: contract symbol
        timeframe: bar timeframe
        timestamp: bar timestamp
        features: merged feature dict for market_context extraction
        feature_ts: timestamp of the corresponding intelligence_features row (None if not written)
        feature_tf: timeframe of the corresponding intelligence_features row (None if not written)
        bar_history: rolling bar deque; close of last bar used as market_entry_price proxy
    """
    if not result.all_ranked:
        return []

    last_bar = bar_history[-1] if bar_history else None
    bar_close = float(last_bar["close"]) if last_bar else None
    tf_secs = TF_SECONDS.get(timeframe, 60)
    garch_sigma = features.get("garch_sigma")
    hmm_regime = features.get("hmm_regime")

    entries = []
    for sig in result.all_ranked:
        rank = sig.get("composite_rank", 99)
        was_selected = rank == 1 and result.selected_signal is not None

        ttl = sig.get("ttl_bars")
        expires_at = None
        if ttl is not None:
            try:
                expires_at = timestamp + timedelta(seconds=int(ttl) * tf_secs)
            except (OverflowError, TypeError, ValueError):
                expires_at = None

        setup_plugin = sig.get("setup_plugin", "unknown")
        direction = int(sig.get("direction", 0))
        if last_bar is not None:
            sid = make_signal_id(
                symbol=symbol,
                feature_ts_ns=int(timestamp.timestamp() * 1e9),
                feature_tf=timeframe,
                open_=float(last_bar["open"]),
                high=float(last_bar["high"]),
                low=float(last_bar["low"]),
                close=float(last_bar["close"]),
                volume=float(last_bar["volume"]),
                setup_plugin=setup_plugin,
                direction=direction,
            )
        else:
            # last_bar is None — malformed signal with no bar data; cannot generate deterministic ID
            _logger.warning(
                "Skipping signal with no bar data — cannot generate deterministic signal_id",
                symbol=symbol,
                timeframe=timeframe,
                setup_plugin=setup_plugin,
                timestamp=str(timestamp),
            )
            continue

        entries.append(
            LedgerEntry(
                signal_id=sid,
                timestamp=timestamp,
                symbol=symbol,
                timeframe=timeframe,
                setup_plugin=setup_plugin,
                signal_type=sig.get("signal_type", "unknown"),
                direction=direction,
                was_selected=was_selected,
                is_shadow=bool(sig.get("is_shadow", False)),
                is_backfill=True,
                feature_ts=feature_ts,
                feature_tf=feature_tf,
                hmm_regime_at_fire=(
                    sig.get("hmm_regime_at_fire") if "hmm_regime_at_fire" in sig else hmm_regime
                ),
                garch_sigma_at_fire=garch_sigma,
                ttl_bars=ttl,
                entry_price=float(sig.get("entry_price", 0.0)),
                stop_loss=float(sig.get("stop_loss", 0.0)),
                targets=[float(t) for t in sig.get("targets", [])],
                entry_zone_low=sig.get("zone_low"),
                entry_zone_high=sig.get("zone_high"),
                market_entry_price=bar_close,
                cis_score=(
                    sig.get("filtered_cis_score")
                    if sig.get("filtered_cis_score") is not None
                    else result.cis_score
                ),
                bucket_scores=result.bucket_scores,
                weights_version=result.weights_version,
                expires_at=expires_at,
                feature_schema_version=FEATURE_SCHEMA_VERSION,
                stop_basis=sig.get("stop_basis"),
                stop_type_col=sig.get("stop_type"),
                structural_stop_distance_atr=sig.get("structural_stop_distance_atr"),
                adaptive_buffer_mult=sig.get("adaptive_buffer_mult"),
                plugin_regime_type=sig.get("plugin_regime_type"),
                stop_structure_age_bars=sig.get("stop_structure_age_bars"),
                raw_confidence=sig.get("pre_quality_confidence") or sig.get("confidence"),
                calibrated_confidence=sig.get("calibrated_confidence"),
                context_features=sig.get("context_features"),
                ctf_score=sig.get("ctf_score"),
                ctf_confirmed=sig.get("ctf_confirmed"),
                zone_friction_score=sig.get("zone_friction_score"),
            )
        )
    return entries


def _insert_signals_sync(conn: Any, entries: list[LedgerEntry]) -> None:
    """Synchronous psycopg2 batch insert into signal_events + trade_frames (G0 grouping).

    G0: one signal_events row + one trade_frames row (entry_type='at_close') per signal.
    Direction converted from int (1/-1) to text ('long'/'short').
    frame_id is deterministic via uuid5 — idempotent across re-runs.
    Status starts as 'pending'; lifecycle_replay.py updates it.
    """
    if not entries:
        return

    se_params = []
    tf_params = []

    for e in entries:
        signal_id = str(e.signal_id)
        direction = _direction_text(
            int(e.direction) if isinstance(e.direction, (int, float)) else 1
        )
        raw_confidence = e.raw_confidence if e.raw_confidence is not None else 0.0

        # Build frame_details JSONB: stop architecture + zone fields archived here
        frame_details: dict = {}
        if e.stop_basis is not None:
            frame_details["stop_basis"] = e.stop_basis
        if e.stop_type_col is not None:
            frame_details["stop_type_col"] = e.stop_type_col
        if e.structural_stop_distance_atr is not None:
            frame_details["structural_stop_distance_atr"] = float(e.structural_stop_distance_atr)
        if e.adaptive_buffer_mult is not None:
            frame_details["adaptive_buffer_mult"] = float(e.adaptive_buffer_mult)
        if e.stop_structure_age_bars is not None:
            frame_details["stop_structure_age_bars"] = e.stop_structure_age_bars
        if e.entry_zone_low is not None:
            frame_details["entry_zone_low"] = float(e.entry_zone_low)
        if e.entry_zone_high is not None:
            frame_details["entry_zone_high"] = float(e.entry_zone_high)
        if e.market_entry_price is not None:
            frame_details["market_entry_price"] = float(e.market_entry_price)
        frame_details_json = json.dumps(frame_details) if frame_details else None

        # Extract first target for trade_frames.target_price
        targets = e.targets or []
        target_price = float(targets[0]) if targets else None
        stop_price = float(e.stop_loss) if e.stop_loss is not None else None
        entry_price = float(e.entry_price) if e.entry_price is not None else None
        r_multiple = None
        if target_price is not None and entry_price is not None and stop_price is not None:
            denom = entry_price - stop_price
            if denom != 0:
                r_multiple = (target_price - entry_price) / denom

        frame_id = _make_frame_id(signal_id, "at_close")

        se_params.append(
            (
                signal_id,  # signal_id
                e.timestamp,  # ts
                e.symbol,  # symbol
                e.timeframe,  # tf
                e.setup_plugin,  # setup_plugin
                direction,  # direction (text)
                raw_confidence,  # raw_confidence (NOT NULL)
                e.calibrated_confidence,  # calibrated_confidence (nullable)
                e.cis_score,  # cis_score
                e.weights_version,  # weights_version
                None,  # factor_scores (plugin-local, not in replay path)
                (
                    json.dumps(_sanitize_for_json(e.context_features))
                    if e.context_features
                    else None
                ),  # context_features (psycopg2 serialized JSONB)
                e.ctf_score,  # ctf_score
                e.ctf_confirmed,  # ctf_confirmed
                e.zone_friction_score,  # zone_friction_score
                e.hmm_regime_at_fire,  # hmm_regime_at_fire
                e.plugin_regime_type,  # plugin_regime_type
                e.garch_sigma_at_fire,  # garch_sigma_at_fire
                e.is_shadow,  # is_shadow
                # is_backfill = TRUE via SQL template
                "pending",  # status
                SIGNAL_SCHEMA_VERSION,  # signal_schema_version (int)
                e.ttl_bars,  # ttl_bars
                e.expires_at,  # expires_at
                e.signal_computed_at,  # signal_computed_at
                e.feature_ts,  # feature_ts
            )
        )

        tf_params.append(
            (
                frame_id,  # frame_id
                signal_id,  # signal_id
                e.timestamp,  # signal_ts (FK anchor for hypertable composite PK)
                "at_close",  # entry_type
                direction,  # direction (text)
                entry_price,  # entry_price
                stop_price,  # stop_price (was stop_loss)
                target_price,  # target_price (first target only)
                r_multiple,  # r_multiple
                e.ttl_bars,  # ttl_bars
                e.expires_at,  # expires_at
                # counterfactual_pnl_r = NULL (CounterfactualTracker v2.11)
                e.was_selected,  # was_selected
                frame_details_json,  # frame_details
            )
        )

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            _INSERT_SIGNAL_EVENTS_SYNC_SQL,
            se_params,
            template=_INSERT_SIGNAL_EVENTS_SYNC_TEMPLATE,
        )
        psycopg2.extras.execute_values(
            cur,
            _INSERT_TRADE_FRAMES_SYNC_SQL,
            tf_params,
            template=_INSERT_TRADE_FRAMES_SYNC_TEMPLATE,
        )
    conn.commit()


def _load_calibration_curves(
    conn: Any, symbol: str = "*"
) -> dict[tuple[str, str], tuple[list, list]]:
    """Load calibration curves from DB as 2-tuple keyed dict for aggregate().

    The DB stores 3-tuple keys (plugin, tf, symbol). aggregate() uses 2-tuple
    (plugin, tf). Symbol-specific curves take precedence over the global '*' sentinel.

    Returns {} when the table is empty — aggregate() falls back to raw confidence.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT setup_plugin, timeframe, symbol, curve_data "
            "FROM calibration_curves "
            "WHERE symbol = %s OR symbol = '*'",
            (symbol,),
        )
        rows = cur.fetchall()

    result: dict[tuple[str, str], tuple[list, list]] = {}
    for plugin, tf, row_symbol, curve_data in rows:
        if not curve_data:
            continue
        bp = curve_data.get("breakpoints")
        vals = curve_data.get("values")
        if not bp or not vals:
            continue
        key = (plugin, tf)
        if key not in result or row_symbol != "*":
            result[key] = (bp, vals)
    return result


def _load_perf_weights(conn: Any) -> dict[str, tuple[float, int]]:
    """Load perf multipliers from setup_performance using the same Sharpe-rank
    formula as the live pipeline (_compute_perf_multipliers).

    Returns {} when no setups have sample_size >= MIN_SAMPLE_SIZE (100).
    """
    from src.intelligence.setup_performance_updater import MIN_SAMPLE_SIZE

    with conn.cursor() as cur:
        cur.execute(
            "SELECT setup_plugin, win_rate, avg_pnl_r, sample_size, sharpe_ratio "
            "FROM setup_performance WHERE sample_size >= %s",
            (MIN_SAMPLE_SIZE,),
        )
        rows = cur.fetchall()

    if not rows:
        return {}

    stats = {
        plugin: {
            "win_rate": win_rate,
            "avg_pnl_r": avg_pnl_r,
            "sample_size": sample_size,
            "sharpe_ratio": sharpe_ratio,
        }
        for plugin, win_rate, avg_pnl_r, sample_size, sharpe_ratio in rows
    }
    return _compute_perf_multipliers(stats)


def _warm_config_service(conn: Any) -> Any:
    """Load APR config values from config_state and inject into framing-path modules.

    Constructs a ConfigService with a pre-warmed in-memory cache (no asyncpg pool
    needed — the cache is populated directly from a psycopg2 query). After this call,
    all _cfg() reads in trade_framer, zone_engine, aggregator, confidence, and
    volume_profile_utils will return APR values rather than hardcoded fallbacks.

    DAG invariant: ConfigService reads config_state once at warm-up only, then serves
    from in-memory cache via get_sync(). No DB access occurs during replay_symbol().

    Returns the ConfigService instance (also injected into module singletons as a
    side effect).
    """
    from src.config.config_service import ConfigService
    from src.intelligence.trading import (  # noqa: PLC0415
        aggregator,
        confidence,
        trade_framer,
        volume_profile_utils,
        zone_engine,
    )

    cfg = ConfigService(database_url="")  # No asyncpg pool — cache-only mode
    with conn.cursor() as cur:
        cur.execute(
            "SELECT cs.config_key, cs.config_value, csc.value_type "
            "FROM config_state cs "
            "JOIN config_schema csc USING (config_key)"
        )
        rows = cur.fetchall()

    for config_key, config_value, value_type in rows:
        cfg._cache[config_key] = cfg._parse_value(config_value, value_type)

    trade_framer.set_config_service(cfg)
    zone_engine.set_config_service(cfg)
    aggregator.set_config_service(cfg)
    confidence.set_config_service(cfg)
    volume_profile_utils.set_config_service(cfg)

    key_count = len(cfg._cache)
    print(f"  Replay config service wired ({key_count} keys from config_state)")
    return cfg


def _load_precomputed_features(
    conn: Any, symbol: str, since: datetime | None = None
) -> dict[tuple[str, datetime], dict]:
    """Load intelligence_features for symbol into (tf, ts) -> merged flat dict.

    Used by --use-precomputed-features to skip I1-I6 recomputation entirely.
    All eight JSONB tier columns (including composite_events and market_context) are merged
    into one flat dict per bar.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ts, tf,"
            " technical_indicators, pattern_detections, regime_features,"
            " confluence_scores, smc, cross_timeframe_context,"
            " composite_events, market_context"
            " FROM intelligence_features"
            " WHERE symbol = %s AND (%s IS NULL OR ts >= %s)"
            " ORDER BY ts ASC",
            (symbol, since, since),
        )
        rows = cur.fetchall()

    result: dict[tuple[str, datetime], dict] = {}
    for ts, tf, i1_data, i5_data, i3_data, i4_data, smc_col, ctf, ce_col, mkt_col in rows:
        merged: dict = {}
        for tier in (i1_data, i5_data, i3_data, i4_data, smc_col, ctf, ce_col, mkt_col):
            if not tier:
                continue
            if isinstance(tier, str):
                tier = json.loads(tier)
            merged.update(tier)
        key_ts = ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)
        result[(tf, key_ts)] = merged
    return result


def run_i7_and_persist(
    bar_history: deque,
    features: dict[str, Any],
    symbol: str,
    timeframe: str,
    timestamp: datetime,
    db_conn: Any,
    feature_ts: datetime | None = None,
    feature_tf: str | None = None,
    df: pd.DataFrame | None = None,
    signal_buffer: list | None = None,
    calibration_curves: dict | None = None,
    perf_weights: dict | None = None,
    plugin_states: dict[tuple[str, str, str], dict] | None = None,
) -> int:
    """Run I7 setup plugins on bar_history+features, aggregate, persist to signal_events + trade_frames.

    Args:
        bar_history: rolling window of bar dicts
        features: merged I1-I6 feature dict
        symbol: contract symbol
        timeframe: bar timeframe
        timestamp: bar timestamp
        db_conn: psycopg2 connection (None for dry-run)
        feature_ts: timestamp of the intelligence_features row for this bar (None if not written)
        feature_tf: timeframe of the intelligence_features row (None if not written)
        df: pre-built DataFrame for bar_history; constructed here if not provided.
        signal_buffer: if provided, entries are appended here instead of inserted immediately.

    Returns:
        Number of ledger entries produced (0 if no signals fired).
    """
    if len(bar_history) < min_bars_for_tf(timeframe):
        return 0

    if df is None:
        df = pd.DataFrame(list(bar_history))
    # I7 plugins build their internal features dict by merging typed sub-dicts:
    #   features = {**(frames.get("i1") or {}), **(frames.get("i4") or {}), ...}
    # The live executor populates these from the typed IntelligenceEvent tiers.
    # Backfill has one merged flat dict — put it in all tier slots so every plugin
    # finds its features regardless of which tier key it reads from.
    # Also set "symbol" so get_atr_with_floor_from_frames can apply the tick floor.
    frames: dict[str, Any] = {
        "main": df,
        "features": features,
        "i1": features,
        "i2": features,
        "i3": features,
        "i4": features,
        "i5": features,
        "smc": features,
        "i6": features,
        "symbol": symbol,
    }

    raw_signals = []
    states = plugin_states if plugin_states is not None else {}
    for name in I7_PLUGINS:
        try:
            plugin = registry.get_pattern(name)
            state_key = (name, symbol, timeframe)
            state = states.setdefault(state_key, {})
            t0 = time.perf_counter()
            result = incremental_compute(plugin, frames, state)
            _accumulate_plugin_time(name, t0)
            states[state_key] = result.get("_state", state)
            if result and result.get("direction", 0) != 0:
                result["setup_plugin"] = name
                raw_signals.append(result)
        except Exception as error:
            _log_plugin_error(name, symbol, timeframe, error)

    if not raw_signals:
        return 0

    for sig in raw_signals:
        annotate_signal_with_context(sig, features)

    trend_regime = float(features.get("trend_regime", 0.0))
    agg_result = aggregate(
        raw_signals,
        trend_regime=trend_regime,
        features=features,
        calibration_curves=calibration_curves,
        perf_weights=perf_weights,
    )
    entries = _build_ledger_entries(
        agg_result,
        symbol,
        timeframe,
        timestamp,
        features,
        feature_ts=feature_ts,
        feature_tf=feature_tf,
        bar_history=bar_history,
    )

    if entries:
        if signal_buffer is not None:
            signal_buffer.extend(entries)
        elif db_conn is not None:
            _insert_signals_sync(db_conn, entries)

    return len(entries)


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
        python production/scripts/run_historical_pipeline.py --seed-roll-chain
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


# ---------------------------------------------------------------------------
# Replay orchestrator
# ---------------------------------------------------------------------------


def replay_symbol(
    symbol: str,
    db_conn: Any,
    timeframes: list[str] | None = None,
    since: datetime | None = None,
    skip_signals: bool = False,
    calibration_curves: dict | None = None,
    perf_weights: dict | None = None,
    precomputed_features: dict | None = None,
    overwrite_features: bool = False,
    seed_from_db: bool = True,
) -> dict[str, int]:
    """Replay bars for *symbol* through the I1→I7 pipeline.

    Processes timeframes in order: 1m first, then 5m, 15m, 1h.
    Lower-TF bar history is available as cross-TF context when processing
    higher timeframes (same as live services).

    # A4 CONFIRMED (2026-06-17): asset_class=None for ALL symbols (NQM6, YMM6, ESM6, etc.)
    # in all_features throughout replay_symbol(). Root cause: live pipeline injects asset_class
    # via instrument_map (built from Settings.Instrument objects in FeaturePipelineExecutor),
    # but replay_symbol() never constructs this lookup and passes no instrument context to
    # run_i7_and_persist(). This is NOT specific to rolled contracts — active front-month
    # contracts are equally affected. Fix: build symbol→asset_class lookup from
    # contract_metadata + instruments tables at replay_symbol() startup and inject into
    # all_features before run_i7_and_persist(). See plan 131-03-PLAN.md T-01.

    Args:
        since: If provided, only replay bars on or after this timestamp.
        skip_signals: If True, run I1→I6 and write intelligence_features but
            skip I7 and signal_ledger writes. Use for seed/warmup runs where
            you only want indicator history, not historical signals.

    Returns:
        dict mapping timeframe → number of ledger entries inserted.
    """
    if timeframes is None:
        timeframes = DEFAULT_TIMEFRAMES

    # Load native stored bars for each requested timeframe.
    # Each TF reads its own rows from market_data_ohlcv (1m = named contract,
    # 5m/1h/1d = back-adjusted continuous). Higher TFs have deeper history.
    bars_by_tf: dict[str, list[dict]] = {}
    for tf in timeframes:
        bars = fetch_bars(db_conn, symbol, tf, since=since)
        if bars:
            bars_by_tf[tf] = bars
            print(f"  {symbol}: {len(bars):,} {tf} bars loaded")
        else:
            print(f"  {symbol}: no {tf} bars in DB — skipping (run fetch stage first)")

    if not bars_by_tf:
        print(f"  {symbol}: no bars found in DB — run fetch stage first")
        return {}

    # Release the read transaction so idle_in_transaction_session_timeout
    # doesn't kill the connection during the multi-minute processing loop.
    db_conn.commit()

    # A4 fix: resolve asset_class for this symbol from contract_metadata (futures rolls)
    # or instruments (equities/ETFs/FX). Mirrors FeaturePipelineExecutor.execute():332.
    # replay_symbol() never builds an instrument_map (unlike the live pipeline which injects
    # asset_class via FeaturePipelineExecutor DI at startup). Without this, trade_framer
    # _min_zone_width_atr() uses default thresholds for ALL replay signals — A4 CONFIRMED
    # in plan 131-01 (affects ALL symbols, not just rolled contracts).
    _symbol_asset_class: str | None = None
    with db_conn.cursor() as _cur:
        _cur.execute(
            """SELECT COALESCE(cm.asset_class, i.contract_details->>'asset_class')
               FROM (SELECT %s::text AS sym) s
               LEFT JOIN contract_metadata cm ON cm.symbol = s.sym
               LEFT JOIN instruments i ON i.symbol = s.sym
               LIMIT 1""",
            (symbol,),
        )
        _row = _cur.fetchone()
        if _row and _row[0] is not None:
            _symbol_asset_class = str(_row[0])

    # Shared state across timeframes for cross-TF context
    # 800 bars: SessionLevelsPlugin needs _SESSION_BARS=390 current + 390 prior window
    bar_histories: dict[str, deque] = defaultdict(lambda: deque(maxlen=800))
    intelligence_cache: dict[str, dict] = {}

    if seed_from_db:
        # A7 fix: seed intelligence_cache with prior I3 data from DB so I6 has
        # non-None trend fields on bar 1. Without this seed, ctf_score=0 for all bars.
        _standard_tfs = ["1m", "5m", "15m", "1h"]
        for _seed_tf in _standard_tfs:
            with db_conn.cursor() as _cur:
                _cur.execute(_SEED_QUERY_PG, (symbol, _seed_tf))
                _seed_row = _cur.fetchone()
            if _seed_row and any(_seed_row):
                # Filter None values — extract_trend_sign() handles missing keys as 0.
                # JSONB text extraction returns strings; coerce numeric fields to float so
                # is_num() in extract_trend_sign() passes (it requires isinstance(x, float)).
                _seed_dict = {
                    k: (float(v) if k in _SEED_NUMERIC_KEYS and v is not None else v)
                    for k, v in zip(_SEED_COLS, _seed_row)
                    if v is not None
                }
                if symbol not in intelligence_cache:
                    intelligence_cache[symbol] = {}
                intelligence_cache[symbol][_seed_tf] = _seed_dict
                print(
                    f"  [A7-seed] {symbol}/{_seed_tf}: seeded trend_direction={_seed_dict.get('trend_direction')!r}"
                )

    # A4: resolve asset_class once and merge into every all_features dict via _base_features.
    # Both the precomputed and computed paths call all_features.update(_base_features).
    _base_features: dict[str, str] = (
        {"asset_class": _symbol_asset_class} if _symbol_asset_class is not None else {}
    )

    # Per-(plugin_name, symbol, tf) state dict — isolates stateful plugins (GARCH/HMM/Kalman)
    # across symbols. Scoped to this symbol so state never bleeds into the next symbol.
    plugin_states: dict[tuple[str, str, str], dict] = {}

    # Per-TF accumulators — maintained across the merged event stream.
    _TF_SORT_KEY: dict[str, int] = {"1m": 0, "5m": 1, "15m": 2, "1h": 3, "4h": 4, "1d": 5}
    feature_buffers: dict[str, list] = defaultdict(list)
    signal_buffers: dict[str, list] = defaultdict(list)
    total_features_by_tf: dict[str, int] = defaultdict(int)
    total_signals_by_tf: dict[str, int] = defaultdict(int)
    bars_processed_by_tf: dict[str, int] = defaultdict(int)
    bars_total_by_tf: dict[str, int] = {tf: len(b) for tf, b in bars_by_tf.items()}

    for tf, count in bars_total_by_tf.items():
        print(f"  {symbol}/{tf}: replaying {count:,} bars...")

    # Merge all TF bar streams into a single chronological event sequence.
    # Lower TFs sort before higher TFs at the same timestamp — this ensures 1m bars are
    # processed before the 1h bar that closes at the same timestamp, so intelligence_cache
    # reflects only contemporaneous information when cross-TF context is injected.
    # Processing TFs sequentially (old approach) injected future 1m intel into past 1h
    # signal computation — a look-ahead bias that corrupts all cross-TF signals.
    events: list[tuple[datetime, int, str, dict]] = []
    for tf, bars in bars_by_tf.items():
        sort_key = _TF_SORT_KEY.get(tf, 99)
        for bar in bars:
            events.append((bar["timestamp"], sort_key, tf, bar))
    events.sort(key=lambda e: (e[0], e[1]))

    tf_hierarchy = ["1m", "5m", "15m", "1h"]

    for _ts, _sort, tf, bar in events:
        ts = bar["timestamp"]
        history_key = f"{symbol}:{tf}"
        bar_histories[history_key].append(bar)
        history = bar_histories[history_key]
        bars_processed_by_tf[tf] += 1

        # Skip indicator computation and signal emission on synthetic flat-fill bars.
        # Running quantitative indicators on fabricated prices produces misleading
        # features and signals built on noise. Bar is still appended to history above
        # so real bars that follow have correct context.
        if bar.get("source") == SOURCE_SYNTHETIC_FILL:
            continue

        # Warmup guard: skip until enough bars exist for stable indicator output.
        # Checked here so pd.DataFrame is never constructed on warmup bars.
        if len(history) < min_bars_for_tf(tf):
            continue

        # Build DataFrame once — shared across I1, frames, and I7.
        df = pd.DataFrame(list(history))
        written_feature_ts: datetime | None = None

        if precomputed_features is not None:
            # Precomputed mode: skip I1-I6 entirely; features already in intelligence_features.
            ts_utc = ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)
            all_features = precomputed_features.get((tf, ts_utc))
            if not all_features:
                continue
            all_features.update(_base_features)
            written_feature_ts = ts
        else:
            # I1 — pass pre-built df
            i1_features = run_i1_plugins(history, symbol, tf, plugin_states, df=df)
            if not i1_features:
                continue

            # Build frames with cross-TF context (for I6 confluence).
            # Because we process bars chronologically across all TFs, intelligence_cache
            # here contains only intel from timestamps <= ts — no look-ahead.
            frames: dict[str, Any] = {"main": df, "features": i1_features}
            for other_tf in tf_hierarchy:
                if other_tf == tf:
                    continue
                other_key = f"{symbol}:{other_tf}"
                if other_key in bar_histories and len(bar_histories[other_key]) >= 50:
                    frames[f"tf_{other_tf}"] = pd.DataFrame(list(bar_histories[other_key]))
                cached = intelligence_cache.get(symbol, {}).get(other_tf)
                if cached:
                    frames[f"intel_{other_tf}"] = cached

            # I2 → I6
            intelligence, tiered = run_analysis_pipeline(
                frames, intelligence_cache, symbol, tf, plugin_states
            )

            # Merge all features for I7
            all_features = {**i1_features, **intelligence}
            all_features.update(_base_features)

            # Build IntelligenceEvent and buffer for batch insert
            event = _build_intelligence_event(bar, i1_features, tiered, symbol, tf, ts)
            if event is not None:
                feature_buffers[tf].append(_event_to_sync_params(event))
                written_feature_ts = ts
                total_features_by_tf[tf] += 1
                if len(feature_buffers[tf]) >= _FEATURE_BATCH_SIZE:
                    _insert_features_sync(
                        db_conn, feature_buffers[tf], overwrite=overwrite_features
                    )
                    feature_buffers[tf].clear()

        # I7 → signal_ledger (skipped in seed/warmup mode)
        if not skip_signals:
            n = run_i7_and_persist(
                history,
                all_features,
                symbol,
                tf,
                ts,
                db_conn,
                feature_ts=written_feature_ts,
                feature_tf=(tf if written_feature_ts is not None else None),
                df=df,
                signal_buffer=signal_buffers[tf],
                calibration_curves=calibration_curves,
                perf_weights=perf_weights,
                plugin_states=plugin_states,
            )
            total_signals_by_tf[tf] += n
            if len(signal_buffers[tf]) >= _FEATURE_BATCH_SIZE:
                # Flush features first — signals must never commit before their features.
                if feature_buffers[tf]:
                    _insert_features_sync(
                        db_conn, feature_buffers[tf], overwrite=overwrite_features
                    )
                    feature_buffers[tf].clear()
                _insert_signals_sync(db_conn, signal_buffers[tf])
                signal_buffers[tf].clear()

        processed = bars_processed_by_tf[tf]
        if processed % 1000 == 0:
            total = bars_total_by_tf[tf]
            count = total_features_by_tf[tf] if skip_signals else total_signals_by_tf[tf]
            label = "features" if skip_signals else "signals"
            print(f"    {symbol}/{tf}: {processed:,}/{total:,} bars, {count} {label}")

    # Flush remaining feature and signal buffers for all TFs
    for tf, buf in feature_buffers.items():
        if buf:
            _insert_features_sync(db_conn, buf, overwrite=overwrite_features)
    for tf, buf in signal_buffers.items():
        if buf:
            _insert_signals_sync(db_conn, buf)

    signal_counts: dict[str, int] = {}
    for tf in timeframes:
        if tf not in bars_by_tf:
            continue
        count = total_features_by_tf[tf] if skip_signals else total_signals_by_tf[tf]
        signal_counts[tf] = count
        label = "feature rows written" if skip_signals else "signals inserted"
        print(f"  {symbol}/{tf}: done — {count} {label}")

    if _plugin_error_counts:
        total_errors = sum(_plugin_error_counts.values())
        print(
            f"  {symbol}: {total_errors} plugin errors across {len(_plugin_error_counts)} plugins — check logs above"
        )

    return signal_counts


class _WorkerArgs(NamedTuple):
    symbol: str
    db_url: str
    timeframes: list[str]
    since_dt: datetime | None
    skip_signals: bool
    use_precomputed: bool
    overwrite_features: bool
    seed_from_db: bool


def _replay_worker(args: _WorkerArgs) -> tuple[str, int, dict[str, int]]:
    """Worker for parallel symbol replay.

    Runs in a subprocess via ProcessPoolExecutor. Opens its own psycopg2
    connection (connections cannot be shared across processes), registers
    plugins, replays the symbol, commits, and closes.
    """
    (
        symbol,
        db_url,
        timeframes,
        since_dt,
        skip_signals,
        use_precomputed,
        overwrite_features,
        seed_from_db,
    ) = args
    register_all_plugins()
    conn = psycopg2.connect(dsn=db_url)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SET synchronous_commit = off")
    try:
        _warm_config_service(conn)
        calibration_curves = _load_calibration_curves(conn, symbol=symbol)
        perf_weights = _load_perf_weights(conn)
        precomputed = (
            _load_precomputed_features(conn, symbol, since=since_dt) if use_precomputed else None
        )
        counts = replay_symbol(
            symbol,
            conn,
            timeframes,
            since=since_dt,
            skip_signals=skip_signals,
            calibration_curves=calibration_curves,
            perf_weights=perf_weights,
            precomputed_features=precomputed,
            overwrite_features=overwrite_features,
            seed_from_db=seed_from_db,
        )
        return symbol, sum(counts.values()), counts
    finally:
        conn.close()


# ---------------------------------------------------------------------------
def _assert_backfill_integrity(conn: Any, symbols: list[str]) -> None:
    """Assert was_selected and signal_id invariants across all symbols in one pass.

    Invariant 1: was_selected = TRUE occurs at most once per (symbol, tf, bar_ts).
    Invariant 2: Every signal_id in signal_events is globally unique.

    Runs two queries using ANY(%s) — covered by idx_signal_events_symbol_tf_ts (migration 140)
    and idx_signal_events_symbol_signal_id (migration 144). sys.exit(1) on any violation.
    """
    # --- Invariant 1: was_selected uniqueness per (symbol, tf, bar_ts) ---
    all_violations: list[Any] = []
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT se.symbol, se.tf, se.ts, COUNT(*) AS winner_count
                FROM signal_events se
                JOIN trade_frames tf ON tf.signal_id = se.signal_id
                                   AND tf.signal_ts = se.ts
                WHERE se.symbol = ANY(%s) AND tf.was_selected = TRUE
                GROUP BY se.symbol, se.tf, se.ts
                HAVING COUNT(*) > 1
                ORDER BY winner_count DESC
                LIMIT 20
                """,
                (symbols,),
            )
            all_violations = cur.fetchall()
    except Exception as error:
        print(f"\n[INTEGRITY WARN] invariant 1 query failed: {error}")
        print("  Data may be intact; re-run audit manually to confirm.")

    if all_violations:
        print(f"\n[INTEGRITY FAIL] was_selected > 1 per bar — {len(all_violations)} bars affected:")
        for sym, tf, ts, cnt in all_violations:
            print(f"  {sym}/{tf} @ {ts}: {cnt} winners")
        sys.exit(1)

    # --- Invariant 2: signal_id global uniqueness ---
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT signal_id FROM signal_events
                    WHERE symbol = ANY(%s)
                    GROUP BY signal_id HAVING COUNT(*) > 1
                ) dups
                """,
                (symbols,),
            )
            total_dup_count = cur.fetchone()[0]
    except Exception as error:
        print(f"\n[INTEGRITY WARN] invariant 2 query failed: {error}")
        print("  Data may be intact; re-run audit manually to confirm.")
        return

    if total_dup_count:
        print(f"\n[INTEGRITY FAIL] {total_dup_count} duplicate signal_ids found")
        sys.exit(1)

    print(
        f"\n[INTEGRITY PASS] was_selected invariant holds across {len(symbols)} symbols. signal_ids unique."
    )


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
    parser = argparse.ArgumentParser(
        description="Historical Backfill — fetch IBKR bars + replay intelligence pipeline"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Max days to fetch/replay for ALL timeframes (default: per-TF config defaults).",
    )
    parser.add_argument(
        "--min-bars",
        type=int,
        default=None,
        dest="min_bars",
        help=(
            "Minimum bars per timeframe for replay. Derives lookback days from the slowest TF "
            "(1d ≈ 5 bars/7 calendar days), ensuring all TFs have enough bars to exercise "
            "plugins. Overrides --days. E.g. --min-bars 50 → ~70 calendar days."
        ),
    )
    parser.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated symbols, e.g. ESH6,NQH6 (default: all active)",
    )
    parser.add_argument(
        "--timeframes",
        default="1m,5m,15m,1h,4h,1d",
        help="Comma-separated timeframes (default: 1m,5m,15m,1h,4h,1d)",
    )
    parser.add_argument("--client-id", type=int, default=40, help="IBKR client ID (default: 40)")
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="Only fetch from IBKR → DB, skip intelligence replay",
    )
    parser.add_argument(
        "--replay-only", action="store_true", help="Only replay DB → signal_events, skip IBKR fetch"
    )
    parser.add_argument(
        "--include-rolled",
        action="store_true",
        help=(
            "Include rolled/expired futures contracts in replay (not just is_front_month=true). "
            "Use with --replay-only to replay full roll-chain history. "
            "Non-futures instruments are always included regardless of this flag."
        ),
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete existing signals before replay (use with --replay-only to avoid duplicates)",
    )
    parser.add_argument(
        "--setups",
        type=str,
        default=None,
        help=(
            "Comma-separated setup_plugin names to scope --clean deletion. "
            "When provided, only deletes signal_events and trade_frames rows for these setups "
            "(intelligence_features is NOT deleted). "
            "Default: None (full-symbol clean)."
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Parallel worker processes for replay stage (default: 8). Use 1 to disable.",
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
    parser.add_argument(
        "--use-precomputed-features",
        action="store_true",
        default=False,
        help="Skip I1-I6 recomputation; load stored intelligence_features rows and feed "
        "them directly to I7. Use when only I7 plugins changed (phases 118-119). "
        "5-10x faster than full replay. Requires intelligence_features to be current.",
    )
    parser.add_argument(
        "--overwrite-features",
        action="store_true",
        default=False,
        help="When running I1-I6 fresh, overwrite existing intelligence_features rows "
        "(DO UPDATE) instead of skipping them (DO NOTHING). Use when I1-I6 code changed "
        "and you want the stored feature vectors to reflect current computation.",
    )
    parser.add_argument(
        "--no-seed",
        action="store_true",
        default=False,
        help="Skip DB seed of intelligence_cache before bar 1 (for testing unseeded path). "
        "By default the replay seeds cross-TF I3 trend data from intelligence_features so "
        "I6 ctf_score is non-zero on bar 1 (A7 fix).",
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

    print("Historical Backfill Pipeline")
    print(f"  Contracts : {[c.symbol for c in contracts]}")
    print(f"  Timeframes: {timeframes}")
    tf_depths = {
        tf: (min(_TF_FETCH_CONFIG[tf][0], args.days) if args.days else _TF_FETCH_CONFIG[tf][0])
        for tf in timeframes
        if tf in _TF_FETCH_CONFIG
    }
    print(f"  TF depths : {tf_depths}")
    if args.fetch_only:
        stage = "fetch-only"
    elif args.replay_only:
        stage = "replay-only"
    else:
        stage = "fetch+replay"
    print(f"  Stages    : {stage}")
    print()

    db_conn = connect_db(settings)

    if args.normalize:
        run_normalize(db_conn, contracts, timeframes)
        db_conn.close()
        return

    # --------------- Stage 1: IBKR Fetch ---------------
    if not args.replay_only:
        print("=== Stage 1: IBKR Fetch ===")

        async def _run_fetch_stage() -> int:
            provider = IBKRProvider(
                host=settings.ib_host,
                port=settings.ib_port,
                client_id=args.client_id,
            )
            if not await provider.connect():
                print("Cannot connect to TWS — aborting fetch stage")
                return -1

            end_dt = datetime.now(tz=UTC)
            total_bars = 0
            fetch_tfs = [tf for tf in timeframes if tf in _TF_FETCH_CONFIG]
            print(f"  Fetching TFs: {fetch_tfs}")
            print()
            try:
                for instrument in contracts:
                    try:
                        qualified = await provider.qualify_instrument(instrument)
                        if not qualified:
                            print(f"  {instrument.symbol}: skipped (qualify failed)")
                            continue

                        # Per-contract mode for futures: fetch each contract in roll chain
                        if args.per_contract and instrument.asset_class == AssetClass.FUTURES:
                            print(f"  {instrument.symbol}: per-contract mode (Renaissance-style)")
                            for tf in fetch_tfs:
                                fetch_days, _ = _TF_FETCH_CONFIG[tf]
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
                            fetch_days, use_continuous = _TF_FETCH_CONFIG[tf]
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

                            print(
                                f"  {instrument.symbol}/{tf}: {len(gaps)} gaps detected, "
                                f"fetching full window {start_dt.date()} to {end_dt.date()}..."
                            )

                            # Skip continuous contracts for short windows (no rolls needed)
                            use_cont = (
                                use_continuous
                                and (fetch_days > 14)
                                and (instrument.asset_class == AssetClass.FUTURES)
                            )
                            # Fetch the full window in one call; the provider chunks at
                            # _MAX_CHUNK_DAYS[tf] (364d for 4h/1h/1d) with 10s between
                            # chunks. Per-gap fetching sent N×IBKR requests + N×2s sleep
                            # for trivially small windows — absurdly slow on initial backfill.
                            # ON CONFLICT DO NOTHING makes this idempotent.
                            try:
                                ohlcv_bars = await provider.fetch_historical_bars(
                                    symbol=instrument.symbol,
                                    timeframe=tf,
                                    start=start_dt,
                                    end=end_dt,
                                    continuous=use_cont,
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
                                    start=start_dt,
                                    end=end_dt,
                                )
                                n = store_bars(db_conn, canonical, instrument.symbol, tf)
                                total_bars += n
                                if n > 0:
                                    fetched_tfs.add(tf)
                                print(
                                    f"  {instrument.symbol}/{tf}: stored {n} bars "
                                    f"({len(gaps)} gaps filled)"
                                )
                            except Exception as e:
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
                                    print(
                                        f"  {instrument.symbol}: no 1m bars — skipping derivation"
                                    )
                            else:
                                sym = instrument.symbol
                                print(f"  {sym}: all TFs fetched from IBKR — skipping derivation")

                        # 4h bars are fetched directly from IBKR at 730d depth above.
                        # No derivation needed: 1m only covers 14d (named contract, no rolls)
                        # which is inferior in both depth and price series to the direct fetch.
                        # Gaps in IBKR 4h data are handled by the gap detection + refetch path.

                    except Exception as e:
                        print(f"  {instrument.symbol}: error — {e}")
                    await asyncio.sleep(2)  # IBKR pacing between instruments
            finally:
                await provider.disconnect()
            return total_bars

        result = asyncio.run(_run_fetch_stage())
        if result == -1:
            if args.fetch_only:
                db_conn.close()
                return
            print("Continuing with replay-only...")
        else:
            print(f"\nStage 1 complete: {result:,} total bars stored\n")

    # --------------- Stage 2: Intelligence Replay ---------------
    if not args.fetch_only:
        print("=== Stage 2: Intelligence Replay ===")
        # When --days is provided, limit replay to that window.
        # Full-history replay (default, no --days) uses since_dt=None to read all DB bars.
        if args.min_bars:
            # Derive lookback from slowest TF (1d ≈ 5 trading bars per 7 calendar days).
            # All faster TFs will have more than min_bars in this window.
            days_needed = math.ceil(args.min_bars * 7 / 5)
            since_dt = datetime.now(UTC) - timedelta(days=days_needed)
            print(
                f"  --min-bars {args.min_bars}: {days_needed}d window "
                f"(1d TF ≈ 5 bars/wk → {days_needed}d ≥ {args.min_bars} bars)"
            )
        elif args.days:
            since_dt = datetime.now(UTC) - timedelta(days=args.days)
            print(f"  Replaying bars since: {since_dt.date()} ({args.days}d)")
        else:
            since_dt = None

        # Clean up old signals for replayed symbols if --clean flag is set
        if args.clean:
            print("  Cleaning up old signals for replayed symbols...")
            with db_conn.cursor() as cur:
                symbol_values = [c.symbol for c in contracts]

                # Determine setup filter scope.
                # When --setups is explicitly "ALL", fall back to full-symbol clean.
                # Otherwise: if --setups provided, use that list; default scope is the
                # 22 _SHADOW_VALIDATION_SETUPS frozenset (never hardcoded here).
                if args.setups == "ALL":
                    setup_filter: list[str] | None = None
                elif args.setups is not None:
                    setup_filter = [s.strip() for s in args.setups.split(",") if s.strip()]
                else:
                    # Default: scope to the 22 shadow validation setups.
                    # Add services/ to sys.path so shadow_validator's _path_bootstrap import works.
                    import sys as _sys

                    _services_dir = str(project_root / "services")
                    if _services_dir not in _sys.path:
                        _sys.path.insert(0, _services_dir)
                    from services.shadow_validator import _SHADOW_VALIDATION_SETUPS

                    setup_filter = list(_SHADOW_VALIDATION_SETUPS)

                if setup_filter is not None:
                    # Plugin-scoped clean: skip intelligence_features (no setup_plugin column;
                    # per-bar feature vectors are shared across all 30 setups — deleting by
                    # symbol would destroy the 8 GOOD control setups' feature data).
                    print(
                        f"  Plugin-scoped clean: {len(setup_filter)} setups, "
                        f"{len(symbol_values)} symbols — intelligence_features NOT deleted"
                    )
                    # Required for TimescaleDB compressed chunks: allow unlimited decompression
                    # during DML. Without this, deletes across compressed hypertable chunks fail
                    # with "tuple decompression limit exceeded".
                    cur.execute("SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0")
                    # Delete trade_frames (FK child) then signal_events (FK parent)
                    cur.execute(
                        """DELETE FROM trade_frames
                           WHERE signal_id IN (
                               SELECT signal_id FROM signal_events
                               WHERE symbol = ANY(%s) AND setup_plugin = ANY(%s)
                           )""",
                        (symbol_values, setup_filter),
                    )
                    deleted_frames = cur.rowcount
                    cur.execute(
                        """DELETE FROM signal_events
                           WHERE symbol = ANY(%s) AND setup_plugin = ANY(%s)""",
                        (symbol_values, setup_filter),
                    )
                    deleted_signals = cur.rowcount
                    db_conn.commit()
                    print(
                        f"  Deleted {deleted_signals:,} signal_events rows + "
                        f"{deleted_frames:,} trade_frames rows "
                        f"(intelligence_features preserved)"
                    )
                else:
                    # Full-symbol clean (legacy path, requires --setups ALL)
                    # Delete signals AND intelligence_features for the symbols we're about to replay
                    cur.execute(
                        "DELETE FROM intelligence_features WHERE symbol = ANY(%s)",
                        (symbol_values,),
                    )
                    deleted_features = cur.rowcount

                    # Delete in FK order: trade_executions → trade_frames → signal_events
                    cur.execute(
                        """
                        DELETE FROM trade_executions
                        WHERE frame_id IN (
                            SELECT tf.frame_id FROM trade_frames tf
                            JOIN signal_events se ON tf.signal_id = se.signal_id
                            WHERE se.symbol = ANY(%s)
                        );
                    """,
                        (symbol_values,),
                    )
                    deleted_executions = cur.rowcount
                    cur.execute(
                        """
                        DELETE FROM trade_frames
                        WHERE signal_id IN (
                            SELECT signal_id FROM signal_events WHERE symbol = ANY(%s)
                        );
                    """,
                        (symbol_values,),
                    )
                    deleted_frames = cur.rowcount
                    cur.execute(
                        """
                        DELETE FROM signal_events
                        WHERE symbol = ANY(%s);
                    """,
                        (symbol_values,),
                    )
                    deleted_signals = cur.rowcount

                    db_conn.commit()
                    print(
                        f"  Deleted {deleted_signals:,} signals + "
                        f"{deleted_frames:,} trade_frames + "
                        f"{deleted_executions:,} trade_executions + "
                        f"{deleted_features:,} intelligence feature rows"
                    )

        register_all_plugins()
        grand_total = 0

        if args.workers == 1:
            with db_conn.cursor() as cur:
                cur.execute("SET synchronous_commit = off")
            _warm_config_service(db_conn)
            perf_weights = _load_perf_weights(db_conn)

            for contract in contracts:
                print(f"\n{contract.symbol}:")
                calibration_curves = _load_calibration_curves(db_conn, symbol=contract.symbol)
                precomputed = (
                    _load_precomputed_features(db_conn, contract.symbol, since=since_dt)
                    if args.use_precomputed_features
                    else None
                )
                counts = replay_symbol(
                    contract.symbol,
                    db_conn,
                    timeframes,
                    since=since_dt,
                    calibration_curves=calibration_curves,
                    perf_weights=perf_weights,
                    precomputed_features=precomputed,
                    overwrite_features=args.overwrite_features,
                    seed_from_db=not args.no_seed,
                )
                symbol_total = sum(counts.values())
                grand_total += symbol_total
                print(f"  {contract.symbol} total: {symbol_total} signals")
        else:
            worker_args = [
                _WorkerArgs(
                    symbol=contract.symbol,
                    db_url=settings.database_url,
                    timeframes=timeframes,
                    since_dt=since_dt,
                    skip_signals=False,
                    use_precomputed=args.use_precomputed_features,
                    overwrite_features=args.overwrite_features,
                    seed_from_db=not args.no_seed,
                )
                for contract in contracts
            ]
            print(f"  Spawning {args.workers} workers for {len(contracts)} symbols...")
            try:
                with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as executor:
                    futures = {executor.submit(_replay_worker, arg): arg[0] for arg in worker_args}
                    for future in concurrent.futures.as_completed(futures):
                        symbol = futures[future]
                        try:
                            sym, total, counts = future.result()
                            grand_total += total
                            print(f"\n  {sym} done: {total} signals  {dict(counts)}")
                        except Exception as error:
                            print(f"\n  {symbol} FAILED: {error}")
            except KeyboardInterrupt:
                print("\nInterrupted — workers will be terminated.")
                raise

        print(f"\nStage 2 complete: {grand_total} total signals inserted into signal_events")
        _assert_backfill_integrity(db_conn, [c.symbol for c in contracts])

    db_conn.close()
    flush_and_shutdown_metrics()
    # Per-plugin cumulative dispatch time (single-worker/in-process path only;
    # parallel workers each have their own dict and do not aggregate here).
    _report_plugin_times()
    print("\nBackfill complete.")


if __name__ == "__main__":
    try:
        init_otel_providers("historical-backfill")
    except OTelInitError as error:
        print(f"[warn] OTel init failed — metrics disabled: {error}")
    main()
