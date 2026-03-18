#!/usr/bin/env python3
"""
Historical Backfill Pipeline

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
signal_ledger and intelligence_features.

Replaces: production/scripts/simple_seeder.py (retired)

Usage:
    python production/scripts/historical_backfill.py
    python production/scripts/historical_backfill.py --fetch-only
    python production/scripts/historical_backfill.py --replay-only
    python production/scripts/historical_backfill.py --symbols ESH6,NQH6

    # Per-contract mode (Renaissance-style raw data storage):
    python production/scripts/historical_backfill.py --fetch-only --per-contract --symbols ESH6

    # Gap-fill: fetch last 2 days across ALL TFs (not just 1m), then replay only those 2 days:
    python production/scripts/historical_backfill.py --fetch-only --symbols EURUSD,BTCUSD --days 2
    python production/scripts/historical_backfill.py --replay-only --symbols EURUSD,BTCUSD --days 2

    python production/scripts/historical_backfill.py --replay-only --clean  # delete old signals

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
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import json
import sys
import time
from collections import defaultdict, deque

import psycopg2
import psycopg2.extras

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd

from src.config.contracts import derive_roll_chain
from src.config.settings import Settings
from src.core.database_manager import DatabaseManager
from src.core.models import AssetClass, ContractMetadata, Instrument
from src.core.service_utils import bar_close_ts as compute_bar_close_ts
from src.intelligence.plugins import registry
from src.intelligence.register_plugins import register_all_plugins
from src.intelligence.trading.aggregator import AggregatedResult, aggregate
from src.intelligence.trading.signal_ledger import LedgerEntry
from src.providers import IBKRProvider

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

# Months for futures contract symbols (H=Mar, M=Jun, U=Sep, Z=Dec)
_MONTH_CODES = {
    "H": "03",  # March
    "M": "06",  # June
    "U": "09",  # September
    "Z": "12",  # December
    # Additional expiries for some products
    "F": "01",  # January
    "G": "02",  # February
    "J": "04",  # April
    "K": "05",  # May
    "N": "07",  # July
    "Q": "08",  # August
    "V": "10",  # October
    "X": "11",  # November
}


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
    if month_code not in _MONTH_CODES:
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


def _upsert_contract_metadata(
    db_conn: Any, metadata: list[ContractMetadata]
) -> int:
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
            m.symbol, m.base_symbol, m.asset_class.value,
            m.expiry_date, m.first_notice_date,
            m.roll_from, m.roll_to, m.roll_date, m.roll_gap, m.exchange
        )
        for m in metadata
    ]

    with db_conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, params)
    db_conn.commit()
    return len(params)


def fetch_per_contract(
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
        month_num = _MONTH_CODES[month_code]
        # Find 3rd Friday of the month
        first_day = date(contract_year, month_num, 1)
        first_friday = (4 - first_day.weekday()) % 7 + 1
        expiry_date = datetime.combine(
            date(contract_year, month_num, first_friday + 7),
            datetime.min.time()
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
            qualified = asyncio.run(provider.qualify_instrument(contract_instrument))
            if not qualified:
                print(f"    {contract_sym}: skip (qualify failed)")
                continue

            # Fetch bars for this contract
            start_dt = (end_dt - timedelta(days=fetch_days)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            ohlcv_bars = asyncio.run(
                provider.fetch_historical_bars(
                    symbol=contract_sym,
                    timeframe=timeframe,
                    start=start_dt,
                    end=end_dt,
                    continuous=False,  # Always named contract for per-contract mode
                )
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

            time.sleep(1)  # IBKR pacing between contracts

        except Exception as e:
            print(f"    {contract_sym}: error — {e}")

    # Upsert all metadata
    if metadata_list:
        _upsert_contract_metadata(db_conn, metadata_list)

    return (total_bars, metadata_list)


# ---------------------------------------------------------------------------
# Plugin lists — keep in sync with services
# ---------------------------------------------------------------------------
I1_PLUGINS = [
    "RSI",
    "MovingAverages",
    "MAComposite",
    "MACD",
    "ATR",
    "BollingerBands",
    "Stochastic",
    "CCI",
    "WilliamsR",
    "MFI",
    "OBV",
    "VWAP",
    "Supertrend",
    "ADX",
    "KeltnerChannels",
    "DonchianChannels",
    "ROC_PPO",
    "ind_CMF",
    "ind_Aroon",
    "ind_HistoricalVolatility",
    "ind_ChandelierExit",
    "ind_ParabolicSAR",
    "ind_StochRSI",
]
I2_PLUGINS = [
    "evt_MACDEvents",
    "evt_RSIEvents",
    "evt_StochasticEvents",
    "evt_ADXEvents",
    "evt_VolumeEvents",
    "evt_MomentumAcceleration",
    "evt_DonchianPosition",
    "evt_OBVMomentum",
    "cmp_DerivativeOscillator",
    "cmp_ExhaustionScore",
    "cmp_AccelerationRegime",
]
I3_PLUGINS = ["struct_SwingDetector", "struct_SupportResistance", "struct_TrendStructure"]
I4_PLUGINS = [
    "ctx_VolatilityRegime",
    "ctx_TrendRegime",
    "ctx_MomentumContext",
    "ctx_GARCHVolatility",
]
I5_PLUGINS = [
    "RSIDivergence",
    "BollingerSqueeze",
    "VolumeDivergence",
    "Confluence",
    "TrendConfluence",
]
from src.intelligence.register_plugins import TIER_SMC, TIER_I6, TIER_I7

SMC_PLUGINS = TIER_SMC
I6_PLUGINS = TIER_I6
I7_PLUGINS = TIER_I7

MIN_BARS = 50
DEFAULT_TIMEFRAMES = ["1m", "5m", "15m", "1h", "1d"]
# Larger than live service batch (50) — replay has no latency pressure and benefits from
# fewer commits over millions of bars.
_FEATURE_BATCH_SIZE = 500

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
    # 1m: named contract (no roll crossings). 14d = 2 full Mon–Fri weekly cycles = ~5,460 bars,
    #     capturing time-of-day and day-of-week intraday patterns. Still well within IBKR's
    #     capturing time-of-day and day-of-week intraday patterns.
    "1m": (14, True),
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
) -> dict[str, Any]:
    """Run all I1 indicator plugins on the current bar history.

    Returns empty dict if fewer than MIN_BARS are available (indicators
    need warmup history to produce meaningful values).

    Args:
        plugin_states: per-(name, symbol, tf) state dict; mutated in place to
            isolate stateful plugins (GARCH, HMM, Kalman) across symbols.
    """
    if len(bar_history) < MIN_BARS:
        return {}

    df = pd.DataFrame(list(bar_history))
    frames: dict[str, Any] = {"main": df, "features": {}}
    features: dict[str, Any] = {}

    for name in I1_PLUGINS:
        try:
            plugin = registry.get_indicator(name)
            state_key = (name, symbol, timeframe)
            plugin._state = plugin_states.setdefault(state_key, {})
            out = plugin.compute_full(frames)
            plugin_states[state_key] = plugin._state  # write-back is load-bearing (GARCH/HMM)
            if out:
                features.update(
                    {k: v for k, v in out.items() if isinstance(v, (int, float, str, bool))}
                )
                frames["features"] = features
        except Exception:
            pass  # individual plugin failure never kills the replay

    return features


def run_analysis_pipeline(
    frames: dict[str, Any],
    intelligence_cache: dict[str, dict[str, Any]],
    symbol: str,
    timeframe: str,
    plugin_states: dict[tuple[str, str, str], dict],
) -> dict[str, Any]:
    """Run I2 → I3 → I4 → I5 → SMC → I6 plugins in tier order.

    Mutates frames["features"] in-place (same as market_analysis_service).
    Caches result in intelligence_cache[symbol][timeframe] for I6 cross-TF plugin.

    Args:
        plugin_states: per-(name, symbol, tf) state dict; mutated in place to
            isolate stateful plugins (GARCH, HMM, Kalman) across symbols.

    Returns:
        Merged intelligence dict from all tiers.
    """
    features = dict(frames.get("features", {}))
    frames["features"] = features
    intelligence: dict[str, Any] = {}

    tier_sequence = [
        (I2_PLUGINS, "I2"),
        (I3_PLUGINS, "I3"),
        (I4_PLUGINS, "I4"),
        (I5_PLUGINS, "I5"),
        (SMC_PLUGINS, "SMC"),
        (I6_PLUGINS, "I6"),
    ]

    for plugin_names, _ in tier_sequence:
        for name in plugin_names:
            try:
                plugin = registry.get_pattern(name)
                state_key = (name, symbol, timeframe)
                plugin._state = plugin_states.setdefault(state_key, {})
                out = plugin.compute_full(frames)
                plugin_states[state_key] = plugin._state  # write-back is load-bearing
                if out:
                    intelligence.update(out)
                    features.update(out)
                    frames["features"] = features
            except Exception:
                pass

    intelligence_cache.setdefault(symbol, {})[timeframe] = intelligence
    return intelligence


# ---------------------------------------------------------------------------
# Intelligence features — sync DB insert (mirrors feature_writer_service with %s placeholders)
# ---------------------------------------------------------------------------

_INSERT_FEATURE_SYNC_SQL = """
INSERT INTO intelligence_features (
    ts, symbol, tf, platform, source, schema_version,
    bar, i1, i3, i4, i5, smc, i6
) VALUES %s
ON CONFLICT (ts, symbol, tf) DO NOTHING
"""

# Per-row template for execute_values — JSONB casts must be explicit per column.
_INSERT_FEATURE_SYNC_TEMPLATE = (
    "(%s, %s, %s, %s, %s, %s,"
    " %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb)"
)


def _build_intelligence_event(
    bar: dict,
    i1_features: dict,
    intelligence: dict,
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
        intelligence: merged flat dict from run_analysis_pipeline (all tiers)
        symbol: contract symbol (e.g. 'ESH6')
        tf: timeframe string (e.g. '1m')
        ts: bar timestamp (timezone-aware datetime)
    """
    try:
        from src.intelligence.schemas import (
            I1Indicators,
            I3Structure,
            I4Context,
            I5Patterns,
            I6Confluence,
            IntelligenceEvent,
            OHLCVBar,
            SMCContext,
        )

        def _pick(model_cls: Any, src: dict) -> dict:
            """Filter src to only keys declared in model_cls.model_fields."""
            fields = model_cls.model_fields.keys()
            return {k: v for k, v in src.items() if k in fields}

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
            i1=I1Indicators(**_pick(I1Indicators, i1_features)),
            i3=I3Structure(**_pick(I3Structure, intelligence)),
            i4=I4Context(**_pick(I4Context, intelligence)),
            i5=I5Patterns(**_pick(I5Patterns, intelligence)),
            smc=SMCContext(**_pick(SMCContext, intelligence)),
            i6=I6Confluence(**_pick(I6Confluence, intelligence)),
        )
    except Exception:
        return None


