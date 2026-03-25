# Renaissance Pipeline Audit Framework — Design Document

**Date:** 2026-03-25
**Status:** Design — REVISED (2026-03-25) — Awaiting Further Review
**Priority:** Critical — Foundation for v2.1 Data Quality validation
**Revision Notes:** Critical issues identified by code review — fixes in progress

## Critical Revisions Required

### 1. Database Schema
- [x] Rename `intelligence_metrics` → `pipeline_audit_metrics` (avoid conflict)
- [ ] Fix all table references in Components 3-5

### 2. Field Name Mapping
- [ ] Update SQL queries to use period-encoded field names:
  - `rsi` → `rsi_14`, `rsi_21`, `rsi_30`
  - `atr` → `atr_14`
  - `macd` → `macd_12_26_9`
- [ ] Update reference implementation validator to handle multiple periods

### 3. Validation Logic Fixes
- [ ] Fix I6→I7 completeness: Query `intelligence_features.i6` directly, not iterate I7 signals
- [ ] Fix regime agreement: Use `signal["regime_type"]` not `regime_gate`
- [ ] Fix I1→I4 correlation thresholds: Lower to ≥0.3 or validate empirically

### 4. Latency Tracking
- [ ] Add sampling (10% of bars) instead of per-bar tracking
- [ ] Add in-memory aggregation with 60s flush

### 5. External Validation
- [ ] Defer to Phase 2 (API availability uncertain)

### 6. Regime Segmentation
- [ ] Add `WHERE i4->>'regime' = 'trending'` variants to all validation queries

### 7. Index Recommendations
- [ ] Add: `CREATE INDEX ON intelligence_features (symbol, tf, ts DESC)`

**Status:** Partially revised. Full rewrite recommended before implementation planning.

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

### `pipeline_audit_metrics` Hypertable

**Note:** Renamed from `intelligence_metrics` to avoid conflict with existing table.

```sql
-- Every metric, every hop, tracked over time
CREATE TABLE IF NOT EXISTS pipeline_audit_metrics (
    id SERIAL PRIMARY KEY,
    measured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol VARCHAR(10) NOT NULL,
    timeframe VARCHAR(5) NOT NULL,

    -- Latency metrics (milliseconds)
    latency_bar_aggregation FLOAT,              -- 5s ticks → 1m bar
    latency_i1_computation FLOAT,               -- I1 plugins
    latency_i4_computation FLOAT,               -- I4 context
    latency_i6_computation FLOAT,               -- I6 confluence
    latency_i7_computation FLOAT,               -- I7 signal generation
    latency_end_to_end FLOAT,                   -- Total from bar to signal

    -- Throughput metrics
    bars_processed INT,
    signals_generated INT,
    signals_per_bar FLOAT,

    -- Computational correctness metrics
    i1_rsi_correct BOOLEAN,                     -- Reference impl match
    i1_macd_correct BOOLEAN,
    i1_atr_correct BOOLEAN,
    i4_volatility_correct BOOLEAN,
    i4_regime_correct BOOLEAN,
    i4_vwap_correct BOOLEAN,
    i6_confluence_correct BOOLEAN,
    i7_signal_logic_correct BOOLEAN,

    -- External validation metrics
    i1_rsi_tv_correlation FLOAT,                -- TradingView correlation
    i1_macd_tv_correlation FLOAT,
    i1_atr_tv_correlation FLOAT,

    -- Cross-tier consistency
    i1_i4_correlation FLOAT,                    -- I1 vs I4 agreement
    i6_i7_completeness FLOAT,                   -- % signals with complete I6
    i4_i7_regime_agreement FLOAT,               -- % regime match

    -- Data quality
    null_count INT,
    nan_count INT,
    out_of_bounds_count INT,

    -- Metadata
    audit_version VARCHAR(10),

    CONSTRAINT symbol_tf_not_null CHECK (symbol IS NOT NULL AND timeframe IS NOT NULL)
);

-- Convert to hypertable for time-series optimization
SELECT create_hypertable('pipeline_audit_metrics', 'measured_at');

-- Indexes for common queries
CREATE INDEX idx_audit_metrics_symbol_tf ON pipeline_audit_metrics (symbol, timeframe, measured_at DESC);
CREATE INDEX idx_audit_metrics_measured_at ON pipeline_audit_metrics (measured_at DESC);

-- Compression policy (compress data older than 30 days)
SELECT add_compression_policy('pipeline_audit_metrics', INTERVAL '30 days');
```

