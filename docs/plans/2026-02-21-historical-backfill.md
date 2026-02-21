# Historical Backfill Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build `production/scripts/historical_backfill.py` — a synchronous script that fetches 90 days of 1m OHLCV bars from IBKR for all 14 instruments, stores them in TimescaleDB, then replays bars through the full I1→I3→I4→I5→SMC→I6→I7 intelligence pipeline to populate `signal_ledger` for ML calibration.

**Architecture:** Synchronous Python script (no asyncio) using `psycopg2` for all DB ops and `ib_insync` for IBKR — same pattern as `simple_seeder.py`. Plugin execution (`compute_full()`) is synchronous. Signal inserts use a local sync psycopg2 function rather than the async `insert_signals()` from `signal_ledger.py`. Two CLI stages: `--fetch-only` (IBKR→DB) and `--replay-only` (DB→plugin pipeline→signal_ledger).

**Tech Stack:** Python 3.13, psycopg2, ib_insync, pandas, existing plugin registry (`src/intelligence/plugins.py`), aggregator (`src/intelligence/trading/aggregator.py`), LedgerEntry (`src/intelligence/trading/signal_ledger.py`)

---

## Important Context Before Starting

- `production/scripts/simple_seeder.py` — superseded by this script (add deprecation note at end)
- `services/indicator_service.py` — copy the `I1_PLUGINS` list exactly (all 23 names)
- `services/market_analysis_service.py` — copy `I3_PLUGINS`, `I4_PLUGINS`, `I5_PLUGINS`, `SMC_PLUGINS`, `I6_PLUGINS` lists exactly
- `services/signal_generator_service.py` — copy `I7_PLUGINS` list exactly; reference `build_ledger_entries()` and `_run_setup_plugins()` logic
- `src/intelligence/trading/signal_ledger.py` — `LedgerEntry.to_insert_params()` returns a 22-tuple; `_INSERT_SQL` uses asyncpg `$N::jsonb` syntax — **use psycopg2 `%s` placeholders instead**
- `src/intelligence/trading/aggregator.py` — `aggregate(signals, trend_regime)` returns `AggregatedResult`
- `MIN_BARS = 50` for the replay loop (same as `signal_generator_service` default)
- `bar_history` deques are `maxlen=200` per `symbol:timeframe` key
- Run tests with: `.venv/bin/pytest tests/unit/test_historical_backfill.py -v`

---

## Task 1: Script skeleton + TimeframeAggregator

**Files:**
- Create: `production/scripts/historical_backfill.py`
- Create: `tests/unit/test_historical_backfill.py`

### Step 1: Write failing tests for `time_bucket` and `aggregate_1m_to_tf`

```python
# tests/unit/test_historical_backfill.py
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "production" / "scripts"))

from historical_backfill import aggregate_1m_to_tf, time_bucket


def _bar(ts: datetime, o=100.0, h=101.0, l=99.0, c=100.5, v=1000):
    return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": v}


def _ts(hour: int, minute: int) -> datetime:
    return datetime(2026, 2, 1, hour, minute, 0, tzinfo=timezone.utc)


class TestTimeBucket:
    @pytest.mark.unit
    def test_floors_to_5m(self):
        ts = _ts(9, 33)
        assert time_bucket(ts, 5) == _ts(9, 30)

    @pytest.mark.unit
    def test_floors_to_15m(self):
        ts = _ts(9, 47)
        assert time_bucket(ts, 15) == _ts(9, 45)

    @pytest.mark.unit
    def test_already_on_boundary(self):
        ts = _ts(10, 0)
        assert time_bucket(ts, 5) == _ts(10, 0)


class TestAggregate1mToTf:
    @pytest.mark.unit
    def test_five_1m_bars_become_one_5m(self):
        bars = [_bar(_ts(9, 30 + i), o=100+i, h=101+i, l=99+i, c=100.5+i, v=100)
                for i in range(5)]
        result = aggregate_1m_to_tf(bars, 5)
        assert len(result) == 1
        r = result[0]
        assert r["timestamp"] == _ts(9, 30)
        assert r["open"] == bars[0]["open"]
        assert r["high"] == max(b["high"] for b in bars)
        assert r["low"] == min(b["low"] for b in bars)
        assert r["close"] == bars[-1]["close"]
        assert r["volume"] == 500

    @pytest.mark.unit
    def test_ten_1m_bars_become_two_5m(self):
        bars = [_bar(_ts(9, 30 + i)) for i in range(10)]
        result = aggregate_1m_to_tf(bars, 5)
        assert len(result) == 2

    @pytest.mark.unit
    def test_empty_input(self):
        assert aggregate_1m_to_tf([], 5) == []
```