def _event_to_sync_params(event: Any) -> tuple:
    """Serialize IntelligenceEvent to a 13-element tuple for psycopg2 batch insert.

    Column order matches _INSERT_FEATURE_SYNC_SQL:
      ts, symbol, tf, platform, source, schema_version,
      bar, i1, i3, i4, i5, smc, i6

    bar and i1 are serialized with model_dump() (include None values for completeness).
    i3, i4, i5, smc, i6 are serialized with model_dump(exclude_none=True) for compactness.
    """
    return (
        event.ts,  # datetime — psycopg2 native
        event.symbol,
        event.tf,
        event.platform,
        event.source,
        event.schema_version,
        json.dumps(event.bar.model_dump()),  # bar: include all fields
        json.dumps(event.i1.model_dump()),  # i1: include all fields
        json.dumps(event.i3.model_dump(exclude_none=True)),  # i3: sparse (extra='forbid')
        json.dumps(event.i4.model_dump(exclude_none=True)),  # i4: sparse
        json.dumps(event.i5.model_dump(exclude_none=True)),  # i5: sparse
        json.dumps(event.smc.model_dump(exclude_none=True)),  # smc: sparse
        json.dumps(event.i6.model_dump(exclude_none=True)),  # i6: sparse
    )


def _insert_features_sync(conn: Any, rows: list) -> None:
    """Synchronous psycopg2 batch insert into intelligence_features.

    Uses execute_values() (single multi-row INSERT) rather than execute_batch()
    (N separate statements) for ~3-5x throughput on large replay batches.

    Args:
        conn: psycopg2 connection
        rows: list of 13-element tuples from _event_to_sync_params()
    """
    if not rows:
        return
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur, _INSERT_FEATURE_SYNC_SQL, rows, template=_INSERT_FEATURE_SYNC_TEMPLATE
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