---

## Implementation Components

### Component 1: LatencyTracker (In-Process Instrumentation)

**File:** `src/core/latency_tracker.py`

**Purpose:** Track per-hop timing through the pipeline in real-time.

```python
"""
Latency tracking for every bar from creation to I7 signal.
"""

import time
from datetime import datetime
from typing import Dict

class LatencyTracker:
    """Track timing through the intelligence pipeline"""

    def __init__(self, symbol: str, tf: str, bar_timestamp: datetime):
        self.symbol = symbol
        self.tf = tf
        self.bar_timestamp = bar_timestamp
        self.timings: Dict[str, float] = {}
        self.start_time = time.time()

    def mark(self, hop: str):
        """Record timestamp for a hop (milliseconds from start)"""
        self.timings[hop] = (time.time() - self.start_time) * 1000

    def get_latencies(self) -> dict:
        """Compute per-hop latencies"""
        return {
            "bar_aggregation": self.timings.get("bar_aggregated", 0),
            "i1_computation": self._get_delta("i1_computed", "bar_aggregated"),
            "i4_computation": self._get_delta("i4_computed", "i1_computed"),
            "i6_computation": self._get_delta("i6_computed", "i4_computed"),
            "i7_computation": self._get_delta("i7_computed", "i6_computed"),
            "end_to_end": self.timings.get("i7_computed", 0),
        }

    def _get_delta(self, current: str, previous: str) -> float:
        """Compute time difference between two hops"""
        curr = self.timings.get(current, 0)
        prev = self.timings.get(previous, 0)
        return max(0, curr - prev)

    async def persist(self, db):
        """Write latencies to database"""
        latencies = self.get_latencies()
        await db.execute("""
            INSERT INTO intelligence_metrics (
                symbol, timeframe,
                latency_bar_aggregation,
                latency_i1_computation,
                latency_i4_computation,
                latency_i6_computation,
                latency_i7_computation,
                latency_end_to_end
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """, (
            self.symbol, self.tf,
            latencies["bar_aggregation"],
            latencies["i1_computation"],
            latencies["i4_computation"],
            latencies["i6_computation"],
            latencies["i7_computation"],
            latencies["end_to_end"]
        ))

# Usage in production code
# In feature_pipeline_service.py, signal_generator_service.py, etc.:
def process_bar(bar: BarMessage):
    tracker = LatencyTracker(bar.symbol, bar.timeframe, bar.timestamp)

    # Bar aggregation
    aggregated = aggregate_bar(bar)
    tracker.mark("bar_aggregated")

    # I1 computation
    i1_features = compute_i1(aggregated)
    tracker.mark("i1_computed")

    # I4 computation
    i4_context = compute_i4(i1_features)
    tracker.mark("i4_computed")

    # I6 confluence
    i6_confluence = compute_i6(i4_context)
    tracker.mark("i6_computed")

    # I7 signal generation
    i7_signals = compute_i7(i6_confluence)
    tracker.mark("i7_computed")

    # Persist metrics
    asyncio.create_task(tracker.persist(db))

    return i7_signals
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

    rs = avg_gain / avg_loss
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
                   close, high, low, volume,
                   (intel->'i1'->>'rsi')::float as i1_rsi,
                   (intel->'i1'->>'macd')::float as i1_macd,
                   (intel->'i1'->>'macd_signal')::float as i1_macd_signal,
                   (intel->'i1'->>'atr')::float as i1_atr,
                   (intel->'i4'->>'volatility')::float as i4_volatility,
                   (intel->'i4'->>'vwap')::float as i4_vwap
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
                (intel->'i1'->>'atr')::float as i1_atr,
                (intel->'i1'->>'rsi')::float as i1_rsi,
                (intel->'i4'->>'volatility')::float as i4_volatility,
                (intel->'i4'->>'trend_strength')::float as i4_trend
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
        """Every I7 signal must have complete I6 features"""
        query = """
            SELECT intel->'i7' as i7_signals
            FROM intelligence_features
            WHERE symbol = $1 AND tf = $2
              AND intel->'i7' IS NOT NULL
              AND ts > NOW() - INTERVAL '24 hours'
        """

        rows = await self.db.fetch(query, symbol, tf)

        total_signals = 0
        complete_signals = 0
        missing_fields = set()

        required_fields = ["i6_ctf_fvg_alignment", "i6_ctf_ob_alignment", "i4_regime"]

        for row in rows:
            i7_signals = row["i7_signals"]
            if not isinstance(i7_signals, list):
                continue

            for signal in i7_signals:
                if not isinstance(signal, dict):
                    continue

                total_signals += 1

                # Check if all required fields are present and non-null
                missing = [f for f in required_fields if signal.get(f) is None]

                if not missing:
                    complete_signals += 1
                else:
                    missing_fields.update(missing)

        completeness_rate = complete_signals / total_signals if total_signals > 0 else 0.0

        result = {
            "total_signals": total_signals,
            "complete_signals": complete_signals,
            "completeness_rate": completeness_rate,
            "expected_min": 0.95,
            "passed": completeness_rate >= 0.95,
            "missing_fields": list(missing_fields)
        }

        # Persist
        await self.db.execute("""
            INSERT INTO intelligence_metrics (symbol, timeframe, i6_i7_completeness)
            VALUES ($1, $2, $3)
        """, symbol, tf, completeness_rate)

        return result

    async def validate_regime_agreement(self, symbol: str, tf: str) -> dict:
        """I4 regime should match I7 regime_gate"""
        query = """
            SELECT
                (intel->'i4'->>'regime') as i4_regime,
                intel->'i7' as i7_signals
            FROM intelligence_features
            WHERE symbol = $1 AND tf = $2
              AND intel->'i4'->>'regime' IS NOT NULL
              AND intel->'i7' IS NOT NULL
              AND ts > NOW() - INTERVAL '24 hours'
        """

        rows = await self.db.fetch(query, symbol, tf)

        total_signals = 0
        matching_signals = 0

        for row in rows:
            i4_regime = row["i4_regime"]
            i7_signals = row["i7_signals"]

            if not isinstance(i7_signals, list):
                continue

            for signal in i7_signals:
                if not isinstance(signal, dict):
                    continue

                total_signals += 1
                i7_regime = signal.get("regime_gate") or signal.get("i4_regime_at_fire")

                if i7_regime == i4_regime:
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
from datetime import datetime

from src.validation.validation_engine import ComputationalCorrectnessValidator
from src.validation.cross_tier_validation import CrossTierValidator
from src.core.database_manager import DatabaseManager

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
        print(f"   Started: {datetime.utcnow().isoformat()}Z")
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

    db = DatabaseManager()
    await db.connect()

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

        # Layer 3: Latency Metrics
        latency_query = """
            SELECT
                AVG(latency_bar_aggregation) as avg_bar_agg,
                AVG(latency_i1_computation) as avg_i1,
                AVG(latency_i4_computation) as avg_i4,
                AVG(latency_i6_computation) as avg_i6,
                AVG(latency_i7_computation) as avg_i7,
                AVG(latency_end_to_end) as avg_e2e,
                PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY latency_end_to_end) as p99_e2e
            FROM intelligence_metrics
            WHERE symbol = $1 AND timeframe = $2
              AND measured_at > NOW() - INTERVAL '24 hours'
        """

        latency_row = await db.fetchrow(latency_query, args.symbol, args.tf)
        latency_dict = dict(latency_row) if latency_row else {}
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