### Step 2: Run tests — confirm they fail

```bash
.venv/bin/pytest tests/unit/test_historical_backfill.py -v
```
Expected: `ModuleNotFoundError: No module named 'historical_backfill'`

### Step 3: Create script skeleton with `time_bucket` and `aggregate_1m_to_tf`

```python
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
```

### Step 4: Run tests — confirm they pass

```bash
.venv/bin/pytest tests/unit/test_historical_backfill.py::TestTimeBucket \
    tests/unit/test_historical_backfill.py::TestAggregate1mToTf -v
```
Expected: 6 tests PASSED

### Step 5: Commit

```bash
git add production/scripts/historical_backfill.py tests/unit/test_historical_backfill.py
git commit -m "feat: add historical_backfill skeleton with TimeframeAggregator"
```

---

## Task 2: I1 plugin runner helper

**Files:**
- Modify: `production/scripts/historical_backfill.py` (add `run_i1_plugins`)
- Modify: `tests/unit/test_historical_backfill.py` (add tests)

### Step 1: Write failing tests

```python
# append to tests/unit/test_historical_backfill.py

import pytest
from unittest.mock import MagicMock, patch


class TestRunI1Plugins:
    @pytest.mark.unit
    def test_returns_empty_when_insufficient_bars(self):
        from historical_backfill import run_i1_plugins, MIN_BARS
        history = deque([_bar(_ts(9, i)) for i in range(MIN_BARS - 1)], maxlen=200)
        result = run_i1_plugins(history, "ESH6", "5m")
        assert result == {}

    @pytest.mark.unit
    def test_returns_features_dict_when_enough_bars(self):
        from historical_backfill import run_i1_plugins, MIN_BARS
        history = deque(
            [_bar(_ts(9, 0) if i == 0 else _ts(9 + i // 60, i % 60))
             for i in range(MIN_BARS)],
            maxlen=200
        )
        # With real plugins registered, we should get some numeric features
        register_all_plugins()
        result = run_i1_plugins(history, "ESH6", "5m")
        # At minimum should have some keys (plugins may skip on low data but dict is returned)
        assert isinstance(result, dict)

    @pytest.mark.unit
    def test_plugin_exception_does_not_propagate(self):
        from historical_backfill import run_i1_plugins, MIN_BARS
        history = deque([_bar(_ts(9, i)) for i in range(MIN_BARS)], maxlen=200)
        register_all_plugins()
        # Should not raise even if some plugins fail internally
        result = run_i1_plugins(history, "FAKE", "5m")
        assert isinstance(result, dict)
```

### Step 2: Run tests — confirm they fail

```bash
.venv/bin/pytest tests/unit/test_historical_backfill.py::TestRunI1Plugins -v
```
Expected: `ImportError: cannot import name 'run_i1_plugins'`

### Step 3: Implement `run_i1_plugins`

Add after `aggregate_1m_to_tf` in the script:

```python
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
```

### Step 4: Run tests — confirm they pass

```bash
.venv/bin/pytest tests/unit/test_historical_backfill.py::TestRunI1Plugins -v
```
Expected: 3 tests PASSED

### Step 5: Commit

```bash
git add production/scripts/historical_backfill.py tests/unit/test_historical_backfill.py
git commit -m "feat: add run_i1_plugins helper to backfill"
```

---

## Task 3: Analysis pipeline runner (I3→I6)

**Files:**
- Modify: `production/scripts/historical_backfill.py` (add `run_analysis_pipeline`)
- Modify: `tests/unit/test_historical_backfill.py` (add tests)

### Step 1: Write failing tests