_INSERT_SYNC_SQL = """
INSERT INTO signal_ledger (
    signal_id, timestamp, symbol, timeframe, setup_plugin, signal_type,
    direction, entry_price, stop_loss, targets,
    confidence, confluence_score, regime_context, supporting_factors,
    was_selected, num_signals_bar, num_agreeing, num_conflicting,
    resolution_method, composite_rank, market_context, status,
    feature_ts, feature_tf,
    cis_score, bucket_scores, weights_version, signal_quality,
    market_entry_price
) VALUES (
    %s::uuid, %s, %s, %s, %s, %s,
    %s, %s, %s, %s::jsonb,
    %s, %s, %s, %s::jsonb,
    %s, %s, %s, %s,
    %s, %s, %s::jsonb, %s,
    %s, %s,
    %s, %s::jsonb, %s, %s,
    %s
) ON CONFLICT DO NOTHING
"""


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

    market_ctx = {k: features[k] for k in MARKET_CONTEXT_KEYS if k in features}
    bar_close = float(bar_history[-1]["close"]) if bar_history else None

    entries = []
    for sig in result.all_ranked:
        rank = sig.get("composite_rank", 99)
        was_selected = rank == 1 and result.selected_signal is not None
        entries.append(
            LedgerEntry(
                signal_id=str(uuid4()),
                timestamp=timestamp,
                symbol=symbol,
                timeframe=timeframe,
                setup_plugin=sig.get("setup_plugin", "unknown"),
                signal_type=sig.get("signal_type", "unknown"),
                direction=int(sig.get("direction", 0)),
                entry_price=float(sig.get("entry_price", 0.0)),
                stop_loss=float(sig.get("stop_loss", 0.0)),
                targets=[float(t) for t in sig.get("targets", [])],
                confidence=float(sig.get("confidence", 0.0)),
                confluence_score=float(sig.get("confluence_score", 0.0)),
                regime_context=str(sig.get("regime_context", "")),
                supporting_factors=list(sig.get("supporting_factors", [])),
                was_selected=was_selected,
                num_signals_bar=result.num_signals_fired,
                num_agreeing=result.num_agreeing,
                num_conflicting=result.num_conflicting,
                resolution_method=result.resolution_method,
                composite_rank=rank,
                market_context=market_ctx,
                status="pending",
                feature_ts=feature_ts,
                feature_tf=feature_tf,
                cis_score=result.cis_score,
                bucket_scores=result.bucket_scores,
                weights_version=result.weights_version,
                market_entry_price=bar_close,
            )
        )
    return entries


