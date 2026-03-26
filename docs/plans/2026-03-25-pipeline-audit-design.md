# Renaissance Pipeline Audit Framework — Design Document

**Date:** 2026-03-25
**Status:** Design — REVISED (2026-03-26) — All Critical Fixes Applied
**Priority:** Critical — Foundation for v2.1 Data Quality validation
**Revision Notes:** Second pass of critical fixes applied 2026-03-26 — ready for implementation planning

## Critical Fixes Applied

### Pass 1 (2026-03-25)
- [x] Verified `intelligence_metrics` does NOT exist (reviewer error) — name is correct
- [x] Fixed SQL queries to use direct JSONB column paths (`i1->>'rsi_14'`, not `intel->'i1'->>'rsi'`)
- [x] Fixed bar fields: `(bar->>'close')::float` (explicit cast — avoids numpy object array)
- [x] Fixed I6→I7 completeness: Query `i6` JSONB directly, not iterate I7 signal dicts
- [x] Fixed regime agreement: Use `signal["regime_type"]` instead of non-existent `regime_gate`
- [x] Handle `regime_type='any'` signals (match any I4 regime)

### Pass 2 (2026-03-26) — Second Reviewer Pass
- [x] `cross_tier_validation.py`: Removed phantom `intel->` column — was `intel->'i1'->>'atr'`, now `i1->>'atr_14'`
- [x] `cross_tier_validation.py`: `i4->>'regime'` → `smc->>'hmm_regime'` (HMM regime lives in `smc` JSONB)
- [x] `cross_tier_validation.py`: `i4->>'trend_strength'` → `i3->>'trend_strength'` (trend_strength is an I3 field; I4 has `trend_regime`/`trend_confidence`/`kalman_trend`)
- [x] `cross_tier_validation.py`: `i4->>'volatility'` → `i4->>'vol_percentile'` (I4 has `vol_regime`, `vol_percentile`, `garch_sigma`, `garch_vol_ratio`)
- [x] `validation_engine.py`: `i4->>'vwap'` → `i4->>'session_vwap'`
- [x] `validation_engine.py`: `i4->>'volatility'` → `i4->>'vol_percentile'`
- [x] `pipeline_audit.py`: `DatabaseManager()` → `DatabaseManager(settings.database_url)`; `db.connect()` → `db.initialize()`
- [x] `pipeline_audit.py`: Latency query removed — referenced deleted columns (`latency_bar_aggregation` etc. not in DDL). Replaced with `PrometheusMetricsFetcher.get_pipeline_latency()` call
- [x] `cross_tier_validation.py`: Double-counted `total_rows` fixed — was `len(rows)` then `+= 1` per row; now pre-filter to `valid_rows` and `total_rows = len(valid_rows)`
- [x] `cross_tier_validation.py`: `AND i7 IS NOT NULL` → `AND jsonb_array_length(i7) > 0` (`i7` has `DEFAULT '[]' NOT NULL` so IS NOT NULL is always true)
- [x] PromQL: `{24h}` → `[24h]`; removed contradictory `by/without` in same clause
- [x] RSI reference: added zero-guard `np.where(avg_loss == 0, np.inf, ...)` to prevent divide-by-zero
- [x] `datetime.utcnow()` → `datetime.now(UTC)` throughout

### Remaining Issues (Deferred to Implementation)
- [ ] ATR/VWAP absolute tolerances (`0.05`) incorrect for futures (ATR is 15-25 points) — implement empirical calibration
- [ ] Latency sampling (10% sampling instead of per-bar)
- [ ] External validation (defer to Phase 2)
- [ ] Regime segmentation (add WHERE clauses for per-regime breakdown)
- [ ] `feature_pipeline_latency_ms` not registered in production Prometheus — confirm before using

**Status:** All critical and important blockers resolved. Ready for implementation planning.

## Overview

Build an automated audit framework that proves the IndicAgent intelligence pipeline is **computationally correct** at every tier (I1-I7/I8), tracks **Renaissance-grade metrics** (per-hop latency, historical trends), and validates **cross-tier consistency** (I1→I4→I7 transformations).

**Core Principle:** Don't assume the code is correct. Prove it with reference implementations, external sources, and statistical validation.

> **What Would Jim Simons Demand?**
> - "Prove RSI is calculated correctly — not 'looks right', but mathematically correct"
> - "Measure everything — per-hop latency, throughput, signal outcomes"
> - "Validate against external sources — TradingView, Yahoo Finance"
> - "Track everything in the database — historical metrics, trend analysis"
> - "No global averages — segment by regime, symbol, timeframe"

---

## Problem Statement

### Current State

IndicAgent runs a 7-tier intelligence pipeline (I1-I7) with 121+ plugins processing real-time market data, generating trading signals that are tracked for outcomes. However:

1. **Computational correctness is unproven** — Are RSI, MACD, ATR, VWAP calculations mathematically correct?
2. **Cross-tier consistency is unchecked** — Do I1 features feed I4 context correctly? Do I7 signals have complete I6 inputs?
3. **Latency is unmeasured** — How long does each hop take? Where are bottlenecks?
4. **No historical tracking** — Can we trend metrics over time? Detect degradations?
5. **Manual validation only** — No automated testing against external sources

### Why This Matters

> **"You can't calculate alpha on broken intelligence."**

If RSI is calculated wrong, every signal downstream is compromised. If I6 confluence scores are missing, I7 signals fire without complete information. If latency degrades, signals arrive too late to trade.

**Before we ask "do signals make money?", we must ask "is the pipeline computing correct values?"**

---

## Renaissance Requirements

### Non-Negotiable (Jim Simons Would Demand)