```python
# append to tests/unit/test_historical_backfill.py

class TestRunAnalysisPipeline:
    @pytest.mark.unit
    def test_returns_dict(self):
        from historical_backfill import run_analysis_pipeline
        register_all_plugins()
        df = pd.DataFrame([_bar(_ts(9, i)) for i in range(60)])
        frames = {"main": df, "features": {"rsi_14": 55.0, "atr_14": 2.5}}
        intel_cache: dict = {}
        result = run_analysis_pipeline(frames, intel_cache, "ESH6", "5m")
        assert isinstance(result, dict)

    @pytest.mark.unit
    def test_populates_intelligence_cache(self):
        from historical_backfill import run_analysis_pipeline
        register_all_plugins()
        df = pd.DataFrame([_bar(_ts(9, i)) for i in range(60)])
        frames = {"main": df, "features": {"rsi_14": 55.0}}
        intel_cache: dict = {}
        run_analysis_pipeline(frames, intel_cache, "ESH6", "5m")
        assert "ESH6" in intel_cache
        assert "5m" in intel_cache["ESH6"]

    @pytest.mark.unit
    def test_plugin_exception_does_not_propagate(self):
        from historical_backfill import run_analysis_pipeline
        frames = {"main": pd.DataFrame(), "features": {}}
        intel_cache: dict = {}
        # Empty DataFrame may cause some plugins to raise — should not propagate
        result = run_analysis_pipeline(frames, intel_cache, "ESH6", "5m")
        assert isinstance(result, dict)
```

### Step 2: Run tests — confirm they fail

```bash
.venv/bin/pytest tests/unit/test_historical_backfill.py::TestRunAnalysisPipeline -v
```
Expected: `ImportError: cannot import name 'run_analysis_pipeline'`

### Step 3: Implement `run_analysis_pipeline`

Add after `run_i1_plugins`:

```python
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
```

### Step 4: Run tests — confirm they pass

```bash
.venv/bin/pytest tests/unit/test_historical_backfill.py::TestRunAnalysisPipeline -v
```
Expected: 3 tests PASSED

### Step 5: Commit

```bash
git add production/scripts/historical_backfill.py tests/unit/test_historical_backfill.py
git commit -m "feat: add run_analysis_pipeline helper to backfill (I3-I6)"
```

---

## Task 4: Signal generation + sync DB insert

**Files:**
- Modify: `production/scripts/historical_backfill.py` (add `_build_ledger_entries`, `_insert_signals_sync`, `run_i7_and_persist`)
- Modify: `tests/unit/test_historical_backfill.py` (add tests)

### Step 1: Write failing tests

```python
# append to tests/unit/test_historical_backfill.py

class TestBuildLedgerEntries:
    def _make_result(self, n_signals=2):
        from src.intelligence.trading.aggregator import AggregatedResult
        sig = {
            "setup_plugin": "trad_TrendFollowing",
            "signal_type": "trend_follow",
            "direction": 1,
            "entry_price": 5100.0,
            "stop_loss": 5085.0,
            "targets": [5115.0, 5130.0],
            "confidence": 0.75,
            "confluence_score": 0.6,
            "regime_context": "bullish",
            "supporting_factors": ["ema_cross"],
            "composite_rank": 1,
        }
        return AggregatedResult(
            selected_signal=sig,
            all_ranked=[sig],
            num_signals_fired=n_signals,
            num_agreeing=n_signals,
            num_conflicting=0,
            resolution_method="sole",
        )

    @pytest.mark.unit
    def test_returns_one_entry_per_ranked_signal(self):
        from historical_backfill import _build_ledger_entries
        result = self._make_result(n_signals=1)
        entries = _build_ledger_entries(result, "ESH6", "5m", _ts(9, 30), {})
        assert len(entries) == 1

    @pytest.mark.unit
    def test_selected_signal_has_was_selected_true(self):
        from historical_backfill import _build_ledger_entries
        result = self._make_result()
        entries = _build_ledger_entries(result, "ESH6", "5m", _ts(9, 30), {})
        selected = [e for e in entries if e.was_selected]
        assert len(selected) == 1

    @pytest.mark.unit
    def test_empty_result_returns_empty_list(self):
        from historical_backfill import _build_ledger_entries
        from src.intelligence.trading.aggregator import AggregatedResult
        result = AggregatedResult(
            selected_signal=None, all_ranked=[], num_signals_fired=0,
            num_agreeing=0, num_conflicting=0, resolution_method="no_signal",
        )
        entries = _build_ledger_entries(result, "ESH6", "5m", _ts(9, 30), {})
        assert entries == []
```

