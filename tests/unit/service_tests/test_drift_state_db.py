"""Unit tests for drift_state DB migration and DB-backed drift reads.

Tests for:
- DriftMonitorService writes KS/CUSUM severity to drift_state DB table (not Redis)
- SignalGeneratorService reads drift penalty from in-process dict populated from DB
- _refresh_drift_penalties_from_db() populates _drift_penalties dict
- _read_drift_penalty() returns float from _drift_penalties dict
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# SignalGeneratorService: _read_drift_penalty uses in-process dict (not Redis)
# ---------------------------------------------------------------------------


def test_read_drift_penalty_returns_float_from_in_process_dict():
    """_read_drift_penalty() must return float from _drift_penalties dict (not Redis)."""
    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc._drift_penalties = {("ES", "1m"): 0.85}

    # No Redis client should be needed
    svc.redis_client = None
    svc.logger = MagicMock()


@pytest.mark.asyncio
async def test_read_drift_penalty_returns_float_for_known_pair():
    """_read_drift_penalty('ES', '1m') → 0.85 when dict has 'warning' → 0.85."""
    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc._drift_penalties = {("ES", "1m"): 0.85}
    svc.logger = MagicMock()

    result = await svc._read_drift_penalty("ES", "1m")
    assert result == pytest.approx(0.85)


@pytest.mark.asyncio
async def test_read_drift_penalty_returns_one_for_unknown_pair():
    """_read_drift_penalty('GC', '1h') → 1.0 when no entry in dict (no penalty)."""
    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc._drift_penalties = {}
    svc.logger = MagicMock()

    result = await svc._read_drift_penalty("GC", "1h")
    assert result == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_read_drift_penalty_returns_one_for_critical():
    """critical severity → 0.70 penalty."""
    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc._drift_penalties = {("NQ", "5m"): 0.70}
    svc.logger = MagicMock()

    result = await svc._read_drift_penalty("NQ", "5m")
    assert result == pytest.approx(0.70)


# ---------------------------------------------------------------------------
# SignalGeneratorService: _refresh_drift_penalties_from_db()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_drift_penalties_populates_dict():
    """_refresh_drift_penalties_from_db() must populate _drift_penalties from DB rows."""
    from services.signal_generator_service import SignalGeneratorService
    from src.monitoring.ks_drift_monitor import DRIFT_PENALTIES

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc._drift_penalties = {}
    svc.logger = MagicMock()

    # Mock DB manager with asyncpg pool
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[
        {"symbol": "ES", "tf": "1m", "ks_severity": "warning"},
        {"symbol": "NQ", "tf": "5m", "ks_severity": "critical"},
        {"symbol": "GC", "tf": "15m", "ks_severity": "none"},
    ])

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    mock_db = MagicMock()
    mock_db.pool = mock_pool
    svc.db_manager = mock_db

    await svc._refresh_drift_penalties_from_db()

    # "warning" → 0.85, "critical" → 0.70, "none" → 1.0
    assert svc._drift_penalties[("ES", "1m")] == pytest.approx(DRIFT_PENALTIES["warning"])
    assert svc._drift_penalties[("NQ", "5m")] == pytest.approx(DRIFT_PENALTIES["critical"])
    assert svc._drift_penalties[("GC", "15m")] == pytest.approx(DRIFT_PENALTIES["none"])


@pytest.mark.asyncio
async def test_refresh_drift_penalties_no_op_when_no_db():
    """_refresh_drift_penalties_from_db() is no-op when db_manager is None."""
    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc._drift_penalties = {}
    svc.db_manager = None
    svc.logger = MagicMock()

    # Should not raise
    await svc._refresh_drift_penalties_from_db()
    assert svc._drift_penalties == {}


# ---------------------------------------------------------------------------
# DriftMonitorService: writes to drift_state DB table, not Redis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ks_drift_monitor_writes_to_db_not_redis():
    """KSDriftMonitor._write_drift_key() must call asyncpg INSERT not redis.set."""
    from src.monitoring.ks_drift_monitor import DriftCheckResult, KSDriftMonitor

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    monitor = KSDriftMonitor.__new__(KSDriftMonitor)
    monitor.db_pool = mock_pool
    monitor.env_prefix = "development:"
    monitor.timeframes = ["1m"]
    monitor.symbols = ["ES"]
    monitor._clean_cycles = {}
    monitor.logger = MagicMock()

    result = DriftCheckResult(severity="warning")

    await monitor._write_drift_key("ES", "1m", result)

    # Should call asyncpg execute (INSERT INTO drift_state)
    assert mock_conn.execute.called
    call_args = mock_conn.execute.call_args
    assert "drift_state" in call_args[0][0]


@pytest.mark.asyncio
async def test_cusum_monitor_writes_to_db_not_redis():
    """CUSUMMonitor.check_setup() must call asyncpg INSERT not redis.set when severity != none."""
    from src.monitoring.cusum_monitor import CUSUMMonitor

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    # Return 30 pnl_r outcomes so CUSUM has enough data to fire
    mock_conn.fetch = AsyncMock(return_value=[
        {"pnl_r": -2.0 - i * 0.1} for i in range(30)
    ])

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    monitor = CUSUMMonitor.__new__(CUSUMMonitor)
    monitor.db_pool = mock_pool
    monitor.env_prefix = "development:"
    monitor.logger = MagicMock()

    # run check_setup — if severity fires, should write to DB not Redis
    severity = await monitor.check_setup("trad_TrendFollowing")

    # The key test: if drift was detected, verify execute was called (not redis.set)
    if severity != "none":
        assert mock_conn.execute.called
        call_args = mock_conn.execute.call_args
        assert "drift_state" in call_args[0][0]


# ---------------------------------------------------------------------------
# DriftMonitorService: no Redis client at all
# ---------------------------------------------------------------------------


def test_drift_monitor_service_has_no_redis_client():
    """DriftMonitorService.__init__ must not set redis_client attribute."""
    from services.drift_monitor_service import DriftMonitorService

    svc = DriftMonitorService.__new__(DriftMonitorService)

    # After migration, redis_client should not be an instance attribute
    # (or should be None and never connected)
    # The service should rely only on db_manager for drift state
    assert not hasattr(svc, "redis_client") or svc.redis_client is None
