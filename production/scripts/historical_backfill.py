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
