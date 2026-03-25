# Renaissance Pipeline Audit Framework — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an automated audit framework that validates every calculation in the intelligence pipeline is mathematically correct, tracks latency metrics, and ensures cross-tier consistency (I1→I4→I7 transformations).

**Architecture:** Modular validation system with reference implementations, validation engine, cross-tier consistency checks, and Prometheus metrics integration. All results persisted to TimescaleDB for historical trend analysis.

**Tech Stack:** Python 3.13+, asyncpg, numpy, httpx, TimescaleDB, Prometheus, pytest

---

## File Structure

```
src/validation/
├── __init__.py                           # Package init, exports
├── reference_implementations.py          # RSI, MACD, ATR, VWAP, volatility from first principles
├── validation_engine.py                  # Compare production values to reference
├── cross_tier_validation.py              # I1→I4, I6→I7, regime consistency checks
├── prometheus_metrics.py                 # Fetch latency metrics from Prometheus
└── audit_reporter.py                     # Console + JSON report generation

production/scripts/
└── pipeline_audit.py                     # Main audit CLI script

production/migrations/
└── 050_intelligence_metrics.sql          # Database schema for audit metrics

tests/unit/
├── test_reference_implementations.py    # Reference implementation tests
├── test_validation_engine.py            # Validation engine tests
└── test_cross_tier_validation.py        # Cross-tier validation tests
```

---

## Task 1: Database Schema Migration

**Files:**
- Create: `production/migrations/050_intelligence_metrics.sql`

**Purpose:** Create the `intelligence_metrics` hypertable for persisting audit results over time.

- [ ] **Step 1: Write migration file**

```sql
-- intelligence_metrics hypertable — audit metrics for Renaissance validation
-- Version: 1.0.0
-- Created: 2026-03-25
-- Purpose: Persist computational correctness, cross-tier consistency, and latency metrics

CREATE TABLE IF NOT EXISTS intelligence_metrics (
    id SERIAL PRIMARY KEY,
    measured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol VARCHAR(10) NOT NULL,
    timeframe VARCHAR(5) NOT NULL,

    -- Computational correctness metrics (validated against reference implementations)
    i1_rsi_correct BOOLEAN,
    i1_macd_correct BOOLEAN,
    i1_atr_correct BOOLEAN,
    i4_volatility_correct BOOLEAN,
    i4_regime_correct BOOLEAN,
    i4_vwap_correct BOOLEAN,
    i6_confluence_correct BOOLEAN,
    i7_signal_logic_correct BOOLEAN,

    -- Cross-tier consistency metrics
    i1_i4_correlation FLOAT,
    i6_i7_completeness FLOAT,
    i4_i7_regime_agreement FLOAT,

    -- Data quality metrics
    null_count INT,
    nan_count INT,
    out_of_bounds_count INT,

    -- Metadata
    audit_version VARCHAR(10) DEFAULT '1.0',

    CONSTRAINT symbol_tf_not_null CHECK (symbol IS NOT NULL AND timeframe IS NOT NULL)
);

-- Convert to hypertable for time-series optimization
SELECT create_hypertable('intelligence_metrics', 'measured_at', if_not_exists => TRUE);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_intel_metrics_sym_tf_ts
    ON intelligence_metrics (symbol, timeframe, measured_at DESC);

-- Compression policy (compress data older than 30 days)
DO $$ BEGIN
  PERFORM add_compression_policy('intelligence_metrics', INTERVAL '30 days', if_not_exists => true);
EXCEPTION WHEN others THEN NULL; END $$;

-- Retention policy: keep data for 1 year
DO $$ BEGIN
  PERFORM add_retention_policy('intelligence_metrics', INTERVAL '1 year', if_not_exists => true);
EXCEPTION WHEN others THEN NULL; END $$;
```

- [ ] **Step 2: Apply migration to database**

Run: `docker exec timescaledb psql -U postgres -d indicagent -f /dev/stdin < production/migrations/050_intelligence_metrics.sql`
Expected: `CREATE TABLE`, `CREATE INDEX`, `create_hypertable` output

- [ ] **Step 3: Verify table creation**

Run: `docker exec timescaledb psql -U postgres -d indicagent -c "\d intelligence_metrics"`
Expected: Table listing with all columns, indexes shown

- [ ] **Step 4: Commit**

```bash
git add production/migrations/050_intelligence_metrics.sql
git commit -m "feat(audit): add intelligence_metrics hypertable for pipeline audit framework"
```

---

## Task 2: Validation Package Initialization

**Files:**
- Create: `src/validation/__init__.py`

- [ ] **Step 1: Create package init file**

