"""Unit tests for ConfidenceCalibrationMonitor alert threshold logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_pool(rows: list[dict]) -> MagicMock:
    """Return a mock asyncpg pool whose conn.fetch returns the given rows.

    Each dict in `rows` represents an asyncpg Record with keys:
      setup_plugin, calibration, n
    """
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[_make_record(r) for r in rows])

    pool = MagicMock()
    pool.acquire = MagicMock(
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=conn),
            __aexit__=AsyncMock(),
        )
    )
    return pool


def _make_record(data: dict) -> MagicMock:
    """Return a MagicMock that behaves like an asyncpg Record for key access."""
    record = MagicMock()
    record.__getitem__ = MagicMock(side_effect=lambda k: data[k])
    return record


@pytest.mark.asyncio
async def test_alert_on_low_calibration(monkeypatch):
    """calibration=0.1, n=150 (both below threshold and above min_n) triggers alert once."""
    import services.confidence_calibration_monitor as mod

    mock_gauge = MagicMock()
    mock_counter = MagicMock()
    monkeypatch.setattr(mod, "SIGNAL_CONFIDENCE_CALIBRATION", mock_gauge)
    monkeypatch.setattr(mod, "CONFIDENCE_CALIBRATION_ALERTS_TOTAL", mock_counter)

    pool = _make_pool([{"setup_plugin": "momentum_breakout", "calibration": 0.1, "n": 150}])

    await mod._run_audit(pool)

    mock_counter.add.assert_called_once_with(1, {"setup_plugin": "momentum_breakout"})
    mock_gauge.set.assert_called_once_with(0.1, {"setup_plugin": "momentum_breakout"})


@pytest.mark.asyncio
async def test_no_alert_on_high_calibration(monkeypatch):
    """calibration=0.8, n=150 (above threshold) triggers no alert; gauge set to 0.8."""
    import services.confidence_calibration_monitor as mod

    mock_gauge = MagicMock()
    mock_counter = MagicMock()
    monkeypatch.setattr(mod, "SIGNAL_CONFIDENCE_CALIBRATION", mock_gauge)
    monkeypatch.setattr(mod, "CONFIDENCE_CALIBRATION_ALERTS_TOTAL", mock_counter)

    pool = _make_pool([{"setup_plugin": "trend_following", "calibration": 0.8, "n": 150}])

    await mod._run_audit(pool)

    mock_counter.add.assert_not_called()
    mock_gauge.set.assert_called_once_with(0.8, {"setup_plugin": "trend_following"})


@pytest.mark.asyncio
async def test_none_calibration_fallback(monkeypatch):
    """calibration=None uses 0.0 fallback for gauge; no alert fired."""
    import services.confidence_calibration_monitor as mod

    mock_gauge = MagicMock()
    mock_counter = MagicMock()
    monkeypatch.setattr(mod, "SIGNAL_CONFIDENCE_CALIBRATION", mock_gauge)
    monkeypatch.setattr(mod, "CONFIDENCE_CALIBRATION_ALERTS_TOTAL", mock_counter)

    pool = _make_pool([{"setup_plugin": "squeeze_expansion", "calibration": None, "n": 150}])

    await mod._run_audit(pool)

    mock_gauge.set.assert_called_once_with(0.0, {"setup_plugin": "squeeze_expansion"})
    mock_counter.add.assert_not_called()