def _insert_signals_sync(conn: Any, entries: list[LedgerEntry]) -> None:
    """Synchronous psycopg2 batch insert into signal_ledger."""
    if not entries:
        return
    params = []
    for e in entries:
        params.append(
            (
                e.signal_id,
                e.timestamp,
                e.symbol,
                e.timeframe,
                e.setup_plugin,
                e.signal_type,
                e.direction,
                e.entry_price,
                e.stop_loss,
                json.dumps(e.targets),
                e.confidence,
                e.confluence_score,
                e.regime_context,
                json.dumps(e.supporting_factors),
                e.was_selected,
                e.num_signals_bar,
                e.num_agreeing,
                e.num_conflicting,
                e.resolution_method,
                e.composite_rank,
                json.dumps(e.market_context),
                e.status,
                e.feature_ts,
                e.feature_tf,
                e.cis_score,
                json.dumps(e.bucket_scores) if e.bucket_scores is not None else None,
                e.weights_version,
                None,  # signal_quality — populated by lifecycle on exit
                e.market_entry_price,
            )
        )
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, _INSERT_SYNC_SQL, params)
    conn.commit()


def run_i7_and_persist(
    bar_history: deque,
    features: dict[str, Any],
    symbol: str,
    timeframe: str,
    timestamp: datetime,
    db_conn: Any,
    feature_ts: datetime | None = None,
    feature_tf: str | None = None,
) -> int:
    """Run I7 setup plugins on bar_history+features, aggregate, persist to signal_ledger.

    Args:
        bar_history: rolling window of bar dicts
        features: merged I1-I6 feature dict
        symbol: contract symbol
        timeframe: bar timeframe
        timestamp: bar timestamp
        db_conn: psycopg2 connection (None for dry-run)
        feature_ts: timestamp of the intelligence_features row for this bar (None if not written)
        feature_tf: timeframe of the intelligence_features row (None if not written)

    Returns:
        Number of ledger entries inserted (0 if no signals fired).
    """
    if len(bar_history) < MIN_BARS:
        return 0

    df = pd.DataFrame(list(bar_history))
    frames: dict[str, Any] = {"main": df, "features": features}

    raw_signals = []
    for name in I7_PLUGINS:
        try:
            plugin = registry.get_pattern(name)
            result = plugin.compute_full(frames)
            if result and result.get("direction", 0) != 0:
                result["setup_plugin"] = name
                raw_signals.append(result)
        except Exception:
            pass

    if not raw_signals:
        return 0

    trend_regime = float(features.get("trend_regime", 0.0))
    agg_result = aggregate(raw_signals, trend_regime=trend_regime, features=features)
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

    if entries and db_conn is not None:
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
        python production/scripts/historical_backfill.py --seed-roll-chain
    """
    import structlog
    log = structlog.get_logger(__name__)

    # Collect unique futures base symbols (order-preserving via dict.fromkeys)
    futures_bases: list[str] = list(
        dict.fromkeys(
            inst.base
            for inst in settings.contracts
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
                params.append((
                    contract["symbol"],
                    contract["base_symbol"],
                    "futures",
                    contract.get("roll_from"),
                    contract.get("roll_to"),
                    is_front_month,
                ))
            await db.execute_batch(_SEED_ROLL_CHAIN_SQL, params)
            total_contracts += len(params)
            log.debug(
                "roll_chain_seeded",
                base=base_symbol,
                contracts=[c["symbol"] for c in chain],
                front_month=chain[0]["symbol"] if chain else None,
            )
        except Exception as exc:
            log.error("seed_roll_chain_error", base=base_symbol, error=str(exc))
            print(f"  [ERROR] seed_roll_chain: {base_symbol} — {exc}")

    print(
        f"Roll chain seeded: {len(futures_bases)} base symbols, "
        f"{total_contracts} contracts total"
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
SELECT timestamp, open, high, low, close, volume
FROM market_data_ohlcv
WHERE symbol = %s AND timeframe = %s
ORDER BY timestamp ASC
"""