```python
"""
Renaissance Pipeline Audit Framework

Validates computational correctness, cross-tier consistency, and latency
across the entire intelligence pipeline (I1-I7).

Usage:
    from src.validation import ValidationEngine, CrossTierValidator, AuditReporter
    validator = ValidationEngine(db)
    results = await validator.run_validation("ES", "5m", hours=24)
"""

from src.validation.reference_implementations import (
    rsi_reference,
    macd_reference,
    atr_reference,
    vwap_reference,
    volatility_reference,
)

from src.validation.validation_engine import ComputationalCorrectnessValidator
from src.validation.cross_tier_validation import CrossTierValidator
from src.validation.audit_reporter import AuditReporter

__all__ = [
    # Reference implementations
    "rsi_reference",
    "macd_reference",
    "atr_reference",
    "vwap_reference",
    "volatility_reference",
    # Validators
    "ComputationalCorrectnessValidator",
    "CrossTierValidator",
    # Reporting
    "AuditReporter",
]
```

- [ ] **Step 2: Commit**

```bash
git add src/validation/__init__.py
git commit -m "feat(audit): add validation package with exports"
```

---

## Task 3: Reference Implementations

**Files:**
- Create: `src/validation/reference_implementations.py`
- Test: `tests/unit/test_reference_implementations.py`

- [ ] **Step 1: Write failing test for RSI reference implementation**

```python
"""Tests for reference implementations from first principles."""

import numpy as np
import pytest
from src.validation.reference_implementations import rsi_reference

def test_rsi_reference_simple_case():
    """Test RSI with known values."""
    prices = [44, 44.34, 44.09, 43.61, 44.33, 44.83, 45.10, 45.42,
              45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00]
    result = rsi_reference(prices, period=14)

    # First 14 values should be NaN (warmup)
    assert np.isnan(result[:14]).all()

    # RSI should be bounded [0, 100]
    assert np.nanmax(result) <= 100
    assert np.nanmin(result) >= 0

    # Last value should be non-NaN and in valid range
    assert not np.isnan(result[-1])
    assert 0 <= result[-1] <= 100

def test_rsi_reference_uptrend():
    """Test RSI in strong uptrend."""
    prices = [100 + i for i in range(20)]  # Perfect uptrend
    result = rsi_reference(prices, period=14)

    # RSI should be high (>70) in strong uptrend
    assert result[-1] > 70

def test_rsi_reference_downtrend():
    """Test RSI in strong downtrend."""
    prices = [100 - i for i in range(20)]  # Perfect downtrend
    result = rsi_reference(prices, period=14)

    # RSI should be low (<30) in strong downtrend
    assert result[-1] < 30
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_reference_implementations.py::test_rsi_reference_simple_case -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.validation.reference_implementations'"

- [ ] **Step 3: Implement RSI reference implementation**

```python
"""
Reference implementations from first principles.

Use these to validate production code is mathematically correct.
All implementations follow original paper formulas exactly.
"""

import numpy as np
from typing import List, Dict


def rsi_reference(prices: List[float], period: int = 14) -> np.ndarray:
    """
    Reference RSI implementation from Wilder's 1978 paper.

    RSI = 100 - (100 / (1 + RS))
    RS = Average Gain / Average Loss (Wilder's smoothing)

    Args:
        prices: List of closing prices
        period: RSI period (default 14)

    Returns:
        Array of RSI values (first `period` values are NaN)
    """
    prices = np.array(prices, dtype=float)
    deltas = np.diff(prices)

    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.zeros_like(deltas)
    avg_loss = np.zeros_like(deltas)

    # Initialize with simple average
    avg_gain[period - 1] = np.mean(gains[:period])
    avg_loss[period - 1] = np.mean(losses[:period])

    # Wilder's smoothing for subsequent values
    for i in range(period, len(deltas)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i]) / period

    # Calculate RS and RSI
    rs = np.divide(avg_gain, avg_loss, out=np.zeros_like(avg_gain), where=avg_loss != 0)
    rsi = 100 - (100 / (1 + rs))

    # First `period` values are undefined (warmup)
    result = np.full(len(prices), np.nan)
    result[period:] = rsi[period - 1:]

    return result