### Step 2: Run tests — confirm they fail

```bash
.venv/bin/pytest tests/unit/test_historical_backfill.py::TestBuildLedgerEntries -v
```
Expected: `ImportError: cannot import name '_build_ledger_entries'`

### Step 3: Implement `_build_ledger_entries`, `_insert_signals_sync`, `run_i7_and_persist`

Add to the script:

```python
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
```

### Step 4: Run tests — confirm they pass

```bash
.venv/bin/pytest tests/unit/test_historical_backfill.py::TestBuildLedgerEntries -v
```
Expected: 3 tests PASSED

### Step 5: Commit

```bash
git add production/scripts/historical_backfill.py tests/unit/test_historical_backfill.py
git commit -m "feat: add signal generation + sync ledger insert to backfill"
```

---

## Task 5: DB fetch layer

**Files:**
- Modify: `production/scripts/historical_backfill.py` (add `connect_db`, `fetch_1m_bars`, `store_bars`)
- Modify: `tests/unit/test_historical_backfill.py` (add tests using mock)

### Step 1: Write failing tests

```python
# append to tests/unit/test_historical_backfill.py

from unittest.mock import MagicMock, call


class TestFetchAndStoreBars:
    @pytest.mark.unit
    def test_fetch_1m_bars_queries_correct_table(self):
        from historical_backfill import fetch_1m_bars
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            (datetime(2026, 2, 1, 9, 30, tzinfo=timezone.utc), 100.0, 101.0, 99.0, 100.5, 1000)
        ]
        rows = fetch_1m_bars(mock_conn, "ESH6", days=1)
        assert len(rows) == 1
        assert rows[0]["symbol"] == "ESH6"
        assert rows[0]["timeframe"] == "1m"
        assert "timestamp" in rows[0]

    @pytest.mark.unit
    def test_store_bars_calls_execute_batch(self):
        from historical_backfill import store_bars
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        bars = [{"timestamp": _ts(9, 30), "open": 100.0, "high": 101.0,
                  "low": 99.0, "close": 100.5, "volume": 1000}]
        store_bars(mock_conn, bars, symbol="ESH6", timeframe="5m")
        mock_conn.commit.assert_called_once()
```

### Step 2: Run tests — confirm they fail

```bash
.venv/bin/pytest tests/unit/test_historical_backfill.py::TestFetchAndStoreBars -v
```
Expected: `ImportError: cannot import name 'fetch_1m_bars'`

### Step 3: Implement DB layer functions

```python
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
```

### Step 4: Run tests — confirm they pass

```bash
.venv/bin/pytest tests/unit/test_historical_backfill.py::TestFetchAndStoreBars -v
```
Expected: 2 tests PASSED

### Step 5: Commit

```bash
git add production/scripts/historical_backfill.py tests/unit/test_historical_backfill.py
git commit -m "feat: add DB fetch/store layer to backfill"
```

---

## Task 6: Replay orchestrator (per symbol × timeframe)

**Files:**
- Modify: `production/scripts/historical_backfill.py` (add `replay_symbol`)

No separate unit test for this (integration logic that glues Tasks 1-5 together). Verified by end-to-end run in Task 8.

### Step 1: Implement `replay_symbol`

Add to the script:

```python
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
```

### Step 2: Commit

```bash
git add production/scripts/historical_backfill.py
git commit -m "feat: add replay_symbol orchestrator to backfill"
```

---

## Task 7: IBKR fetch stage

**Files:**
- Modify: `production/scripts/historical_backfill.py` (add `IBKRFetcher` class)

No unit test — requires live TWS. Verified manually in Task 8.

### Step 1: Implement `IBKRFetcher`