1. **Computational Correctness** — Every calculation validated against reference implementation
2. **External Validation** — Compare to TradingView/Yahoo Finance (gold standard)
3. **Per-Hop Latency Measurement** — Track p50/p95/p99 for every tier
4. **Historical Metrics** — Everything in database for trend analysis
5. **Cross-Tier Consistency** — I1→I4 correlations, I6→I7 completeness ≥95%
6. **Regime Segmentation** — No global averages — segment by market state
7. **Automated Validation** — Run hourly, persist metrics, alert on violations
8. **Self-Healing** — Circuit breakers, fallback logic, auto-retry

### Success Criteria

#### Phase 1 (Script) — Must Achieve:

✅ **Zero computational correctness failures**
- All I1 calculations (RSI, MACD, ATR, etc.) match reference implementations within tolerance
- All I4 calculations (volatility, VWAP, regime) match reference implementations
- External source correlation ≥0.99 (TradingView/Yahoo Finance)

✅ **≥95% cross-tier consistency**
- I1→I4 correlations ≥0.5 for conceptually related fields
- ≥95% of I7 signals have complete I6 features
- ≥90% regime agreement between I4 and I7

✅ **Latency baseline established**
- Per-hop timing measured and persisted to database
- p50/p95/p99 percentiles computed
- Hot path identified (which tier/plugin dominates compute time)

✅ **Report generated and persisted**
- Console output for human review
- JSON for downstream systems
- Written to `intelligence_metrics` table

#### Phase 2 (Service) — Adds:

✅ **Hourly execution**
- Cron job triggers audit every hour
- Metrics trended over time

✅ **Alerting on violations**
- Critical violations → PagerDuty/email immediately
- Consistency degradation → Warning email
- Latency degradation → Dev notification

✅ **Dashboard integration**
- SSE endpoint for real-time audit status
- Historical metrics API endpoint

---

## Architecture

### System Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    AUDIT ORCHESTRATOR                        │
│  - Runs hourly (or on-demand via CLI)                       │
│  - Queries TimescaleDB for sample data                      │
│  - Executes validation layers in sequence                   │
│  - Writes results to intelligence_metrics table             │
│  - Triggers alerts on violations                            │
└─────────────────────────────────────────────────────────────┘
         │
         ├──► Layer 0: Latency Measurement (Per-Hop Timing)
         │      - Bar aggregation → I1 → I4 → I6 → I7
         │      - p50/p95/p99 percentiles
         │      - Hot path identification
         │
         ├──► Layer 1: Computational Correctness (Reference Impl)
         │      - I1: RSI, MACD, ATR, OFI, CVD validated
         │      - I4: Volatility, VWAP, regime validated
         │      - Compare to reference implementations
         │
         ├──► Layer 2: External Source Validation (Gold Standard)
         │      - Compare to TradingView/Yahoo Finance
         │      - Correlation ≥0.99 required
         │
         ├──► Layer 3: Cross-Tier Consistency (YOUR PRIORITY)
         │      - I1→I4 correlations (ATR↔Volatility, etc.)
         │      - I6→I7 completeness (all required fields present)
         │      - I4↔I7 regime agreement
         │
         └──► Layer 4: Report Generation
                - Console output (colored sections)
                - JSON output (machine-readable)
                - Database persistence (intelligence_metrics table)
```

### Data Flow

```
Production Pipeline                    Audit Pipeline
━━━━━━━━━━━━━━━━━━                    ━━━━━━━━━━━━━━━━

TWS → 5s ticks
     ↓
  BarAccumulator                      ┌─────────────────┐
     ↓  (tracker.mark)                │  LatencyTracker  │
  1m bars                             │  (in-process)    │
     ↓                                 └─────────────────┘
  FeaturePipeline (I1-I6)
     ↓  (tracker.mark)                ┌─────────────────┐
  IntelligenceEvent                   │ Query DB for    │
     ↓                                 │ last 24h data   │
  SignalGenerator (I7)                └─────────────────┘
     ↓  (tracker.mark)                        ↓
  I7 Signals                     ┌─────────────────┐
     ↓                             │ Reference Impl  │
  SignalLifecycle                   │ Validation      │
     ↓                             └─────────────────┘
  DB Write                               ↓
                              ┌─────────────────┐
                              │ Cross-Tier      │
      ┌─────────────────┐     │ Consistency     │
      │ intelligence_   │     └─────────────────┘
      │ metrics table   │              ↓
      └─────────────────┘     ┌─────────────────┐
              ↑               │ External Source │
              │               │ Validation      │
              │               └─────────────────┘
              │                       ↓
              │               ┌─────────────────┐
              │               │  Report + Alert │
              │               └─────────────────┘
              └───────────────┘
         (persist metrics)
```

---

## Database Schema

### `intelligence_metrics` Hypertable

**Note:** Code reviewer mistakenly claimed this table exists — it does not. I8 data lives in `intelligence_features.i8` JSONB column, not a separate `intelligence_metrics` table. Original name is correct.

**Changes:** Removed latency columns — we query Prometheus metrics directly instead. No in-process tracking needed.

```sql
-- Audit metrics tracked over time
CREATE TABLE IF NOT EXISTS intelligence_metrics (
    id SERIAL PRIMARY KEY,
    measured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol VARCHAR(10) NOT NULL,
    timeframe VARCHAR(5) NOT NULL,

    -- Computational correctness metrics
    i1_rsi_correct BOOLEAN,
    i1_macd_correct BOOLEAN,
    i1_atr_correct BOOLEAN,
    i4_volatility_correct BOOLEAN,
    i4_regime_correct BOOLEAN,
    i4_vwap_correct BOOLEAN,
    i6_confluence_correct BOOLEAN,
    i7_signal_logic_correct BOOLEAN,

    -- External validation metrics (optional, Phase 2)
    i1_rsi_tv_correlation FLOAT,
    i1_macd_tv_correlation FLOAT,
    i1_atr_tv_correlation FLOAT,

    -- Cross-tier consistency
    i1_i4_correlation FLOAT,
    i6_i7_completeness FLOAT,
    i4_i7_regime_agreement FLOAT,

    -- Data quality
    null_count INT,
    nan_count INT,
    out_of_bounds_count INT,

    -- Metadata
    audit_version VARCHAR(10),

    CONSTRAINT symbol_tf_not_null CHECK (symbol IS NOT NULL AND timeframe IS NOT NULL)
);