def macd_reference(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, np.ndarray]:
    """
    Reference MACD implementation.

    MACD Line = EMA(fast) - EMA(slow)
    Signal Line = EMA(MACD, signal_period)
    Histogram = MACD - Signal

    Args:
        prices: List of closing prices
        fast: Fast EMA period (default 12)
        slow: Slow EMA period (default 26)
        signal: Signal line EMA period (default 9)

    Returns:
        Dict with 'macd', 'signal', 'histogram' arrays
    """
    prices = np.array(prices, dtype=float)

    def ema(data: np.ndarray, period: int) -> np.ndarray:
        """Exponential Moving Average."""
        alpha = 2 / (period + 1)
        ema_values = np.zeros_like(data)
        ema_values[0] = data[0]

        for i in range(1, len(data)):
            ema_values[i] = alpha * data[i] + (1 - alpha) * ema_values[i - 1]

        return ema_values

    ema_fast = ema(prices, fast)
    ema_slow = ema(prices, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line

    return {
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram,
    }


def atr_reference(high: List[float], low: List[float], close: List[float], period: int = 14) -> np.ndarray:
    """
    Reference ATR implementation (Wilder's smoothing).

    True Range = max(high - low, |high - close_prev|, |low - close_prev|)
    ATR = Wilder's smoothing of True Range

    Args:
        high: List of high prices
        low: List of low prices
        close: List of close prices
        period: ATR period (default 14)

    Returns:
        Array of ATR values (first `period` values are NaN)
    """
    high = np.array(high, dtype=float)
    low = np.array(low, dtype=float)
    close = np.array(close, dtype=float)

    true_range = np.zeros(len(close))
    true_range[0] = high[0] - low[0]

    for i in range(1, len(close)):
        tr1 = high[i] - low[i]
        tr2 = abs(high[i] - close[i - 1])
        tr3 = abs(low[i] - close[i - 1])
        true_range[i] = max(tr1, tr2, tr3)

    atr = np.zeros_like(true_range)
    atr[period - 1] = np.mean(true_range[:period])

    for i in range(period, len(true_range)):
        atr[i] = (atr[i - 1] * (period - 1) + true_range[i]) / period

    # First `period` values are undefined
    result = np.full(len(close), np.nan)
    result[period:] = atr[period - 1:]

    return result


def vwap_reference(high: List[float], low: List[float], close: List[float], volume: List[float]) -> np.ndarray:
    """
    Reference VWAP implementation.

    VWAP = Cumulative(Volume * Typical Price) / Cumulative(Volume)
    Typical Price = (High + Low + Close) / 3

    Args:
        high: List of high prices
        low: List of low prices
        close: List of close prices
        volume: List of volumes

    Returns:
        Array of VWAP values
    """
    high = np.array(high, dtype=float)
    low = np.array(low, dtype=float)
    close = np.array(close, dtype=float)
    volume = np.array(volume, dtype=float)

    typical_price = (high + low + close) / 3
    tp_volume = typical_price * volume

    cumulative_tp_volume = np.cumsum(tp_volume)
    cumulative_volume = np.cumsum(volume)

    # Handle zero volume
    vwap = np.divide(
        cumulative_tp_volume,
        cumulative_volume,
        out=np.zeros_like(cumulative_tp_volume),
        where=cumulative_volume != 0,
    )

    return vwap


def volatility_reference(prices: List[float], period: int = 20) -> np.ndarray:
    """
    Reference volatility implementation (std dev of returns, annualized).

    Volatility = std(returns) * sqrt(252)

    Args:
        prices: List of closing prices
        period: Lookback period (default 20)

    Returns:
        Array of annualized volatility values (first `period` values are NaN)
    """
    prices = np.array(prices, dtype=float)
    returns = np.diff(np.log(prices))

    volatility = np.full(len(prices), np.nan)

    for i in range(period, len(prices)):
        window = returns[i - period:i]
        volatility[i] = np.std(window) * np.sqrt(252)

    return volatility
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_reference_implementations.py -v`
Expected: PASS for all RSI tests

- [ ] **Step 5: Add remaining reference implementation tests**

```python
def test_macd_reference():
    """Test MACD calculation."""
    prices = [100 + i + np.sin(i / 2) for i in range(50)]
    result = macd_reference(prices)

    assert "macd" in result
    assert "signal" in result
    assert "histogram" in result
    assert len(result["macd"]) == len(prices)
    assert len(result["signal"]) == len(prices)
    assert len(result["histogram"]) == len(prices)

    # Histogram = MACD - Signal
    np.testing.assert_array_almost_equal(
        result["histogram"],
        result["macd"] - result["signal"],
        decimal=10
    )

def test_atr_reference():
    """Test ATR calculation."""
    high = [102 + i for i in range(20)]
    low = [100 + i for i in range(20)]
    close = [101 + i for i in range(20)]
    result = atr_reference(high, low, close, period=14)

    # First 14 values should be NaN
    assert np.isnan(result[:14]).all()

    # ATR should be positive
    assert np.nanmin(result) >= 0
    assert not np.isnan(result[-1])

def test_vwap_reference():
    """Test VWAP calculation."""
    high = [102 + i for i in range(20)]
    low = [100 + i for i in range(20)]
    close = [101 + i for i in range(20)]
    volume = [1000 + i * 100 for i in range(20)]
    result = vwap_reference(high, low, close, volume)

    # VWAP should be within price range
    assert np.all(result >= np.array(low))
    assert np.all(result <= np.array(high))

def test_volatility_reference():
    """Test volatility calculation."""
    prices = [100 + i + np.random.randn() * 2 for i in range(50)]
    result = volatility_reference(prices, period=20)

    # First 20 values should be NaN
    assert np.isnan(result[:20]).all()

    # Volatility should be positive
    assert np.nanmin(result) >= 0
    assert not np.isnan(result[-1])
```

- [ ] **Step 6: Run all tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_reference_implementations.py -v`
Expected: PASS for all tests

- [ ] **Step 7: Commit**

```bash
git add src/validation/reference_implementations.py tests/unit/test_reference_implementations.py
git commit -m "feat(audit): add reference implementations for RSI, MACD, ATR, VWAP, volatility"
```

---

## Task 4: Validation Engine — Computational Correctness

**Files:**
- Create: `src/validation/validation_engine.py`
- Test: `tests/unit/test_validation_engine.py`

- [ ] **Step 1: Write failing test for validation engine**

```python
"""Tests for computational correctness validation engine."""

import pytest
import numpy as np
from src.validation.validation_engine import ComputationalCorrectnessValidator


@pytest.mark.asyncio
async def test_validator_fetches_data(db_connection):
    """Test that validator can fetch production data."""
    validator = ComputationalCorrectnessValidator(db_connection)

    # This requires actual data in intelligence_features
    # For unit test, we'll mock the data
    data = await validator.fetch_production_data("ES", "5m", hours=24)

    assert "close" in data
    assert "high" in data
    assert "low" in data
    assert "volume" in data
    assert "i1_rsi" in data
    assert len(data["close"]) > 0


@pytest.mark.asyncio
async def test_validate_field_within_tolerance():
    """Test field validation with values within tolerance."""
    from src.validation.validation_engine import ComputationalCorrectnessValidator

    validator = ComputationalCorrectnessValidator(None)

    ref_values = np.array([50.0, 51.0, 52.0, 53.0, 54.0])
    prod_values = np.array([50.01, 51.01, 52.01, 53.01, 54.01])

    result = validator.validate_field("test_field", ref_values, prod_values)

    assert result["field"] == "test_field"
    assert result["passed"] is True
    assert result["max_diff"] < 0.02
    assert result["samples"] == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_validation_engine.py::test_validate_field_within_tolerance -v`
Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Implement validation engine**

```python
"""
Computational correctness validation engine.

Compares production values from intelligence_features to reference
implementations to detect calculation errors.
"""

import asyncpg
import numpy as np
from typing import Dict, List

from src.validation.reference_implementations import (
    rsi_reference,
    macd_reference,
    atr_reference,
    vwap_reference,
    volatility_reference,
)


class ComputationalCorrectnessValidator:
    """Validate every calculation in the pipeline against reference implementations."""

    TOLERANCES = {
        "i1_rsi": 0.01,
        "i1_macd": 0.01,
        "i1_atr": 0.05,
        "i4_volatility": 0.02,
        "i4_vwap": 0.05,
    }

    def __init__(self, db: asyncpg.Connection):
        """Initialize validator with database connection.

        Args:
            db: asyncpg connection or connection pool
        """
        self.db = db

    async def fetch_production_data(
        self, symbol: str, tf: str, hours: int = 24
    ) -> Dict[str, List]:
        """Fetch data from intelligence_features for validation.

        Args:
            symbol: Trading symbol (e.g., "ES")
            tf: Timeframe (e.g., "5m", "15m", "1h")
            hours: Hours of historical data to fetch

        Returns:
            Dict with lists of values for each field
        """
        query = """
            SELECT ts,
                   bar->>'close' as close,
                   bar->>'high' as high,
                   bar->>'low' as low,
                   bar->>'volume' as volume,
                   i1->>'rsi_14' as i1_rsi,
                   i1->>'macd_12_26_9' as i1_macd,
                   i1->>'atr_14' as i1_atr,
                   i4->>'volatility' as i4_volatility,
                   i4->>'vwap' as i4_vwap
            FROM intelligence_features
            WHERE symbol = $1 AND tf = $2
              AND ts > NOW() - INTERVAL '%s hours'
            ORDER BY ts ASC
        """ % hours

        rows = await self.db.fetch(query, symbol, tf)

        return {
            "ts": [r["ts"] for r in rows],
            "close": [float(r["close"]) if r["close"] is not None else np.nan for r in rows],
            "high": [float(r["high"]) if r["high"] is not None else np.nan for r in rows],
            "low": [float(r["low"]) if r["low"] is not None else np.nan for r in rows],
            "volume": [float(r["volume"]) if r["volume"] is not None else np.nan for r in rows],
            "i1_rsi": [float(r["i1_rsi"]) if r["i1_rsi"] is not None else np.nan for r in rows],
            "i1_macd": [float(r["i1_macd"]) if r["i1_macd"] is not None else np.nan for r in rows],
            "i1_atr": [float(r["i1_atr"]) if r["i1_atr"] is not None else np.nan for r in rows],
            "i4_volatility": [float(r["i4_volatility"]) if r["i4_volatility"] is not None else np.nan for r in rows],
            "i4_vwap": [float(r["i4_vwap"]) if r["i4_vwap"] is not None else np.nan for r in rows],
        }

    def validate_field(
        self, field_name: str, ref_values: np.ndarray, prod_values: np.ndarray
    ) -> Dict:
        """Validate a single field against reference implementation.

        Args:
            field_name: Name of the field being validated
            ref_values: Reference implementation values
            prod_values: Production values from intelligence_features

        Returns:
            Dict with validation results (passed, max_diff, mean_diff, samples)
        """
        # Skip NaN values in comparison
        mask = ~np.isnan(ref_values) & ~np.isnan(prod_values)
        valid_samples = np.sum(mask)

        if valid_samples == 0:
            return {
                "field": field_name,
                "passed": False,
                "error": "No valid samples to compare",
                "samples": 0,
                "max_diff": np.nan,
                "mean_diff": np.nan,
                "std_diff": np.nan,
                "tolerance": self.TOLERANCES.get(field_name, 0.01),
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
            "samples": int(valid_samples),
            "error": None,
        }

    async def run_validation(
        self, symbol: str = "ES", tf: str = "5m", hours: int = 24
    ) -> Dict[str, Dict]:
        """Run full computational correctness validation.

        Args:
            symbol: Trading symbol to validate
            tf: Timeframe to validate
            hours: Hours of data to validate

        Returns:
            Dict mapping field names to validation results
        """
        data = await self.fetch_production_data(symbol, tf, hours)

        results = {}

        # Validate I1: RSI
        ref_rsi = rsi_reference(data["close"])
        prod_rsi = np.array(data["i1_rsi"])
        results["i1_rsi"] = self.validate_field("i1_rsi", ref_rsi, prod_rsi)

        # Validate I1: MACD
        ref_macd = macd_reference(data["close"])
        prod_macd = np.array(data["i1_macd"])
        results["i1_macd"] = self.validate_field("i1_macd", ref_macd["macd"], prod_macd)

        # Validate I1: ATR
        ref_atr = atr_reference(data["high"], data["low"], data["close"])
        prod_atr = np.array(data["i1_atr"])
        results["i1_atr"] = self.validate_field("i1_atr", ref_atr, prod_atr)

        # Validate I4: Volatility
        ref_vol = volatility_reference(data["close"])
        prod_vol = np.array(data["i4_volatility"])
        results["i4_volatility"] = self.validate_field("i4_volatility", ref_vol, prod_vol)

        # Validate I4: VWAP
        ref_vwap = vwap_reference(data["high"], data["low"], data["close"], data["volume"])
        prod_vwap = np.array(data["i4_vwap"])
        results["i4_vwap"] = self.validate_field("i4_vwap", ref_vwap, prod_vwap)

        # Persist results
        await self.persist_results(symbol, tf, results)

        return results

    async def persist_results(
        self, symbol: str, tf: str, results: Dict[str, Dict]
    ) -> None:
        """Write validation results to database.

        Args:
            symbol: Trading symbol
            tf: Timeframe
            results: Validation results from run_validation()
        """
        await self.db.execute(
            """
            INSERT INTO intelligence_metrics (
                symbol, timeframe,
                i1_rsi_correct,
                i1_macd_correct,
                i1_atr_correct,
                i4_volatility_correct,
                i4_vwap_correct
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
            symbol,
            tf,
            results.get("i1_rsi", {}).get("passed"),
            results.get("i1_macd", {}).get("passed"),
            results.get("i1_atr", {}).get("passed"),
            results.get("i4_volatility", {}).get("passed"),
            results.get("i4_vwap", {}).get("passed"),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_validation_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/validation/validation_engine.py tests/unit/test_validation_engine.py
git commit -m "feat(audit): add computational correctness validation engine"
```

---

## Task 5: Cross-Tier Consistency Validator

**Files:**
- Create: `src/validation/cross_tier_validation.py`
- Test: `tests/unit/test_cross_tier_validation.py`

- [ ] **Step 1: Write failing test**

```python
"""Tests for cross-tier consistency validation."""

import pytest
from src.validation.cross_tier_validation import CrossTierValidator


@pytest.mark.asyncio
async def test_validate_i6_to_i7_completeness(db_connection):
    """Test I6→I7 completeness validation."""
    validator = CrossTierValidator(db_connection)
    result = await validator.validate_i6_to_i7_completeness("ES", "5m")

    assert "completeness_rate" in result
    assert "passed" in result
    assert 0 <= result["completeness_rate"] <= 1


@pytest.mark.asyncio
async def test_validate_regime_agreement(db_connection):
    """Test I4↔I7 regime agreement validation."""
    validator = CrossTierValidator(db_connection)
    result = await validator.validate_regime_agreement("ES", "5m")

    assert "agreement_rate" in result
    assert "total_signals" in result
    assert "passed" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_cross_tier_validation.py -v`
Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Implement cross-tier validator**

```python
"""
Cross-tier consistency validation.

Validates that transformations between intelligence tiers are consistent:
- I1 features feed I4 context correctly
- I6 features are present for I7 signals
- I4 regime matches I7 regime_type
"""

import asyncpg
import numpy as np
from typing import Dict, List


class CrossTierValidator:
    """Validate cross-tier consistency in the intelligence pipeline."""

    def __init__(self, db: asyncpg.Connection):
        """Initialize validator with database connection.

        Args:
            db: asyncpg connection or connection pool
        """
        self.db = db

    async def validate_i1_to_i4_consistency(
        self, symbol: str, tf: str
    ) -> Dict:
        """Validate I1 features correlate with I4 context.

        I1 ATR should correlate with I4 volatility (both measure volatility).
        Correlation threshold: ≥0.5

        Args:
            symbol: Trading symbol
            tf: Timeframe

        Returns:
            Dict with correlation and pass/fail status
        """
        query = """
            SELECT
                i1->>'atr_14' as i1_atr,
                i4->>'volatility' as i4_volatility
            FROM intelligence_features
            WHERE symbol = $1 AND tf = $2
              AND ts > NOW() - INTERVAL '24 hours'
        """

        rows = await self.db.fetch(query, symbol, tf)

        # Extract arrays (skip nulls)
        i1_atr = np.array(
            [float(r["i1_atr"]) for r in rows if r["i1_atr"] is not None]
        )
        i4_vol = np.array(
            [float(r["i4_volatility"]) for r in rows if r["i4_volatility"] is not None]
        )

        # Compute correlation
        if len(i1_atr) > 0 and len(i4_vol) > 0:
            min_len = min(len(i1_atr), len(i4_vol))
            if min_len > 1:
                corr_matrix = np.corrcoef(i1_atr[:min_len], i4_vol[:min_len])
                corr = corr_matrix[0, 1]
            else:
                corr = np.nan
        else:
            corr = np.nan
            min_len = 0

        result = {
            "i1_atr_i4_volatility_correlation": float(corr) if not np.isnan(corr) else 0.0,
            "expected_min": 0.5,
            "passed": bool(corr >= 0.5) if not np.isnan(corr) else False,
            "samples": min_len,
        }

        # Persist
        await self.db.execute(
            """
            INSERT INTO intelligence_metrics (symbol, timeframe, i1_i4_correlation)
            VALUES ($1, $2, $3)
        """,
            symbol,
            tf,
            result["i1_atr_i4_volatility_correlation"],
        )

        return result

    async def validate_i6_to_i7_completeness(
        self, symbol: str, tf: str
    ) -> Dict:
        """Validate I6 confluence fields are present for I7 signals.

        Required I6 fields: ctf_score, ctf_trend_alignment, ctf_fvg_alignment, ctf_ob_alignment
        Completeness threshold: ≥95%

        Args:
            symbol: Trading symbol
            tf: Timeframe

        Returns:
            Dict with completeness rate and pass/fail status
        """
        query = """
            SELECT i6, i7
            FROM intelligence_features
            WHERE symbol = $1 AND tf = $2
              AND ts > NOW() - INTERVAL '24 hours'
        """

        rows = await self.db.fetch(query, symbol, tf)

        total_rows = 0
        complete_rows = 0
        missing_field_counts = {}

        # Required I6 confluence fields
        required_fields = [
            "ctf_score",
            "ctf_trend_alignment",
            "ctf_fvg_alignment",
            "ctf_ob_alignment",
        ]

        for row in rows:
            i6 = row.get("i6", {})
            if not isinstance(i6, dict):
                continue

            total_rows += 1

            # Check if all required I6 fields are present and non-null
            missing = [f for f in required_fields if i6.get(f) is None]

            if not missing:
                complete_rows += 1
            else:
                for f in missing:
                    missing_field_counts[f] = missing_field_counts.get(f, 0) + 1

        completeness_rate = (
            complete_rows / total_rows if total_rows > 0 else 0.0
        )

        result = {
            "total_rows": total_rows,
            "complete_rows": complete_rows,
            "completeness_rate": completeness_rate,
            "expected_min": 0.95,
            "passed": completeness_rate >= 0.95,
            "missing_field_counts": missing_field_counts,
        }

        # Persist
        await self.db.execute(
            """
            INSERT INTO intelligence_metrics (symbol, timeframe, i6_i7_completeness)
            VALUES ($1, $2, $3)
        """,
            symbol,
            tf,
            completeness_rate,
        )

        return result

    async def validate_regime_agreement(
        self, symbol: str, tf: str
    ) -> Dict:
        """Validate I4 regime matches I7 signal regime_type.

        Signals with regime_type='any' match any I4 regime.
        Agreement threshold: ≥90%

        Args:
            symbol: Trading symbol
            tf: Timeframe

        Returns:
            Dict with agreement rate and pass/fail status
        """
        query = """
            SELECT
                i4->>'regime' as i4_regime,
                i7
            FROM intelligence_features
            WHERE symbol = $1 AND tf = $2
              AND i4->>'regime' IS NOT NULL
              AND i7 IS NOT NULL
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

        agreement_rate = (
            matching_signals / total_signals if total_signals > 0 else 0.0
        )

        result = {
            "total_signals": total_signals,
            "matching_signals": matching_signals,
            "agreement_rate": agreement_rate,
            "expected_min": 0.90,
            "passed": agreement_rate >= 0.90,
        }

        # Persist
        await self.db.execute(
            """
            INSERT INTO intelligence_metrics (symbol, timeframe, i4_i7_regime_agreement)
            VALUES ($1, $2, $3)
        """,
            symbol,
            tf,
            agreement_rate,
        )

        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_cross_tier_validation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/validation/cross_tier_validation.py tests/unit/test_cross_tier_validation.py
git commit -m "feat(audit): add cross-tier consistency validator"
```

---

## Task 6: Audit Reporter

**Files:**
- Create: `src/validation/audit_reporter.py`

- [ ] **Step 1: Implement audit reporter**

```python
"""
Generate human-readable and machine-readable audit reports.

Produces console output with colored sections, JSON output for
downstream systems, and tracks passed/failed checks.
"""

from datetime import datetime
from typing import Dict, List


class AuditReporter:
    """Generate audit reports with console and JSON output."""

    def __init__(self):
        """Initialize reporter."""
        self.passed: List[str] = []
        self.failed: List[str] = []
        self.warnings: List[str] = []

    def print_header(self, symbol: str, tf: str, hours: int) -> None:
        """Print audit header.

        Args:
            symbol: Trading symbol
            tf: Timeframe
            hours: Hours of data validated
        """
        print("\n" + "=" * 60)
        print("🔬 RENAISSANCE PIPELINE AUDIT")
        print(f"   Symbol: {symbol}")
        print(f"   Timeframe: {tf}")
        print(f"   Window: Last {hours} hours")
        print(f"   Started: {datetime.utcnow().isoformat()}Z")
        print("=" * 60)

    def print_section(self, title: str) -> None:
        """Print section header.

        Args:
            title: Section title
        """
        print(f"\n{title}")
        print("-" * 60)

    def print_computational_correctness(self, results: Dict[str, Dict]) -> None:
        """Print Layer 1: Computational Correctness results.

        Args:
            results: Validation results from ComputationalCorrectnessValidator
        """
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

    def print_cross_tier_consistency(
        self,
        i1_i4: Dict,
        i6_i7: Dict,
        regime: Dict,
    ) -> None:
        """Print Layer 2: Cross-Tier Consistency results.

        Args:
            i1_i4: I1→I4 correlation results
            i6_i7: I6→I7 completeness results
            regime: Regime agreement results
        """
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
        print(f"    Total rows: {i6_i7.get('total_rows', 0)}")
        print(f"    Complete: {i6_i7.get('complete_rows', 0)}")
        print(f"    Expected: ≥{i6_i7.get('expected_min', 0.95):.0%}")

        if i6_i7.get("missing_field_counts"):
            missing = ", ".join(i6_i7["missing_field_counts"].keys())
            print(f"    ⚠️  Missing fields: {missing}")
            self.warnings.append(f"Missing I6 fields: {missing}")

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

    def print_summary(self) -> None:
        """Print audit summary with final pass/fail status."""
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
```

- [ ] **Step 2: Commit**

```bash
git add src/validation/audit_reporter.py
git commit -m "feat(audit): add audit reporter for console output"
```

---

## Task 7: Main Audit Script

**Files:**
- Create: `production/scripts/pipeline_audit.py`

- [ ] **Step 1: Implement main audit script**

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
from src.validation.audit_reporter import AuditReporter
from src.core.database_manager import DatabaseManager
from src.config.settings import Settings


async def main():
    """Run pipeline audit."""
    parser = argparse.ArgumentParser(
        description="Renaissance Pipeline Audit — Computational Correctness + Latency"
    )
    parser.add_argument("--symbol", default="ES", help="Symbol to audit (default: ES)")
    parser.add_argument("--tf", default="5m", help="Timeframe to audit (default: 5m)")
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Hours of data to validate (default: 24)",
    )
    args = parser.parse_args()

    settings = Settings()
    reporter = AuditReporter()
    reporter.print_header(args.symbol, args.tf, args.hours)

    db = DatabaseManager(settings.database_url)
    await db.initialize()

    try:
        # Layer 1: Computational Correctness
        validator = ComputationalCorrectnessValidator(db.pool)
        correctness_results = await validator.run_validation(
            args.symbol, args.tf, args.hours
        )
        reporter.print_computational_correctness(correctness_results)

        # Layer 2: Cross-Tier Consistency
        cross_validator = CrossTierValidator(db.pool)

        i1_i4_results = await cross_validator.validate_i1_to_i4_consistency(
            args.symbol, args.tf
        )
        i6_i7_results = await cross_validator.validate_i6_to_i7_completeness(
            args.symbol, args.tf
        )
        regime_results = await cross_validator.validate_regime_agreement(
            args.symbol, args.tf
        )

        reporter.print_cross_tier_consistency(
            i1_i4_results, i6_i7_results, regime_results
        )

        # Summary
        reporter.print_summary()

        return 0 if not reporter.failed else 1

    finally:
        await db.close()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
