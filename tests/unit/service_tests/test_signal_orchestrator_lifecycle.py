"""Tests for lifecycle tracking path."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def _make_service():
    with patch("services.signal_orchestrator_service.start_metrics_server"):
        from services.signal_orchestrator_service import SignalOrchestratorService
        return SignalOrchestratorService()


def _active_signal(signal_id: str, status: str = "pending", direction: int = 1) -> dict:
    return {
        "signal_id": signal_id,
        "status": status,
        "direction": direction,
        "entry_price": 5103.0,
        "stop_loss": 5083.0,
        "targets": [5123.0, 5143.0, 5163.0],
        "ttl_bars": 20,
        "bars_elapsed": 0,
        "point_value": 50.0,
        "timeframe": "5m",
    }


@pytest.mark.asyncio
async def test_track_lifecycle_activates_pending_signal():
    """Pending signal transitions to active when high >= entry."""
    svc = _make_service()
    svc.db_manager = MagicMock()

    pending = _active_signal("test-uuid-1", status="pending", direction=1)

    with patch("services.signal_orchestrator_service.get_active_signals",
               new=AsyncMock(return_value=[pending])):
        with patch("services.signal_orchestrator_service.update_signal_status",
                   new=AsyncMock()) as mock_update:
            bar = {"open": 5100.0, "high": 5104.0, "low": 5099.0, "close": 5103.0}
            ts = datetime(2026, 2, 18, 10, 5, 0, tzinfo=timezone.utc)
            await svc._track_lifecycle("ESH6", "5m", bar, ts)

    mock_update.assert_called_once()
    call_kwargs = mock_update.call_args.kwargs
    assert call_kwargs["status"] == "active"


@pytest.mark.asyncio
async def test_track_lifecycle_stops_out_active_signal():
    """Active signal transitions to stopped_out when low <= stop_loss."""
    svc = _make_service()
    svc.db_manager = MagicMock()

    active = _active_signal("test-uuid-2", status="active", direction=1)

    with patch("services.signal_orchestrator_service.get_active_signals",
               new=AsyncMock(return_value=[active])):
        with patch("services.signal_orchestrator_service.update_signal_status",
                   new=AsyncMock()) as mock_update:
            # Low dips below stop_loss (5083.0)
            bar = {"open": 5085.0, "high": 5086.0, "low": 5080.0, "close": 5082.0}
            ts = datetime(2026, 2, 18, 10, 10, 0, tzinfo=timezone.utc)
            await svc._track_lifecycle("ESH6", "5m", bar, ts)

    mock_update.assert_called_once()
    call_kwargs = mock_update.call_args.kwargs
    assert call_kwargs["status"] == "stopped_out"
    assert call_kwargs["pnl_r"] < 0


@pytest.mark.asyncio
async def test_track_lifecycle_skips_different_timeframe_signals():
    """Signals from a different timeframe are NOT evaluated on this bar."""
    svc = _make_service()
    svc.db_manager = MagicMock()

    signal_1h = _active_signal("test-uuid-3", status="pending")
    signal_1h["timeframe"] = "1h"  # This is a 1h signal

    with patch("services.signal_orchestrator_service.get_active_signals",
               new=AsyncMock(return_value=[signal_1h])):
        with patch("services.signal_orchestrator_service.update_signal_status",
                   new=AsyncMock()) as mock_update:
            # We're processing a 5m bar
            bar = {"open": 5100.0, "high": 5104.0, "low": 5099.0, "close": 5103.0}
            ts = datetime(2026, 2, 18, 10, 5, 0, tzinfo=timezone.utc)
            await svc._track_lifecycle("ESH6", "5m", bar, ts)

    assert not mock_update.called  # 1h signal not evaluated on 5m bar


@pytest.mark.asyncio
async def test_track_lifecycle_no_update_when_no_transition():
    """No DB update when signal price conditions aren't met."""
    svc = _make_service()
    svc.db_manager = MagicMock()

    pending = _active_signal("test-uuid-4", status="pending", direction=1)

    with patch("services.signal_orchestrator_service.get_active_signals",
               new=AsyncMock(return_value=[pending])):
        with patch("services.signal_orchestrator_service.update_signal_status",
                   new=AsyncMock()) as mock_update:
            # High (5101) below entry (5103) — no activation
            bar = {"open": 5098.0, "high": 5101.0, "low": 5097.0, "close": 5099.0}
            ts = datetime(2026, 2, 18, 10, 5, 0, tzinfo=timezone.utc)
            await svc._track_lifecycle("ESH6", "5m", bar, ts)

    assert not mock_update.called