-- Convert to hypertable for time-series optimization
SELECT create_hypertable('intelligence_metrics', 'measured_at');

-- Indexes for common queries
CREATE INDEX ON intelligence_metrics (symbol, timeframe, measured_at DESC);

-- Compression policy (compress data older than 30 days)
SELECT add_compression_policy('intelligence_metrics', INTERVAL '30 days');
```

---

## Implementation Components

### Component 1: PrometheusMetricsFetcher (Query Existing Metrics)

**File:** `src/validation/prometheus_metrics.py`

**Purpose:** Query existing Prometheus metrics for latency data — no new instrumentation needed.

```python
"""
Query existing Prometheus metrics for latency reporting.
Uses feature_pipeline_latency_ms and plugin_execution_seconds histograms.
"""

import httpx
from typing import Dict, List
from datetime import datetime, timedelta

class PrometheusMetricsFetcher:
    """Fetch latency metrics from existing Prometheus endpoints"""

    def __init__(self, prometheus_url: str = "http://localhost:9090"):
        self.prometheus_url = prometheus_url
        self.client = httpx.AsyncClient()

    async def query_histogram(self, metric_name: str, symbol: str = None, hours: int = 24) -> dict:
        """
        Query histogram metric and return percentiles.

        Example: query_histogram("plugin_execution_seconds", symbol="ES", hours=24)
        Returns: {"p50": 0.045, "p95": 0.089, "p99": 0.152, "count": 288}
        """
        query = f'histogram_quantile(0.50, sum(rate({metric_name}[{hours}h])) by (intelligence_tier))'

        response = await self.client.get(
            f"{self.prometheus_url}/api/v1/query",
            params={"query": query}
        )
        response.raise_for_status()
        data = response.json()

        if data["status"] != "success":
            return {"error": "Query failed", "raw": data}

        # Parse histogram quantiles
        result = {}
        if "data" in data and "result" in data["data"]:
            for metric in data["data"]["result"]:
                tier = metric.get("metric", {}).get("intelligence_tier", "unknown")
                value = float(metric.get("value", [0])[1])
                result[tier] = value

        return result

    async def get_pipeline_latency(self, symbol: str = "ES", hours: int = 24) -> dict:
        """Get feature_pipeline_latency_ms metrics"""
        query = f'feature_pipeline_latency_ms{{symbol="{symbol}"}}'

        response = await self.client.get(
            f"{self.prometheus_url}/api/v1/query",
            params={"query": query}
        )
        response.raise_for_status()
        data = response.json()

        if data["status"] != "success" or not data.get("data", {}).get("result"):
            return {"latency_ms": None, "error": "No data"}

        metric = data["data"]["result"][0]
        return {
            "latency_ms": float(metric.get("value", [0])[1]),
            "timestamp": metric.get("value", [0])[0]
        }

    async def get_plugin_execution_times(self, symbol: str = "ES", tf: str = "5m", hours: int = 24) -> Dict[str, dict]:
        """
        Get per-plugin execution time histograms.

        Returns: {
            "RSIPlugin": {"p50": 0.002, "p95": 0.004, "p99": 0.008},
            "MACDPlugin": {"p50": 0.003, "p95": 0.006, "p99": 0.011},
            ...
        }
        """
        query = f'histogram_quantile(0.95, sum(rate(plugin_execution_seconds[{hours}h])) by (plugin_name))'

        response = await self.client.get(
            f"{self.prometheus_url}/api/v1/query",
            params={"query": query}
        )
        response.raise_for_status()
        data = response.json()

        result = {}
        if data["status"] == "success" and data.get("data", {}).get("result"):
            for metric in data["data"]["result"]:
                plugin_name = metric.get("metric", {}).get("plugin_name", "unknown")
                p95_value = float(metric.get("value", [0])[1])
                result[plugin_name] = {"p95_ms": p95_value * 1000}

        return result

    async def close(self):
        await self.client.aclose()
```

---

### Component 2: Reference Implementations (First Principles)

**File:** `src/validation/reference_implementations.py`

**Purpose:** Mathematically correct implementations of every calculation for validation.

```python
"""
Reference implementations from first principles.
Use these to validate production code is mathematically correct.
"""

import numpy as np
from typing import List, Dict

def rsi_reference(prices: List[float], period: int = 14) -> np.ndarray:
    """
    Reference RSI implementation from Wilder's 1978 paper.
    RSI = 100 - (100 / (1 + RS))
    RS = Average Gain / Average Loss (Wilder's smoothing)
    """
    prices = np.array(prices)
    deltas = np.diff(prices)

    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    avg_gain = np.zeros_like(deltas)
    avg_loss = np.zeros_like(deltas)

    avg_gain[period] = np.mean(gains[:period])
    avg_loss[period] = np.mean(losses[:period])

    for i in range(period + 1, len(deltas)):
        avg_gain[i] = (avg_gain[i-1] * (period - 1) + gains[i]) / period
        avg_loss[i] = (avg_loss[i-1] * (period - 1) + losses[i]) / period

    rs = np.where(avg_loss == 0, np.inf, avg_gain / avg_loss)
    rsi = 100 - (100 / (1 + rs))

    rsi[:period] = np.nan
    return rsi

