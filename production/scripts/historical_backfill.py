#!/usr/bin/env python3
"""
Historical Backfill Pipeline

Fetches N days of 1m OHLCV bars from IBKR for all 14 active instruments,
stores them in TimescaleDB, then replays bars through the full
I1→I3→I4→I5→SMC→I6→I7 intelligence pipeline to populate signal_ledger.

Replaces: production/scripts/simple_seeder.py (retired)

Usage:
    python production/scripts/historical_backfill.py --days 90
    python production/scripts/historical_backfill.py --days 90 --fetch-only
    python production/scripts/historical_backfill.py --replay-only
    python production/scripts/historical_backfill.py --symbols ESH6,NQH6 --days 30
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg2
import psycopg2.extras

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd

from src.config.settings import Settings
from src.intelligence.plugins import registry
from src.intelligence.register_plugins import register_all_plugins
from src.intelligence.trading.aggregator import AggregatedResult, aggregate
from src.intelligence.trading.signal_ledger import LedgerEntry

# ---------------------------------------------------------------------------
# Plugin lists — keep in sync with services
# ---------------------------------------------------------------------------
I1_PLUGINS = [
    "RSI", "MovingAverages", "MAComposite", "MACD", "ATR", "BollingerBands",
    "Stochastic", "CCI", "WilliamsR", "MFI", "OBV", "VWAP", "Supertrend",
    "ADX", "KeltnerChannels", "DonchianChannels", "ROC_PPO",
    "ind_CMF", "ind_Aroon", "ind_HistoricalVolatility",
    "ind_ChandelierExit", "ind_ParabolicSAR", "ind_StochRSI",
]
I3_PLUGINS = ["struct_SwingDetector", "struct_SupportResistance", "struct_TrendStructure"]
I4_PLUGINS = [
    "ctx_VolatilityRegime", "ctx_TrendRegime", "ctx_MomentumContext", "ctx_GARCHVolatility",
]
I5_PLUGINS = [
    "RSIDivergence", "BollingerSqueeze", "VolumeDivergence", "Confluence", "TrendConfluence",
]
SMC_PLUGINS = [
    "smc_BOSCHoCH", "smc_FairValueGap", "smc_OrderBlocks",
    "smc_LiquiditySweeps", "smc_BOCPDChangePoint",
]
I6_PLUGINS = ["i6_CrossTimeframeConfluence"]
I7_PLUGINS = [
    "trad_TrendFollowing", "trad_MeanReversion", "trad_LiquiditySweepReclaim",
    "trad_MTFAlignment", "trad_SqueezeExpansion", "trad_VWAPDeviation",
    "trad_MomentumBreakout",
]

MIN_BARS = 50
TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}
DEFAULT_TIMEFRAMES = ["1m", "5m", "15m", "1h"]


# ---------------------------------------------------------------------------
# Timeframe aggregation
# ---------------------------------------------------------------------------

def time_bucket(ts: datetime, minutes: int) -> datetime:
    """Floor a datetime to the nearest N-minute boundary (UTC)."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    epoch = ts.timestamp()
    bucket_seconds = minutes * 60
    floored = (epoch // bucket_seconds) * bucket_seconds
    return datetime.fromtimestamp(floored, tz=timezone.utc)


def aggregate_1m_to_tf(bars: list[dict], minutes: int) -> list[dict]:
    """Aggregate a list of 1m OHLCV bar dicts into N-minute bars.

    Args:
        bars: List of dicts with keys: timestamp, open, high, low, close, volume.
              timestamp may be datetime or ISO string.
        minutes: Target timeframe in minutes (e.g. 5, 15, 60).

    Returns:
        List of aggregated bar dicts, sorted by timestamp ascending.
    """
    if not bars:
        return []

    buckets: dict[datetime, list[dict]] = defaultdict(list)
    for bar in bars:
        ts = bar["timestamp"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        bucket = time_bucket(ts, minutes)
        buckets[bucket].append(bar)

    result = []
    for bucket_ts in sorted(buckets):
        group = buckets[bucket_ts]
        result.append({
            "timestamp": bucket_ts,
            "open": float(group[0]["open"]),
            "high": float(max(b["high"] for b in group)),
            "low": float(min(b["low"] for b in group)),
            "close": float(group[-1]["close"]),
            "volume": int(sum(b["volume"] for b in group)),
        })
    return result


def run_i1_plugins(
    bar_history: deque,
    symbol: str,
    timeframe: str,
) -> dict[str, Any]:
    """Run all I1 indicator plugins on the current bar history.

    Returns empty dict if fewer than MIN_BARS are available (indicators
    need warmup history to produce meaningful values).
    """
    if len(bar_history) < MIN_BARS:
        return {}

    df = pd.DataFrame(list(bar_history))
    frames: dict[str, Any] = {"main": df, "features": {}}
    features: dict[str, Any] = {}

    for name in I1_PLUGINS:
        try:
            plugin = registry.get_indicator(name)
            out = plugin.compute_full(frames)
            if out:
                features.update({k: v for k, v in out.items()
                                  if isinstance(v, (int, float, str, bool))})
                frames["features"] = features
        except Exception:
            pass  # individual plugin failure never kills the replay

    return features


def run_analysis_pipeline(
    frames: dict[str, Any],
    intelligence_cache: dict[str, dict[str, Any]],
    symbol: str,
    timeframe: str,
) -> dict[str, Any]:
    """Run I3 → I4 → I5 → SMC → I6 plugins in tier order.

    Mutates frames["features"] in-place (same as market_analysis_service).
    Caches result in intelligence_cache[symbol][timeframe] for I6 cross-TF plugin.

    Returns:
        Merged intelligence dict from all tiers.
    """
    features = dict(frames.get("features", {}))
    frames["features"] = features
    intelligence: dict[str, Any] = {}

    tier_sequence = [
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
                out = plugin.compute_full(frames)
                if out:
                    intelligence.update(out)
                    features.update(out)
                    frames["features"] = features
            except Exception:
                pass

    intelligence_cache.setdefault(symbol, {})[timeframe] = intelligence
    return intelligence


# ---------------------------------------------------------------------------
# Signal generation + sync DB insert
# ---------------------------------------------------------------------------

MARKET_CONTEXT_KEYS = (
    "trend_regime", "volatility_regime", "trend_confidence",
    "atr_14", "rsi_14", "ctf_score", "swing_pattern",
    "trend_strength", "volatility_percentile", "hmm_regime_state",
)

_INSERT_SYNC_SQL = """
INSERT INTO signal_ledger (
    signal_id, timestamp, symbol, timeframe, setup_plugin, signal_type,
    direction, entry_price, stop_loss, targets,
    confidence, confluence_score, regime_context, supporting_factors,
    was_selected, num_signals_bar, num_agreeing, num_conflicting,
    resolution_method, composite_rank, market_context, status
) VALUES (
    %s::uuid, %s, %s, %s, %s, %s,
    %s, %s, %s, %s::jsonb,
    %s, %s, %s, %s::jsonb,
    %s, %s, %s, %s,
    %s, %s, %s::jsonb, %s
) ON CONFLICT DO NOTHING
"""


def _build_ledger_entries(
    result: AggregatedResult,
    symbol: str,
    timeframe: str,
    timestamp: datetime,
    features: dict[str, Any],
) -> list[LedgerEntry]:
    """Convert an AggregatedResult into LedgerEntry objects for DB insertion."""
    if not result.all_ranked:
        return []

    market_ctx = {k: features[k] for k in MARKET_CONTEXT_KEYS if k in features}

    entries = []
    for sig in result.all_ranked:
        rank = sig.get("composite_rank", 99)
        was_selected = rank == 1 and result.selected_signal is not None
        entries.append(LedgerEntry(
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
        ))
    return entries


def _insert_signals_sync(conn: Any, entries: list[LedgerEntry]) -> None:
    """Synchronous psycopg2 batch insert into signal_ledger."""
    if not entries:
        return
    params = []
    for e in entries:
        params.append((
            e.signal_id, e.timestamp, e.symbol, e.timeframe,
            e.setup_plugin, e.signal_type, e.direction, e.entry_price, e.stop_loss,
            json.dumps(e.targets), e.confidence, e.confluence_score,
            e.regime_context, json.dumps(e.supporting_factors),
            e.was_selected, e.num_signals_bar, e.num_agreeing, e.num_conflicting,
            e.resolution_method, e.composite_rank, json.dumps(e.market_context),
            e.status,
        ))
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
) -> int:
    """Run I7 setup plugins on bar_history+features, aggregate, persist to signal_ledger.

    Returns number of ledger entries inserted (0 if no signals fired).
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
    agg_result = aggregate(raw_signals, trend_regime=trend_regime)
    entries = _build_ledger_entries(agg_result, symbol, timeframe, timestamp, features)

    if entries and db_conn is not None:
        _insert_signals_sync(db_conn, entries)

    return len(entries)


# ---------------------------------------------------------------------------
# DB fetch/store layer
# ---------------------------------------------------------------------------

_FETCH_SQL = """
SELECT timestamp, open, high, low, close, volume
FROM market_data_ohlcv
WHERE symbol = %s AND timeframe = '1m'
  AND timestamp >= NOW() - INTERVAL '%s days'
ORDER BY timestamp ASC
"""

_STORE_SQL = """
INSERT INTO market_data_ohlcv
    (timestamp, symbol, timeframe, open, high, low, close, volume, source)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (timestamp, symbol, timeframe) DO NOTHING
"""


def connect_db(settings: Settings) -> Any:
    """Create a synchronous psycopg2 connection from Settings."""
    # Parse DATABASE_URL: postgresql://user:pass@host:port/dbname
    url = settings.database_url
    # Simple parse — production URLs follow this pattern
    url = url.replace("postgresql://", "").replace("postgres://", "")
    userpass, rest = url.split("@", 1)
    user, password = userpass.split(":", 1)
    hostport_db = rest.split("/", 1)
    hostport = hostport_db[0]
    dbname = hostport_db[1] if len(hostport_db) > 1 else "indicagent"
    host, port = (hostport.split(":", 1) if ":" in hostport else (hostport, "5432"))

    return psycopg2.connect(
        host=host, port=int(port), database=dbname, user=user, password=password
    )


def fetch_1m_bars(conn: Any, symbol: str, days: int) -> list[dict]:
    """Fetch all 1m OHLCV bars for *symbol* covering the last *days* calendar days."""
    with conn.cursor() as cur:
        cur.execute(_FETCH_SQL, (symbol, days))
        rows = cur.fetchall()
    return [
        {
            "timestamp": row[0] if row[0].tzinfo else row[0].replace(tzinfo=timezone.utc),
            "symbol": symbol,
            "timeframe": "1m",
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": int(row[5]),
        }
        for row in rows
    ]


def store_bars(conn: Any, bars: list[dict], symbol: str, timeframe: str) -> int:
    """Upsert bars into market_data_ohlcv. Returns count inserted."""
    if not bars:
        return 0
    params = [
        (b["timestamp"], symbol, timeframe,
         b["open"], b["high"], b["low"], b["close"], b["volume"],
         "historical_backfill")
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
) -> dict[str, int]:
    """Replay all bars for *symbol* through the I1→I7 pipeline.

    Processes timeframes in order: 1m first, then 5m, 15m, 1h.
    Lower-TF bar history is available as cross-TF context when processing
    higher timeframes (same as live services).

    Returns:
        dict mapping timeframe → number of ledger entries inserted.
    """
    if timeframes is None:
        timeframes = DEFAULT_TIMEFRAMES

    register_all_plugins()

    # Fetch all 1m bars once
    bars_1m = fetch_1m_bars(db_conn, symbol, days=9999)  # get all available
    if not bars_1m:
        print(f"  {symbol}: no 1m bars in DB — run fetch stage first")
        return {}

    print(f"  {symbol}: {len(bars_1m):,} 1m bars loaded")

    # Aggregate to higher timeframes upfront
    bars_by_tf: dict[str, list[dict]] = {"1m": bars_1m}
    for tf in ["5m", "15m", "1h"]:
        if tf in timeframes:
            minutes = TF_MINUTES[tf]
            bars_by_tf[tf] = aggregate_1m_to_tf(bars_1m, minutes)
            print(f"  {symbol}: {len(bars_by_tf[tf]):,} {tf} bars aggregated")

    # Store aggregated bars in DB
    for tf, bars in bars_by_tf.items():
        if tf != "1m":
            stored = store_bars(db_conn, bars, symbol, tf)
            print(f"  {symbol}: {stored} {tf} bars stored")

    # Shared state across timeframes for cross-TF context
    bar_histories: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))
    intelligence_cache: dict[str, dict] = {}

    signal_counts: dict[str, int] = {}

    for tf in timeframes:
        if tf not in bars_by_tf:
            continue

        bars = bars_by_tf[tf]
        total_signals = 0
        print(f"  {symbol}/{tf}: replaying {len(bars):,} bars...")

        for i, bar in enumerate(bars):
            ts = bar["timestamp"]
            history_key = f"{symbol}:{tf}"
            bar_histories[history_key].append(bar)
            history = bar_histories[history_key]

            # I1
            i1_features = run_i1_plugins(history, symbol, tf)
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

            # I3 → I6
            intelligence = run_analysis_pipeline(frames, intelligence_cache, symbol, tf)

            # Merge all features for I7
            all_features = {**i1_features, **intelligence}

            # I7 → signal_ledger
            n = run_i7_and_persist(history, all_features, symbol, tf, ts, db_conn)
            total_signals += n

            if (i + 1) % 1000 == 0:
                print(f"    {symbol}/{tf}: {i+1:,}/{len(bars):,} bars, {total_signals} signals so far")

        signal_counts[tf] = total_signals
        print(f"  {symbol}/{tf}: done — {total_signals} signals inserted")

    return signal_counts