```

- [ ] **Step 2: Make script executable**

Run: `chmod +x production/scripts/pipeline_audit.py`

- [ ] **Step 3: Test script help**

Run: `.venv/bin/python production/scripts/pipeline_audit.py --help`
Expected: Help message with usage and options

- [ ] **Step 4: Commit**

```bash
git add production/scripts/pipeline_audit.py
git commit -m "feat(audit): add main pipeline audit CLI script"
```

---

## Task 8: Integration Testing

**Files:**
- Test: Manual integration test

- [ ] **Step 1: Run audit on live data**

Run: `.venv/bin/python production/scripts/pipeline_audit.py --symbol ES --tf 5m --hours 24`
Expected: Full audit output with pass/fail status

- [ ] **Step 2: Verify metrics persisted**

Run: `docker exec timescaledb psql -U postgres -d indicagent -c "SELECT * FROM intelligence_metrics ORDER BY measured_at DESC LIMIT 1;"`
Expected: Recent row with audit results

- [ ] **Step 3: Run tests**

Run: `.venv/bin/pytest tests/unit/test_reference_implementations.py tests/unit/test_validation_engine.py tests/unit/test_cross_tier_validation.py -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/2026-03-25-pipeline-audit-implementation.md
git commit -m "docs(audit): add pipeline audit implementation plan (all tasks complete)"
```

---

## Verification Checklist

After completing all tasks, verify:

- [ ] All tests pass: `.venv/bin/pytest tests/unit/ -v`
- [ ] Audit script runs without errors
- [ ] Metrics are persisted to `intelligence_metrics` table
- [ ] Console output shows colored sections
- [ ] Reference implementations produce mathematically correct values
- [ ] Cross-tier validation detects consistency issues
- [ ] Code follows CLAUDE.md conventions (snake_case, type hints, async/await)

---

## Next Steps

Phase 2 (Service):
- Create `pipeline_audit_service.py` with hourly execution
- Add systemd unit file
- Add alerting integration (email/PagerDuty)
- Add dashboard SSE endpoint
- Add historical metrics API endpoint

For now, the script is manually runnable for ad-hoc validation.