_FETCH_BARS_SINCE_SQL = """
SELECT timestamp, open, high, low, close, volume
FROM market_data_ohlcv
WHERE symbol = %s AND timeframe = %s AND timestamp >= %s
ORDER BY timestamp ASC
"""

_STORE_SQL = """
INSERT INTO market_data_ohlcv
    (timestamp, symbol, timeframe, open, high, low, close, volume, source)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (timestamp, symbol, timeframe) DO NOTHING
"""


def connect_db(settings: Settings) -> Any:
    """Create a synchronous psycopg2 connection from Settings DSN."""
    return psycopg2.connect(dsn=settings.database_url)


_TF_MINUTES: dict[str, int] = {"5m": 5, "15m": 15, "1h": 60, "1d": 1440}


def aggregate_bars_from_1m(bars_1m: list[dict], target_tf: str) -> list[dict]:
    """Aggregate 1m OHLCV bars to a higher timeframe by flooring to window boundaries."""
    minutes = _TF_MINUTES[target_tf]
    windows: dict[datetime, list[dict]] = {}
    for bar in bars_1m:
        ts = bar["timestamp"]
        if minutes < 1440:
            floored = ts.replace(
                minute=(ts.minute // minutes) * minutes,
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
                "source": "derived_1m",
            }
        )
    return result