```python
class IBKRFetcher:
    """Synchronous IBKR fetcher using ib_insync."""

    def __init__(self, host: str, port: int, client_id: int):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib = None

    def connect(self) -> bool:
        from ib_insync import IB
        self.ib = IB()
        try:
            self.ib.connect(host=self.host, port=self.port,
                            clientId=self.client_id, timeout=30)
            return self.ib.isConnected()
        except Exception as e:
            print(f"  IBKR connection error: {e}")
            return False

    def disconnect(self) -> None:
        if self.ib and self.ib.isConnected():
            self.ib.disconnect()

    def fetch_and_store(
        self,
        contract_cfg: Any,  # IBKRContract from Settings
        days: int,
        db_conn: Any,
    ) -> int:
        """Fetch *days* of 1m bars for *contract_cfg* and upsert into DB.

        Returns number of bars stored.
        """
        from ib_insync import Future

        symbol = contract_cfg.symbol
        print(f"  Fetching {days}D of 1m bars for {symbol}...")

        try:
            contract = Future(
                symbol=contract_cfg.base,
                lastTradeDateOrContractMonth=contract_cfg.expiry,
                exchange=contract_cfg.exchange,
            )
            details = self.ib.reqContractDetails(contract)
            if not details:
                print(f"  {symbol}: no contract details — skipping")
                return 0

            qualified = details[0].contract
            bars = self.ib.reqHistoricalData(
                contract=qualified,
                endDateTime="",
                durationStr=f"{days} D",
                barSizeSetting="1 min",
                whatToShow="TRADES",
                useRTH=False,  # include extended hours for metals/energy/rates
            )

            if not bars:
                print(f"  {symbol}: no data returned")
                return 0

            bar_dicts = [
                {
                    "timestamp": (
                        bar.date if hasattr(bar.date, "tzinfo")
                        else datetime.fromisoformat(str(bar.date)).replace(tzinfo=timezone.utc)
                    ),
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": float(bar.close),
                    "volume": int(bar.volume),
                }
                for bar in bars
            ]

            stored = store_bars(db_conn, bar_dicts, symbol, "1m")
            print(f"  {symbol}: {len(bars)} bars fetched, {stored} stored")
            return stored

        except Exception as e:
            print(f"  {symbol}: fetch error — {e}")
            return 0
```

### Step 2: Commit

```bash
git add production/scripts/historical_backfill.py
git commit -m "feat: add IBKRFetcher to backfill"
```

---

## Task 8: Main function + CLI + deprecation note

**Files:**
- Modify: `production/scripts/historical_backfill.py` (add `main()`)
- Modify: `production/scripts/simple_seeder.py` (add deprecation header)

### Step 1: Implement `main()`