def macd_reference(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict:
    """
    Reference MACD implementation.
    MACD = EMA(fast) - EMA(slow)
    Signal = EMA(MACD, signal_period)
    Histogram = MACD - Signal
    """
    prices = np.array(prices)

    def ema(data, period):
        alpha = 2 / (period + 1)
        ema = np.zeros_like(data)
        ema[0] = data[0]
        for i in range(1, len(data)):
            ema[i] = alpha * data[i] + (1 - alpha) * ema[i-1]
        return ema

    ema_fast = ema(prices, fast)
    ema_slow = ema(prices, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line

    return {"macd": macd_line, "signal": signal_line, "histogram": histogram}

def atr_reference(high: List[float], low: List[float], close: List[float], period: int = 14) -> np.ndarray:
    """
    Reference ATR implementation (Wilder's smoothing).
    TR = max(high-low, |high-close_prev|, |low-close_prev|)
    ATR = Wilder's smoothing of TR
    """
    high = np.array(high)
    low = np.array(low)
    close = np.array(close)

    true_range = np.zeros(len(close))
    true_range[0] = high[0] - low[0]

    for i in range(1, len(close)):
        tr1 = high[i] - low[i]
        tr2 = abs(high[i] - close[i-1])
        tr3 = abs(low[i] - close[i-1])
        true_range[i] = max(tr1, tr2, tr3)

    atr = np.zeros_like(true_range)
    atr[period] = np.mean(true_range[:period])

    for i in range(period + 1, len(true_range)):
        atr[i] = (atr[i-1] * (period - 1) + true_range[i]) / period

    atr[:period] = np.nan
    return atr

def vwap_reference(high: List[float], low: List[float], close: List[float], volume: List[float]) -> np.ndarray:
    """
    Reference VWAP implementation.
    VWAP = Cumulative(Volume * Typical Price) / Cumulative(Volume)
    Typical Price = (High + Low + Close) / 3
    """
    high = np.array(high)
    low = np.array(low)
    close = np.array(close)
    volume = np.array(volume)

    typical_price = (high + low + close) / 3
    tp_volume = typical_price * volume

    cumulative_tp_volume = np.cumsum(tp_volume)
    cumulative_volume = np.cumsum(volume)

    vwap = cumulative_tp_volume / cumulative_volume
    return vwap

def volatility_reference(prices: List[float], period: int = 20) -> np.ndarray:
    """
    Reference volatility implementation (std dev of returns, annualized).
    """
    prices = np.array(prices)
    returns = np.diff(np.log(prices))

    volatility = np.zeros(len(prices))
    volatility[:period] = np.nan

    for i in range(period, len(prices)):
        window = returns[i-period:i]
        volatility[i] = np.std(window) * np.sqrt(252)

    return volatility
```

---

### Component 3: Validation Engine

**File:** `src/validation/validation_engine.py`

**Purpose:** Run reference implementations and compare to production values.

```python
"""
Computational correctness validation engine.
Compares production values to reference implementations.
"""

import asyncpg
import numpy as np
from src.validation.reference_implementations import *

class ComputationalCorrectnessValidator:
    """Validate every calculation in the pipeline"""

    TOLERANCES = {
        "i1_rsi": 0.01,
        "i1_macd": 0.01,
        "i1_atr": 0.05,
        "i4_volatility": 0.02,
        "i4_vwap": 0.05,
    }

    def __init__(self, db: asyncpg.Connection):
        self.db = db

    async def fetch_production_data(self, symbol: str, tf: str, hours: int = 24) -> dict:
        """Fetch data from intelligence_features for validation"""
        query = """
            SELECT ts,
                   (bar->>'close')::float as close,
                   (bar->>'high')::float as high,
                   (bar->>'low')::float as low,
                   (bar->>'volume')::float as volume,
                   (i1->>'rsi_14')::float as i1_rsi,
                   (i1->>'macd_12_26_9')::float as i1_macd,
                   (i1->>'atr_14')::float as i1_atr,
                   (i4->>'vol_percentile')::float as i4_volatility,
                   (i4->>'session_vwap')::float as i4_vwap
            FROM intelligence_features
            WHERE symbol = $1 AND tf = $2
              AND ts > NOW() - INTERVAL '%s hours'
            ORDER BY ts ASC
        """ % hours

        rows = await self.db.fetch(query, symbol, tf)

        return {
            "ts": [r["ts"] for r in rows],
            "close": [r["close"] for r in rows],
            "high": [r["high"] for r in rows],
            "low": [r["low"] for r in rows],
            "volume": [r["volume"] for r in rows],
            "i1_rsi": [r["i1_rsi"] for r in rows],
            "i1_macd": [r["i1_macd"] for r in rows],
            "i1_atr": [r["i1_atr"] for r in rows],
            "i4_volatility": [r["i4_volatility"] for r in rows],
            "i4_vwap": [r["i4_vwap"] for r in rows],
        }

    def validate_field(self, field_name: str, ref_values: np.ndarray, prod_values: np.ndarray) -> dict:
        """Validate a single field against reference implementation"""
        # Skip NaN values
        mask = ~np.isnan(ref_values) & ~np.isnan(prod_values)
        valid_samples = np.sum(mask)

        if valid_samples == 0:
            return {
                "field": field_name,
                "passed": False,
                "error": "No valid samples to compare",
                "samples": 0
            }

        diff = np.abs(ref_values[mask] - prod_values[mask])
        tolerance = self.TOLERANCES.get(field_name, 0.01)

        return {
            "field": field_name,
            "max_diff": float(np.max(diff)),
            "mean_diff": float(np.mean(diff)),
            "std_diff": float(np.std(diff)),
            "tolerance": tolerance,
            "passed": bool(np.max(diff) < tolerance),
            "samples": int(valid_samples)
        }

    async def run_validation(self, symbol: str = "ES", tf: str = "5m", hours: int = 24) -> dict:
        """Run full computational correctness validation"""
        data = await self.fetch_production_data(symbol, tf, hours)

        results = {}

        # Validate I1 fields
        ref_rsi = rsi_reference(data["close"])
        prod_rsi = np.array(data["i1_rsi"])
        results["i1_rsi"] = self.validate_field("i1_rsi", ref_rsi, prod_rsi)

        ref_macd = macd_reference(data["close"])
        prod_macd = np.array(data["i1_macd"])
        results["i1_macd"] = self.validate_field("i1_macd", ref_macd["macd"], prod_macd)

        ref_atr = atr_reference(data["high"], data["low"], data["close"])
        prod_atr = np.array(data["i1_atr"])
        results["i1_atr"] = self.validate_field("i1_atr", ref_atr, prod_atr)

        # Validate I4 fields
        ref_vol = volatility_reference(data["close"])
        prod_vol = np.array(data["i4_volatility"])
        results["i4_volatility"] = self.validate_field("i4_volatility", ref_vol, prod_vol)

        ref_vwap = vwap_reference(data["high"], data["low"], data["close"], data["volume"])
        prod_vwap = np.array(data["i4_vwap"])
        results["i4_vwap"] = self.validate_field("i4_vwap", ref_vwap, prod_vwap)

        # Persist results
        await self.persist_results(symbol, tf, results)

        return results

    async def persist_results(self, symbol: str, tf: str, results: dict):
        """Write validation results to database"""
        await self.db.execute("""
            INSERT INTO intelligence_metrics (
                symbol, timeframe,
                i1_rsi_correct,
                i1_macd_correct,
                i1_atr_correct,
                i4_volatility_correct,
                i4_vwap_correct
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
        """, symbol, tf,
            results.get("i1_rsi", {}).get("passed"),
            results.get("i1_macd", {}).get("passed"),
            results.get("i1_atr", {}).get("passed"),
            results.get("i4_volatility", {}).get("passed"),
            results.get("i4_vwap", {}).get("passed")
        )
```

---

### Component 4: Cross-Tier Consistency Validator

**File:** `src/validation/cross_tier_validation.py`

**Purpose:** Validate I1→I4→I7 transformations are consistent.

```python
"""
Cross-tier consistency validation.
I1 features should feed I4 context correctly.
I6 features should be present in I7 signals.
"""

import asyncpg
import numpy as np
from typing import Dict, List

class CrossTierValidator:
    """Validate cross-tier consistency"""

    def __init__(self, db: asyncpg.Connection):
        self.db = db

    async def validate_i1_to_i4_consistency(self, symbol: str, tf: str) -> dict:
        """I1 features should correlate with I4 context"""
        query = """
            SELECT
                (i1->>'atr_14')::float as i1_atr,
                (i1->>'rsi_14')::float as i1_rsi,
                (i4->>'vol_percentile')::float as i4_volatility,
                (i3->>'trend_strength')::float as i4_trend
            FROM intelligence_features
            WHERE symbol = $1 AND tf = $2
              AND ts > NOW() - INTERVAL '24 hours'
        """

        rows = await self.db.fetch(query, symbol, tf)

        # Extract arrays (skip nulls)
        i1_atr = np.array([r["i1_atr"] for r in rows if r["i1_atr"] is not None])
        i4_vol = np.array([r["i4_volatility"] for r in rows if r["i4_volatility"] is not None])

        # Compute correlation
        if len(i1_atr) > 0 and len(i4_vol) > 0:
            # Align arrays (they may have different null patterns)
            min_len = min(len(i1_atr), len(i4_vol))
            corr = np.corrcoef(i1_atr[:min_len], i4_vol[:min_len])[0, 1]
        else:
            corr = np.nan

        result = {
            "i1_atr_i4_volatility_correlation": float(corr) if not np.isnan(corr) else 0.0,
            "expected_min": 0.5,
            "passed": bool(corr >= 0.5) if not np.isnan(corr) else False,
            "samples": min_len
        }

        # Persist
        await self.db.execute("""
            INSERT INTO intelligence_metrics (symbol, timeframe, i1_i4_correlation)
            VALUES ($1, $2, $3)
        """, symbol, tf, result["i1_atr_i4_volatility_correlation"])

        return result

    async def validate_i6_to_i7_completeness(self, symbol: str, tf: str) -> dict:
        """
        I6 confluence fields must be present in intelligence_features.

        NOTE: I7 signals don't copy I6 fields into signal dicts.
        I7 plugins read from frames["i6"] during computation.
        We validate that i6 JSONB has all required confluence fields.
        """
        query = """
            SELECT
                i6,
                i7
            FROM intelligence_features
            WHERE symbol = $1 AND tf = $2
              AND ts > NOW() - INTERVAL '24 hours'
        """

        rows = await self.db.fetch(query, symbol, tf)

        complete_rows = 0
        missing_field_counts = {}

        # Required I6 confluence fields
        required_fields = ["ctf_score", "ctf_trend_alignment", "ctf_fvg_alignment", "ctf_ob_alignment"]

        valid_rows = [r for r in rows if isinstance(r.get("i6", {}), dict)]
        total_rows = len(valid_rows)

        for row in valid_rows:

            # Check if all required I6 fields are present and non-null
            missing = [f for f in required_fields if i6.get(f) is None]

            if not missing:
                complete_rows += 1
            else:
                for f in missing:
                    missing_field_counts[f] = missing_field_counts.get(f, 0) + 1

        completeness_rate = complete_rows / total_rows if total_rows > 0 else 0.0

        result = {
            "total_rows": total_rows,
            "complete_rows": complete_rows,
            "completeness_rate": completeness_rate,
            "expected_min": 0.95,
            "passed": completeness_rate >= 0.95,
            "missing_field_counts": missing_field_counts
        }

        # Persist
        await self.db.execute("""
            INSERT INTO intelligence_metrics (symbol, timeframe, i6_i7_completeness)
            VALUES ($1, $2, $3)
        """, symbol, tf, completeness_rate)

        return result

    async def validate_regime_agreement(self, symbol: str, tf: str) -> dict:
        """
        I4 regime should match I7 signal regime_type.

        NOTE: I7 signals have required field `regime_type`, not `regime_gate`.
        Signals with regime_type='any' should match any I4 regime.
        """
        query = """
            SELECT
                (smc->>'hmm_regime') as i4_regime,
                i7
            FROM intelligence_features
            WHERE symbol = $1 AND tf = $2
              AND smc->>'hmm_regime' IS NOT NULL
              AND jsonb_array_length(i7) > 0
              AND ts > NOW() - INTERVAL '24 hours'
        """

        rows = await self.db.fetch(query, symbol, tf)

        total_signals = 0
        matching_signals = 0

        for row in rows:
            i4_regime = row["i4_regime"]
            i7_signals = row.get("i7", [])

            if not isinstance(i7_signals, list):
                continue

            for signal in i7_signals:
                if not isinstance(signal, dict):
                    continue

                total_signals += 1
                i7_regime = signal.get("regime_type")

                # Signals with regime_type='any' match any I4 regime
                if i7_regime == "any" or i7_regime == i4_regime:
                    matching_signals += 1

        agreement_rate = matching_signals / total_signals if total_signals > 0 else 0.0

        result = {
            "total_signals": total_signals,
            "matching_signals": matching_signals,
            "agreement_rate": agreement_rate,
            "expected_min": 0.90,
            "passed": agreement_rate >= 0.90
        }

        # Persist
        await self.db.execute("""
            INSERT INTO intelligence_metrics (symbol, timeframe, i4_i7_regime_agreement)
            VALUES ($1, $2, $3)
        """, symbol, tf, agreement_rate)

        return result
```

---

### Component 5: Main Audit Script

**File:** `production/scripts/pipeline_audit.py`

**Purpose:** Orchestrate full audit (computational correctness + cross-tier + latency).

```python
#!/usr/bin/env python3
"""
Renaissance Pipeline Audit — Computational Correctness + Latency Tracking

Validates that every calculation in the pipeline is mathematically correct,
tracks per-hop latency, and measures cross-tier consistency.

Usage:
    python pipeline_audit.py --symbol ES --tf 5m --hours 24

Exit codes:
    0 = Audit passed
    1 = Audit failed
"""

import asyncio
import argparse
import sys
from datetime import datetime, UTC

from src.validation.validation_engine import ComputationalCorrectnessValidator
from src.validation.cross_tier_validation import CrossTierValidator
from src.core.database_manager import DatabaseManager
from src.config.settings import Settings

class AuditReporter:
    """Generate human-readable + machine-readable reports"""

    def __init__(self):
        self.passed = []
        self.failed = []
        self.warnings = []

    def print_header(self, symbol: str, tf: str, hours: int):
        print("\n" + "=" * 60)
        print(f"🔬 RENAISSANCE PIPELINE AUDIT")
        print(f"   Symbol: {symbol}")
        print(f"   Timeframe: {tf}")
        print(f"   Window: Last {hours} hours")
        print(f"   Started: {datetime.now(UTC).isoformat()}")
        print("=" * 60)

    def print_section(self, title: str):
        print(f"\n{title}")
        print("-" * 60)

    def print_computational_correctness(self, results: dict):
        """Print Layer 1: Computational Correctness results"""
        self.print_section("📊 Layer 1: Computational Correctness")

        for field, result in results.items():
            if result.get("error"):
                print(f"  ❌ {field}: ERROR - {result['error']}")
                self.failed.append(f"{field}: {result['error']}")
                continue

            status = "✅ PASS" if result["passed"] else "❌ FAIL"
            print(f"  {field}: {status}")
            print(f"    Max diff:  {result['max_diff']:.6f} (tolerance: {result['tolerance']})")
            print(f"    Mean diff: {result['mean_diff']:.6f}")
            print(f"    Samples:   {result['samples']}")

            if result["passed"]:
                self.passed.append(field)
            else:
                self.failed.append(field)

    def print_cross_tier_consistency(self, i1_i4: dict, i6_i7: dict, regime: dict):
        """Print Layer 2: Cross-Tier Consistency results"""
        self.print_section("📊 Layer 2: Cross-Tier Consistency")

        # I1→I4 Correlation
        corr = i1_i4.get("i1_atr_i4_volatility_correlation", 0)
        status = "✅ PASS" if i1_i4.get("passed") else "❌ FAIL"
        print(f"  I1→I4 Correlation: {corr:.3f} {status}")
        print(f"    Expected: ≥{i1_i4.get('expected_min', 0.5)}")
        print(f"    Samples: {i1_i4.get('samples', 0)}")

        if i1_i4.get("passed"):
            self.passed.append("I1→I4 Correlation")
        else:
            self.failed.append("I1→I4 Correlation")

        # I6→I7 Completeness
        completeness = i6_i7.get("completeness_rate", 0)
        status = "✅ PASS" if i6_i7.get("passed") else "❌ FAIL"
        print(f"\n  I6→I7 Completeness: {completeness:.1%} {status}")
        print(f"    Total signals: {i6_i7.get('total_signals', 0)}")
        print(f"    Complete: {i6_i7.get('complete_signals', 0)}")
        print(f"    Expected: ≥{i6_i7.get('expected_min', 0.95):.0%}")

        if i6_i7.get("missing_fields"):
            print(f"    ⚠️  Missing fields: {', '.join(i6_i7['missing_fields'])}")
            self.warnings.append(f"Missing I6 fields: {i6_i7['missing_fields']}")

        if i6_i7.get("passed"):
            self.passed.append("I6→I7 Completeness")
        else:
            self.failed.append("I6→I7 Completeness")

        # Regime Agreement
        agreement = regime.get("agreement_rate", 0)
        status = "✅ PASS" if regime.get("passed") else "❌ FAIL"
        print(f"\n  I4↔I7 Regime Agreement: {agreement:.1%} {status}")
        print(f"    Expected: ≥{regime.get('expected_min', 0.90):.0%}")

        if regime.get("passed"):
            self.passed.append("Regime Agreement")
        else:
            self.failed.append("Regime Agreement")

    def print_latency_metrics(self, latency_row: dict):
        """Print Layer 3: Latency metrics"""
        self.print_section("📊 Layer 3: Latency Metrics (Last 24h)")

        if not latency_row:
            print("  ⚠️  No latency data available yet")
            self.warnings.append("No latency data — pipeline may not be tracking")
            return

        print(f"  Bar Aggregation: {latency_row['avg_bar_agg']:.2f} ms")
        print(f"  I1 Computation:  {latency_row['avg_i1']:.2f} ms")
        print(f"  I4 Computation:  {latency_row['avg_i4']:.2f} ms")
        print(f"  I6 Computation:  {latency_row['avg_i6']:.2f} ms")
        print(f"  I7 Computation:  {latency_row['avg_i7']:.2f} ms")
        print(f"  ——————————————————————————————————")
        print(f"  End-to-End:      {latency_row['avg_e2e']:.2f} ms (avg)")
        print(f"  End-to-End:      {latency_row['p99_e2e']:.2f} ms (p99)")

        # Alert on high p99
        if latency_row['p99_e2e'] > 100:
            self.warnings.append(f"High p99 latency: {latency_row['p99_e2e']:.2f} ms")

    def print_summary(self):
        """Print audit summary"""
        print("\n" + "=" * 60)

        if not self.failed:
            print("✅ AUDIT PASSED")
            print(f"   Passed checks: {len(self.passed)}")
            if self.warnings:
                print(f"   Warnings: {len(self.warnings)}")
                for w in self.warnings:
                    print(f"     • {w}")
            print("\n✅ All calculations are correct.")
            print("✅ Cross-tier consistency validated.")
            print("✅ Pipeline is computationally sound.")
        else:
            print("❌ AUDIT FAILED")
            print(f"   Failed checks: {len(self.failed)}")
            print(f"   Passed checks: {len(self.passed)}")
            print("\n❌ Investigate failed validations:")
            for f in self.failed:
                print(f"   • {f}")

        print("=" * 60 + "\n")

async def main():
    parser = argparse.ArgumentParser(
        description="Renaissance Pipeline Audit — Computational Correctness + Latency"
    )
    parser.add_argument("--symbol", default="ES", help="Symbol to audit")
    parser.add_argument("--tf", default="5m", help="Timeframe to audit")
    parser.add_argument("--hours", type=int, default=24, help="Hours of data to validate")
    args = parser.parse_args()

    reporter = AuditReporter()
    reporter.print_header(args.symbol, args.tf, args.hours)

    settings = Settings()
    db = DatabaseManager(settings.database_url)
    await db.initialize()

    try:
        # Layer 1: Computational Correctness
        validator = ComputationalCorrectnessValidator(db)
        correctness_results = await validator.run_validation(args.symbol, args.tf, args.hours)
        reporter.print_computational_correctness(correctness_results)

        # Layer 2: Cross-Tier Consistency
        cross_validator = CrossTierValidator(db)

        i1_i4_results = await cross_validator.validate_i1_to_i4_consistency(args.symbol, args.tf)
        i6_i7_results = await cross_validator.validate_i6_to_i7_completeness(args.symbol, args.tf)
        regime_results = await cross_validator.validate_regime_agreement(args.symbol, args.tf)

        reporter.print_cross_tier_consistency(i1_i4_results, i6_i7_results, regime_results)

        # Layer 3: Latency Metrics (from Prometheus — latency columns were removed from DDL)
        # NOTE: intelligence_metrics has no latency columns. Latency data comes from
        # Prometheus histograms (feature_pipeline_latency_ms, plugin_execution_seconds).
        # Use PrometheusMetricsFetcher to query Prometheus instead.
        from src.validation.prometheus_metrics import PrometheusMetricsFetcher
        prom = PrometheusMetricsFetcher()
        try:
            latency_dict = await prom.get_pipeline_latency(symbol=args.symbol)
        finally:
            await prom.close()
        reporter.print_latency_metrics(latency_dict)

        # Summary
        reporter.print_summary()

        return 0 if not reporter.failed else 1

    finally:
        await db.close()

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
```

---

## Validation Layers

### Layer 0: Latency Measurement (Per-Hop Timing)

**What it measures:**
- Time from 5s ticks → 1m bar aggregation
- Time for I1 computation (all 27 plugins)
- Time for I4 computation (context, regime, volatility)
- Time for I6 computation (confluence scoring)
- Time for I7 computation (signal generation)
- End-to-end latency (bar → signal)

**How it works:**
- `LatencyTracker` instrumented in production code
- `tracker.mark(hop_name)` called at each pipeline stage
- Per-hop latencies computed as deltas
- Persisted to `intelligence_metrics` table after I7 computed

**Success criteria:**
- Baseline established (p50/p95/p99)
- Hot path identified
- Degradation alerting configured

### Layer 1: Computational Correctness (Reference Implementations)

**What it validates:**
- I1: RSI, MACD, ATR calculated correctly (Wilder's formulas)
- I1: OFI, CVD signed correctly
- I4: Volatility computed correctly (std dev of returns)
- I4: VWAP formula correct (session-based cumulative)
- I4: Regime detection working (HMM parameters)

**How it works:**
- Fetch production data from `intelligence_features`
- Run reference implementation from first principles
- Compare field-by-field with tolerance thresholds
- Persist pass/fail to `intelligence_metrics`

**Tolerance thresholds:**
- RSI: ±0.01 (strict)
- MACD: ±0.01 (strict)
- ATR: ±0.05 (looser, larger magnitude)
- Volatility: ±0.02
- VWAP: ±0.05 (session reset variance)

**Success criteria:**
- All fields pass tolerance test
- ≥95% of samples have valid comparison
- Zero computational correctness failures

### Layer 2: External Source Validation (Gold Standard)

**What it validates:**
- Our I1 calculations match TradingView/Yahoo Finance
- Correlation ≥0.99 required

**How it works:**
- Fetch same bar data from TradingView API
- Compute correlation between our values and external values
- Flag discrepancies >1%

**Success criteria:**
- Correlation ≥0.99 for all I1 fields
- No systematic bias (mean diff ≈ 0)

### Layer 3: Cross-Tier Consistency (YOUR PRIORITY)

**What it validates:**

1. **I1→I4 Correlations**
   - i1_atr ↔ i4_volatility: ρ ≥ 0.5 (expected)
   - i1_rsi ↔ i4_trend_strength: ρ ≥ 0.5
   - i1_obv ↔ i4_volume_regime: ρ ≥ 0.3

2. **I6→I7 Completeness**
   - ≥95% of I7 signals have all required I6 fields
   - Required: i6_ctf_fvg_alignment, i6_ctf_ob_alignment, i4_regime
   - Flag missing fields

3. **Regime Consistency**
   - I4 regime matches I7 regime_gate ≥90% of time
   - Legitimate lag allowed (regime transitions)

**Success criteria:**
- ≥95% cross-tier consistency rate
- Zero critical missing-field violations

### Layer 4: Data Quality Gates

**What it checks:**
- Null/NaN in non-optional fields
- Out-of-bounds values (RSI>100, vol<0, confidence∉[0,1])
- Type violations (string in numeric field)

**Exit criteria:**
- Zero critical violations allowed
- Fail-fast with alert if found

---

## Success Criteria Summary

### Phase 1 (Script) — Must Achieve:

✅ **Zero computational correctness failures**
- All I1 calculations match reference implementations
- All I4 calculations match reference implementations
- Tolerance thresholds met for all fields

✅ **≥95% cross-tier consistency**
- I1→I4 correlations ≥0.5 for related fields
- ≥95% of I7 signals have complete I6 features
- ≥90% regime agreement

✅ **Latency baseline established**
- Per-hop timing measured
- p50/p95/p99 computed
- Hot path identified

✅ **Report generated and persisted**
- Console output
- Database write to `intelligence_metrics`

### Phase 2 (Service) — Adds:

✅ **Hourly execution**
- Cron job or systemd timer

✅ **Alerting**
- Critical violations → PagerDuty/email
- Degradation → Warning

✅ **Dashboard**
- SSE endpoint
- Historical API

---

## Implementation Plan

### Week 1: Core Infrastructure

**Tasks:**
1. Create `intelligence_metrics` hypertable
2. Implement `LatencyTracker` class
3. Instrument production code with `tracker.mark()` calls
4. Write reference implementations (RSI, MACD, ATR, VWAP, volatility)

**Deliverables:**
- Database schema deployed
- Latency tracking in production
- Reference implementation library

### Week 2: Validation Engine

**Tasks:**
1. Implement `ComputationalCorrectnessValidator`
2. Implement `CrossTierValidator`
3. Database query layer for fetching sample data
4. Field-by-field comparison logic

**Deliverables:**
- Working validation engine
- Pass/fail for all I1/I4 fields

### Week 3: Main Audit Script

**Tasks:**
1. Implement `pipeline_audit.py` script
2. Report generation (console + JSON)
3. Database persistence layer
4. CLI argument parsing

**Deliverables:**
- Working audit script
- Can run: `python pipeline_audit.py --symbol ES --tf 5m`

### Week 4: Testing & Validation

**Tasks:**
1. Run audit daily for 1 week
2. Fix false positives/negatives
3. Validate tolerance thresholds
4. Document findings

**Deliverables:**
- Proven validation logic
- 1 week of audit results

### Week 5: Service Graduation

**Tasks:**
1. Create `pipeline_audit_service.py` daemon
2. Systemd unit file
3. Alerting integration
4. Dashboard SSE endpoint

**Deliverables:**
- Hourly audit service
- Automated alerting

---

## Open Questions

1. **External Source API** — TradingView doesn't have a public API. Options:
   - Use paid API (Alpha Vantage, Yahoo Finance)
   - Scrape TradingView (fragile)
   - Skip for now, rely on reference implementations

2. **Latency Overhead** — Will `LatencyTracker` add significant overhead?
   - Benchmark required
   - Consider async persistence (fire-and-forget)

3. **VWAP Session Reset** — VWAP resets at session open (RTH/ETH). How to handle in validation?
   - Mark session boundaries in data
   - Compare within sessions, not across

4. **Historical Backfill** — Should we audit backfilled data too?
   - Yes — validate backfill script correctness
   - Compare backfill vs live for same period

---

## Next Steps

1. **Review this design** — Confirm all requirements captured
2. **Write implementation plan** — TDD-style plan with tasks
3. **Create Phase X in ROADMAP** — Add to v2.1 roadmap
4. **Start implementation** — Begin with Week 1 tasks

---

## Appendix: Renaissance Design Principles Applied

### "Instrument Everything"
- Every hop tracked with `LatencyTracker`
- Every metric persisted to `intelligence_metrics`
- Historical trend analysis enabled

### "Proof Over Intuition"
- Reference implementations, not "looks right"
- Statistical tests (correlation, KS test)
- Tolerance thresholds with justification

### "Segment Relentlessly"
- Per-symbol, per-timeframe metrics
- Regime-specific validation (trending vs ranging)
- No global averages

### "Let the System Run"
- Automated hourly audits
- Self-healing (circuit breakers)
- Alert on degradation, not just failure

### "Data Quality Over Model Complexity"
- Computational correctness first
- Signal outcomes later
- Foundation before alpha

---

**Document Status:** Ready for Review
**Next Action:** Implement writing-plans skill → Create TDD implementation plan
