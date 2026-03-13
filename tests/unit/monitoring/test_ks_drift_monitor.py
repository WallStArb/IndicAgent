"""Unit tests for KSDriftMonitor — QUAL-09 KS distribution drift detection."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from src.monitoring.ks_drift_monitor import (
    DRIFT_PENALTIES,
    DriftCheckResult,
    KSDriftMonitor,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_monitor() -> KSDriftMonitor:
    """Return a KSDriftMonitor with mocked DB pool and Redis."""
    db_pool = MagicMock()
    redis_client = AsyncMock()
    redis_client.get = AsyncMock(return_value=None)
    redis_client.set = AsyncMock(return_value=True)
    redis_client.delete = AsyncMock(return_value=1)
    return KSDriftMonitor(
        db_pool=db_pool,
        redis_client=redis_client,
        env_prefix="development:",
    )


def _mock_pool_records(monitor: KSDriftMonitor, reference_rows: list, current_rows: list) -> None:
    """Patch the db_pool to return two sets of rows for reference and current queries."""
    conn = AsyncMock()
    results = [reference_rows, current_rows]
    call_count = [0]

    async def fetch_side_effect(query, *args):
        idx = call_count[0]
        call_count[0] += 1
        if idx < len(results):
            return results[idx]
        return []

    conn.fetch = fetch_side_effect
    monitor.db_pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=conn),
        __aexit__=AsyncMock(return_value=False),
    ))


# ---------------------------------------------------------------------------
# Tests: DRIFT_PENALTIES constants
# ---------------------------------------------------------------------------


def test_drift_penalties_none():
    assert DRIFT_PENALTIES["none"] == 1.0


def test_drift_penalties_warning():
    assert DRIFT_PENALTIES["warning"] == 0.85


def test_drift_penalties_critical():
    assert DRIFT_PENALTIES["critical"] == 0.70


# ---------------------------------------------------------------------------
# Tests: insufficient data → no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_insufficient_reference_data_returns_none_severity():
    """Fewer than 30 reference rows → severity='none' (warming up)."""
    monitor = _make_monitor()
    # Only 10 reference rows — below 30 minimum
    reference_rows = [{"rsi_14": float(v)} for v in np.random.default_rng(0).random(10)]
    current_rows = [{"rsi_14": float(v)} for v in np.random.default_rng(1).random(50)]
    _mock_pool_records(monitor, reference_rows, current_rows)

    result = await monitor.check_symbol_tf("ES", "1m")

    assert result.severity == "none"
    assert result.ks_statistic is None
    assert result.ks_pvalue is None


# ---------------------------------------------------------------------------
# Tests: identical distributions → no drift
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_identical_distributions_no_drift():
    """Reference and current from same distribution → severity='none'."""
    monitor = _make_monitor()
    rng = np.random.default_rng(42)

    # Use multi-feature rows (matching KS_FEATURES fields)
    def make_row(rng):
        return {
            "rsi_14": float(rng.uniform(40, 60)),
            "macd_histogram_12_26_9": float(rng.uniform(-0.5, 0.5)),
            "rel_volume": float(rng.uniform(0.8, 1.2)),
            "hurst_exponent": float(rng.uniform(0.45, 0.55)),
            "entropy_quality": float(rng.uniform(0.6, 0.9)),
            "garch_sigma": float(rng.uniform(0.01, 0.03)),
            "trend_regime": float(rng.uniform(-0.2, 0.2)),
            "hmm_regime_0": float(rng.uniform(0.3, 0.7)),
        }

    reference_rows = [make_row(rng) for _ in range(60)]
    current_rows = [make_row(rng) for _ in range(40)]
    _mock_pool_records(monitor, reference_rows, current_rows)

    result = await monitor.check_symbol_tf("ES", "1m")

    assert result.severity == "none"


# ---------------------------------------------------------------------------
# Tests: clearly shifted distribution → drift detected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_shifted_distribution_detects_drift():
    """Current distribution shifted by 3σ → severity in {warning, critical}."""
    monitor = _make_monitor()
    rng = np.random.default_rng(99)

    # Reference: RSI centered around 50
    def make_ref_row(rng):
        return {
            "rsi_14": float(rng.normal(50, 5)),
            "macd_histogram_12_26_9": float(rng.normal(0, 0.3)),
            "rel_volume": float(rng.normal(1.0, 0.1)),
            "hurst_exponent": float(rng.normal(0.5, 0.05)),
            "entropy_quality": float(rng.normal(0.7, 0.05)),
            "garch_sigma": float(rng.normal(0.02, 0.002)),
            "trend_regime": float(rng.normal(0, 0.15)),
            "hmm_regime_0": float(rng.normal(0.5, 0.1)),
        }

    # Current: RSI shifted by 3σ (mean=65, same std)
    def make_curr_row(rng):
        return {
            "rsi_14": float(rng.normal(65, 5)),  # +3σ shift
            "macd_histogram_12_26_9": float(rng.normal(0.8, 0.3)),  # shifted
            "rel_volume": float(rng.normal(1.0, 0.1)),
            "hurst_exponent": float(rng.normal(0.5, 0.05)),
            "entropy_quality": float(rng.normal(0.7, 0.05)),
            "garch_sigma": float(rng.normal(0.02, 0.002)),
            "trend_regime": float(rng.normal(0, 0.15)),
            "hmm_regime_0": float(rng.normal(0.5, 0.1)),
        }

    reference_rows = [make_ref_row(rng) for _ in range(60)]
    current_rows = [make_curr_row(rng) for _ in range(40)]
    _mock_pool_records(monitor, reference_rows, current_rows)

    result = await monitor.check_symbol_tf("ES", "1m")

    assert result.severity in {"warning", "critical"}
    assert result.ks_statistic is not None
    assert result.ks_pvalue is not None
    assert result.ks_pvalue < 0.05


# ---------------------------------------------------------------------------
# Tests: DriftCheckResult structure
# ---------------------------------------------------------------------------


def test_drift_check_result_fields():
    r = DriftCheckResult(severity="warning", ks_statistic=0.35, ks_pvalue=0.02)
    assert r.severity == "warning"
    assert r.ks_statistic == 0.35
    assert r.ks_pvalue == 0.02