```python
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Historical Backfill — fetch IBKR bars + replay intelligence pipeline"
    )
    parser.add_argument("--days", type=int, default=90,
                        help="Days of history to fetch (default: 90)")
    parser.add_argument("--symbols", default=None,
                        help="Comma-separated symbols, e.g. ESH6,NQH6 (default: all 14)")
    parser.add_argument("--timeframes", default="1m,5m,15m,1h",
                        help="Comma-separated timeframes for replay (default: 1m,5m,15m,1h)")
    parser.add_argument("--client-id", type=int, default=56,
                        help="IBKR client ID (default: 56)")
    parser.add_argument("--fetch-only", action="store_true",
                        help="Only fetch from IBKR → DB, skip intelligence replay")
    parser.add_argument("--replay-only", action="store_true",
                        help="Only replay DB → signal_ledger, skip IBKR fetch")
    args = parser.parse_args()

    settings = Settings()
    timeframes = [t.strip() for t in args.timeframes.split(",") if t.strip()]

    # Filter contracts
    contracts = settings.contracts
    if args.symbols:
        wanted = {s.strip() for s in args.symbols.split(",") if s.strip()}
        contracts = [c for c in contracts if c.symbol in wanted]
        if not contracts:
            print(f"No matching contracts for: {args.symbols}")
            return

    print(f"Historical Backfill Pipeline")
    print(f"  Contracts : {[c.symbol for c in contracts]}")
    print(f"  Days      : {args.days}")
    print(f"  Timeframes: {timeframes}")
    print(f"  Stages    : {'fetch+replay' if not (args.fetch_only or args.replay_only) else 'fetch-only' if args.fetch_only else 'replay-only'}")
    print()

    db_conn = connect_db(settings)

    # --------------- Stage 1: IBKR Fetch ---------------
    if not args.replay_only:
        print("=== Stage 1: IBKR Fetch ===")
        fetcher = IBKRFetcher(
            host=settings.ib_host,
            port=settings.ib_port,
            client_id=args.client_id,
        )
        if not fetcher.connect():
            print("Cannot connect to TWS — aborting fetch stage")
            if args.fetch_only:
                db_conn.close()
                return
            print("Continuing with replay-only...")
        else:
            total_bars = 0
            for contract in contracts:
                n = fetcher.fetch_and_store(contract, args.days, db_conn)
                total_bars += n
                time.sleep(2)  # IBKR pacing
            fetcher.disconnect()
            print(f"\nStage 1 complete: {total_bars:,} total bars stored\n")

    # --------------- Stage 2: Intelligence Replay ---------------
    if not args.fetch_only:
        print("=== Stage 2: Intelligence Replay ===")
        grand_total = 0
        for contract in contracts:
            print(f"\n{contract.symbol}:")
            counts = replay_symbol(contract.symbol, db_conn, timeframes)
            symbol_total = sum(counts.values())
            grand_total += symbol_total
            print(f"  {contract.symbol} total: {symbol_total} signals")

        print(f"\nStage 2 complete: {grand_total} total signals inserted into signal_ledger")

    db_conn.close()
    print("\nBackfill complete.")


if __name__ == "__main__":
    main()
```

### Step 2: Run full unit test suite — confirm all new tests pass

```bash
.venv/bin/pytest tests/unit/test_historical_backfill.py -v
```
Expected: All tests PASSED

### Step 3: Add deprecation note to `simple_seeder.py`

At the very top of `production/scripts/simple_seeder.py`, after the docstring, add:

```python
# DEPRECATED: This script is superseded by historical_backfill.py which:
#   - Uses Settings.contracts (all 14 current instruments, auto-updated expiries)
#   - Runs the full I1→I7 intelligence pipeline to populate signal_ledger
#   - Supports multi-timeframe (1m/5m/15m/1h) bar generation
# Use: python production/scripts/historical_backfill.py --days 90
```

### Step 4: Run full unit test suite — confirm nothing broke

```bash
.venv/bin/pytest tests/unit/ -v --tb=short 2>&1 | tail -20
```
Expected: 459+ tests passing, 0 failures

### Step 5: Final commit

```bash
git add production/scripts/historical_backfill.py production/scripts/simple_seeder.py
git commit -m "feat: complete historical_backfill.py — canonical IBKR seeder + intelligence replay

Replaces simple_seeder.py. Fetches N days of 1m bars for all 14 active
instruments from IBKR, stores in TimescaleDB, then replays through full
I1→I3→I4→I5→SMC→I6→I7 pipeline to populate signal_ledger for ML calibration.

CLI: --days, --symbols, --timeframes, --fetch-only, --replay-only"
```

---

## End-to-End Verification (manual)

Once infrastructure is running (Dragonfly, PostgreSQL, venv active):

```bash
# Quick smoke test — 7 days, ES only
python production/scripts/historical_backfill.py --days 7 --symbols ESH6

# Check what landed in DB
psql -U postgres -d indicagent -c "
SELECT symbol, timeframe, COUNT(*) as bars, MIN(timestamp), MAX(timestamp)
FROM market_data_ohlcv GROUP BY symbol, timeframe ORDER BY symbol, timeframe;"

# Check signals generated
psql -U postgres -d indicagent -c "
SELECT symbol, timeframe, COUNT(*) as signals, MIN(timestamp), MAX(timestamp)
FROM signal_ledger GROUP BY symbol, timeframe ORDER BY symbol, timeframe;"

# Full run — all 14 instruments, 90 days
python production/scripts/historical_backfill.py --days 90
```

Expected signal count: ~30 signals/trading day × 90 days × some timeframe multiplier = 2,000+ rows in signal_ledger.
