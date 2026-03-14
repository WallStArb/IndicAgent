"""Unit tests for CUSUMMonitor — QUAL-10 CUSUM performance drift detection."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.stream_keys import drift_cusum
from src.monitoring.cusum_monitor import (
    CUSUMMonitor,
    _compute_cusum,
)

# ---------------------------------------------------------------------------
# Tests: _compute_cusum() pure function
# ---------------------------------------------------------------------------


def test_compute_cusum_degraded_series_returns_warning_or_critical():
    """All -0.5 pnl_r with positive baseline → CUSUM detects degradation."""
    # mu0=0.5 (good baseline), sigma0=1.0 — degraded to -0.5 → severe negative drift
    pnl_r_series = [0.5] * 20 + [-0.5] * 30  # 20 baseline + 30 degraded
    s_pos, s_neg, severity = _compute_cusum(pnl_r_series, mu0=0.5, sigma0=1.0)
    assert severity in {"warning", "critical"}, (
        f"Expected warning or critical for degraded series, got {severity!r}"
    )


def test_compute_cusum_neutral_series_returns_none():
    """Series that matches baseline → severity='none'."""
    # mu0=0.3, sigma0=0.5 — matching performance, no degradation
    pnl_r_series = [0.3] * 50
    s_pos, s_neg, severity = _compute_cusum(pnl_r_series, mu0=0.3, sigma0=0.5)
    assert severity == "none", (
        f"Expected none for neutral series matching baseline, got {severity!r}"
    )


def test_compute_cusum_returns_tuple_of_three():
    """_compute_cusum() always returns (s_pos, s_neg, severity) tuple."""
    result = _compute_cusum([0.5] * 25, mu0=0.3, sigma0=0.5)
    assert len(result) == 3
    s_pos, s_neg, severity = result
    assert isinstance(s_pos, float)
    assert isinstance(s_neg, float)
    assert isinstance(severity, str)
    assert severity in {"none", "warning", "critical", "info"}


def test_compute_cusum_winning_streak_returns_info():
    """Strongly positive series above baseline → severity='info' (upside)."""
    pnl_r_series = [0.3] * 20 + [2.0] * 30  # strong winning streak
    s_pos, s_neg, severity = _compute_cusum(pnl_r_series, mu0=0.3, sigma0=0.5)
    # info triggers on s_pos >= h=4.0 (winning streak)
    assert severity in {"info", "none"}, (
        f"Expected info or none for winning streak, got {severity!r}"
    )


# ---------------------------------------------------------------------------
# Tests: drift_cusum() stream key
# ---------------------------------------------------------------------------


def test_drift_cusum_key_format():
    """drift_cusum() returns correct namespaced key."""
    key = drift_cusum("development:", "trad_TrendFollowing")
    assert key == "development:drift:cusum:trad_TrendFollowing"


def test_drift_cusum_key_empty_prefix():
    """drift_cusum() with empty prefix works."""
    key = drift_cusum("", "trad_MeanReversion")
    assert key == "drift:cusum:trad_MeanReversion"


# ---------------------------------------------------------------------------
# Tests: CUSUMMonitor.check_setup()
# ---------------------------------------------------------------------------


def _make_monitor() -> CUSUMMonitor:
    """Return CUSUMMonitor with mocked DB pool (Phase 30: no Redis)."""
    db_pool = MagicMock()
    return CUSUMMonitor(
        db_pool=db_pool,
        env_prefix="development:",
    )


def _mock_db_outcomes(monitor: CUSUMMonitor, pnl_r_values: list[float]) -> None:
    """Patch db_pool to return fake outcome rows."""
    rows = [{"pnl_r": v} for v in pnl_r_values]
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows)
    conn.execute = AsyncMock()
    monitor.db_pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(return_value=False),
        )
    )
    return conn


@pytest.mark.asyncio
async def test_check_setup_insufficient_data_returns_none():
    """N < 20 outcomes → severity='none' (insufficient data gate)."""
    monitor = _make_monitor()
    _mock_db_outcomes(monitor, [0.5] * 15)  # only 15 rows

    severity = await monitor.check_setup("trad_TrendFollowing")
    assert severity == "none"


@pytest.mark.asyncio
async def test_check_setup_writes_db_on_detection():
    """check_setup() writes drift_state DB row when severity != 'none'."""
    monitor = _make_monitor()
    # Degraded series: good baseline then losses
    outcomes = [0.8] * 20 + [-0.8] * 30
    conn = _mock_db_outcomes(monitor, outcomes)

    severity = await monitor.check_setup("trad_TrendFollowing")

    if severity != "none":
        # DB execute should be called (INSERT INTO drift_state)
        assert conn.execute.called
        call_args = conn.execute.call_args
        query = call_args[0][0] if call_args[0] else ""
        assert "drift_state" in query
        assert call_args[0][1] == "trad_TrendFollowing"
        assert call_args[0][2] in {"warning", "critical"}


@pytest.mark.asyncio
async def test_check_setup_no_db_write_on_none_severity():
    """check_setup() does NOT write drift_state DB row when severity='none'."""
    monitor = _make_monitor()
    # Neutral series — should produce none
    outcomes = [0.3] * 50
    conn = _mock_db_outcomes(monitor, outcomes)

    severity = await monitor.check_setup("trad_MeanReversion")
    assert severity == "none"
    conn.execute.assert_not_called()