def fetch_bars(conn: Any, symbol: str, timeframe: str, since: datetime | None = None) -> list[dict]:
    """Fetch stored OHLCV bars for *symbol* + *timeframe*, ordered oldest-first.

    Args:
        since: If provided, only fetch bars on or after this timestamp.
    """
    with conn.cursor() as cur:
        if since is not None:
            cur.execute(_FETCH_BARS_SINCE_SQL, (symbol, timeframe, since))
        else:
            cur.execute(_FETCH_BARS_SQL, (symbol, timeframe))
        rows = cur.fetchall()
    return [
        {
            "timestamp": row[0] if row[0].tzinfo else row[0].replace(tzinfo=UTC),
            "symbol": symbol,
            "timeframe": timeframe,
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": int(row[5]),
        }
        for row in rows
    ]


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
) -> dict[str, int]:
    """Replay bars for *symbol* through the I1→I7 pipeline.

    Processes timeframes in order: 1m first, then 5m, 15m, 1h.
    Lower-TF bar history is available as cross-TF context when processing
    higher timeframes (same as live services).

    Args:
        since: If provided, only replay bars on or after this timestamp.

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

    # Shared state across timeframes for cross-TF context
    bar_histories: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))
    intelligence_cache: dict[str, dict] = {}

    # Per-(plugin_name, symbol, tf) state dict — isolates stateful plugins (GARCH/HMM/Kalman)
    # across symbols. Scoped to this symbol so state never bleeds into the next symbol.
    plugin_states: dict[tuple[str, str, str], dict] = {}

    signal_counts: dict[str, int] = {}

    for tf in timeframes:
        if tf not in bars_by_tf:
            continue

        bars = bars_by_tf[tf]
        total_signals = 0
        print(f"  {symbol}/{tf}: replaying {len(bars):,} bars...")

        feature_buffer: list[tuple] = []

        for i, bar in enumerate(bars):
            ts = bar["timestamp"]
            history_key = f"{symbol}:{tf}"
            bar_histories[history_key].append(bar)
            history = bar_histories[history_key]

            # I1
            i1_features = run_i1_plugins(history, symbol, tf, plugin_states)
            if not i1_features:
                continue  # not enough bars yet

            # Build frames with cross-TF context (for I6 confluence)
            df = pd.DataFrame(list(history))
            frames: dict[str, Any] = {"main": df, "features": i1_features}

            tf_hierarchy = ["1m", "5m", "15m", "1h"]
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
            intelligence = run_analysis_pipeline(
                frames, intelligence_cache, symbol, tf, plugin_states
            )

            # Merge all features for I7
            all_features = {**i1_features, **intelligence}

            # Build IntelligenceEvent and buffer for batch insert
            event = _build_intelligence_event(bar, i1_features, intelligence, symbol, tf, ts)
            written_feature_ts: datetime | None = None
            if event is not None:
                feature_buffer.append(_event_to_sync_params(event))
                written_feature_ts = ts
                if len(feature_buffer) >= _FEATURE_BATCH_SIZE:
                    _insert_features_sync(db_conn, feature_buffer)
                    feature_buffer.clear()

            # I7 → signal_ledger (with feature_ts populated when features row was written)
            n = run_i7_and_persist(
                history,
                all_features,
                symbol,
                tf,
                ts,
                db_conn,
                feature_ts=written_feature_ts,
                feature_tf=(tf if written_feature_ts is not None else None),
            )
            total_signals += n

            if (i + 1) % 1000 == 0:
                print(f"    {symbol}/{tf}: {i+1:,}/{len(bars):,} bars, {total_signals} signals")

        # Flush remaining buffered feature rows
        if feature_buffer:
            _insert_features_sync(db_conn, feature_buffer)

        signal_counts[tf] = total_signals
        print(f"  {symbol}/{tf}: done — {total_signals} signals inserted")

    return signal_counts


def _replay_worker(args: tuple) -> tuple[str, int, dict[str, int]]:
    """Worker for parallel symbol replay.

    Runs in a subprocess via ProcessPoolExecutor. Opens its own psycopg2
    connection (connections cannot be shared across processes), registers
    plugins, replays the symbol, commits, and closes.

    Args:
        args: (symbol, db_url, timeframes, since_dt)

    Returns:
        (symbol, total_signals, counts_by_tf)
    """
    symbol, db_url, timeframes, since_dt = args
    conn = psycopg2.connect(dsn=db_url)
    try:
        counts = replay_symbol(symbol, conn, timeframes, since=since_dt)
        conn.commit()
        return symbol, sum(counts.values()), counts
    finally:
        conn.close()


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
        help="Max days to fetch for ALL timeframes (default: per-TF config defaults).",
    )
    parser.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated symbols, e.g. ESH6,NQH6 (default: all active)",
    )
    parser.add_argument(
        "--timeframes",
        default="1m,5m,15m,1h,1d",
        help="Comma-separated timeframes (default: 1m,5m,15m,1h,1d)",
    )
    parser.add_argument("--client-id", type=int, default=56, help="IBKR client ID (default: 56)")
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="Only fetch from IBKR → DB, skip intelligence replay",
    )
    parser.add_argument(
        "--replay-only", action="store_true", help="Only replay DB → signal_ledger, skip IBKR fetch"
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete existing signals before replay (use with --replay-only to avoid duplicates)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Parallel worker processes for replay stage (default: 4). Use 1 to disable.",
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

    timeframes = [t.strip() for t in args.timeframes.split(",") if t.strip()]

    # Filter contracts
    contracts = settings.contracts
    if args.symbols:
        wanted = {s.strip() for s in args.symbols.split(",") if s.strip()}
        contracts = [c for c in contracts if c.symbol in wanted]
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

    # --------------- Stage 1: IBKR Fetch ---------------
    if not args.replay_only:
        print("=== Stage 1: IBKR Fetch ===")
        provider = IBKRProvider(
            host=settings.ib_host,
            port=settings.ib_port,
            client_id=args.client_id,
        )
        if not asyncio.run(provider.connect()):
            print("Cannot connect to TWS — aborting fetch stage")
            if args.fetch_only:
                db_conn.close()
                return
            print("Continuing with replay-only...")
        else:
            end_dt = datetime.now(tz=UTC)
            total_bars = 0
            # Fetch each requested TF using its configured depth and contract type.
            # --days caps ALL TF fetch depths when provided; otherwise use _TF_FETCH_CONFIG
            # defaults.
            fetch_tfs = [tf for tf in timeframes if tf in _TF_FETCH_CONFIG]
            print(f"  Fetching TFs: {fetch_tfs}")
            print()
            for instrument in contracts:
                try:
                    qualified = asyncio.run(provider.qualify_instrument(instrument))
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
                            bars, metadata = fetch_per_contract(
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
                        # Skip continuous contracts for short windows (no rolls needed)
                        if fetch_days <= 14:
                            use_continuous = False
                        start_dt = (end_dt - timedelta(days=fetch_days)).replace(
                            hour=0, minute=0, second=0, microsecond=0
                        )
                        try:
                            use_continuous = use_continuous and (
                                instrument.asset_class == AssetClass.FUTURES
                            )
                            ohlcv_bars = asyncio.run(
                                provider.fetch_historical_bars(
                                    symbol=instrument.symbol,
                                    timeframe=tf,
                                    start=start_dt,
                                    end=end_dt,
                                    continuous=use_continuous,
                                )
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
                            n = store_bars(db_conn, bar_dicts, instrument.symbol, tf)
                            total_bars += n
                            if n > 0:
                                fetched_tfs.add(tf)
                            label = "continuous-adj" if use_continuous else "named"
                            print(f"  {instrument.symbol}/{tf} ({label}, {fetch_days}d): {n} bars")
                        except Exception as e:
                            print(f"  {instrument.symbol}/{tf}: error — {e}")
                        time.sleep(2)  # IBKR pacing between TF requests

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
                                deep_bars = asyncio.run(
                                    provider.fetch_historical_bars(
                                        symbol=instrument.symbol,
                                        timeframe="1m",
                                        start=deep_start,
                                        end=end_dt,
                                        continuous=False,
                                    )
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
                                n = store_bars(db_conn, deep_dicts, instrument.symbol, "1m")
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
                                print(f"  {instrument.symbol}: no 1m bars — skipping derivation")
                        else:
                            sym = instrument.symbol
                            print(f"  {sym}: all TFs fetched from IBKR — skipping derivation")

                except Exception as e:
                    print(f"  {instrument.symbol}: error — {e}")
                time.sleep(2)  # IBKR pacing between instruments
            asyncio.run(provider.disconnect())
            print(f"\nStage 1 complete: {total_bars:,} total bars stored\n")

    # --------------- Stage 2: Intelligence Replay ---------------
    if not args.fetch_only:
        print("=== Stage 2: Intelligence Replay ===")
        # When --days is provided, limit replay to that window.
        # Full-history replay (default, no --days) uses since_dt=None to read all DB bars.
        if args.days:
            since_dt = datetime.now(UTC) - timedelta(days=args.days)
            print(f"  Replaying bars since: {since_dt.date()} ({args.days}d)")
        else:
            since_dt = None

        # Clean up old signals for replayed symbols if --clean flag is set
        if args.clean:
            print("  Cleaning up old signals for replayed symbols...")
            with db_conn.cursor() as cur:
                # Delete signals AND intelligence_features for the symbols we're about to replay
                # This allows re-running backfill on specific symbols cleanly
                symbol_values = [c.symbol for c in contracts]

                # Delete all intelligence_features rows for these symbols directly.
                # The old subquery JOIN against signal_ledger only deleted rows that had
                # a matching signal, orphaning feature rows for bars where I7 fired no signals.
                cur.execute(
                    "DELETE FROM intelligence_features WHERE symbol = ANY(%s)",
                    (symbol_values,),
                )
                deleted_features = cur.rowcount

                # Delete from signal_ledger (no CASCADE - no FKs exist)
                cur.execute(
                    """
                    DELETE FROM signal_ledger
                    WHERE symbol = ANY(%s);
                """,
                    (symbol_values,),
                )
                deleted_signals = cur.rowcount

                db_conn.commit()
                print(
                    f"  Deleted {deleted_signals:,} signals + "
                    f"{deleted_features:,} intelligence feature rows"
                )

        register_all_plugins()
        grand_total = 0

        if args.workers == 1:
            for contract in contracts:
                print(f"\n{contract.symbol}:")
                counts = replay_symbol(contract.symbol, db_conn, timeframes, since=since_dt)
                symbol_total = sum(counts.values())
                grand_total += symbol_total
                print(f"  {contract.symbol} total: {symbol_total} signals")
        else:
            worker_args = [
                (contract.symbol, settings.database_url, timeframes, since_dt)
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
                        except Exception as exc:
                            print(f"\n  {symbol} FAILED: {exc}")
            except KeyboardInterrupt:
                print("\nInterrupted — workers will be terminated.")
                raise

        print(f"\nStage 2 complete: {grand_total} total signals inserted into signal_ledger")

    db_conn.close()
    print("\nBackfill complete.")


if __name__ == "__main__":
    main()
