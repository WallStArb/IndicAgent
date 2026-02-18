"""Tests for signal generation path: plugins → aggregate → insert → publish."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def _make_frames(n_bars: int = 60) -> dict:
    import pandas as pd
    import numpy as np
    bars = pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n_bars, freq="5min"),
        "open":  5100.0 + np.random.randn(n_bars),
        "high":  5105.0 + np.random.randn(n_bars),
        "low":   5095.0 + np.random.randn(n_bars),
        "close": 5100.0 + np.random.randn(n_bars),
        "volume": np.random.randint(1000, 5000, n_bars),
    })
    return {"main": bars, "features": {"trend_regime": 0.7, "atr_14": 12.5}}


def _make_service():
    with patch("services.signal_orchestrator_service.start_metrics_server"):
        from services.signal_orchestrator_service import SignalOrchestratorService
        return SignalOrchestratorService()


def test_run_setup_plugins_returns_only_directional_signals():
    """Only signals with direction != 0 are returned."""
    svc = _make_service()

    from src.intelligence.register_plugins import register_all_plugins
    register_all_plugins()

    frames = _make_frames(60)
    signals = svc._run_setup_plugins(frames)

    # All returned signals must have a real direction
    for sig in signals:
        assert sig.get("direction", 0) != 0
        assert "setup_plugin" in sig


def test_run_setup_plugins_handles_plugin_failure_gracefully():
    """If a plugin raises, the others still run."""
    svc = _make_service()

    from src.intelligence.register_plugins import register_all_plugins
    register_all_plugins()

    from src.intelligence.plugins import registry
    original = registry.get_pattern("trad_TrendFollowing").compute_full

    def boom(frames):
        raise RuntimeError("plugin exploded")

    registry.get_pattern("trad_TrendFollowing").compute_full = boom
    try:
        frames = _make_frames(60)
        signals = svc._run_setup_plugins(frames)
        # Should not raise; other plugins still ran (result may be empty or not)
        assert isinstance(signals, list)
    finally:
        registry.get_pattern("trad_TrendFollowing").compute_full = original


@pytest.mark.asyncio
async def test_process_bar_inserts_signals_when_plugins_fire():
    """When plugins produce signals, they are inserted into signal_ledger."""
    svc = _make_service()
    svc.db_manager = MagicMock()
    svc.redis_client = AsyncMock()
    svc.redis_client.xadd = AsyncMock()

    # Mock insert_signals to capture calls
    with patch("services.signal_orchestrator_service.insert_signals", new=AsyncMock()) as mock_insert:
        with patch("services.signal_orchestrator_service.get_active_signals", new=AsyncMock(return_value=[])):
            frames = _make_frames(60)
            bar = {"open": 5100.0, "high": 5105.0, "low": 5098.0, "close": 5103.0, "volume": 10000}
            features = {"trend_regime": 0.7, "atr_14": 12.5, "ctf_score": 0.8}
            ts = datetime(2026, 2, 18, 10, 0, 0, tzinfo=timezone.utc)

            # Inject fake plugin signals
            fake_signal = {
                "type": "signal.v1", "signal_type": "trend_following",
                "setup_plugin": "trad_TrendFollowing", "direction": 1,
                "entry_price": 5103.0, "stop_loss": 5083.0,
                "targets": [5123.0, 5143.0, 5163.0],
                "confidence": 0.72, "risk_reward_ratio": 1.0,
                "regime_context": "trending_bull", "confluence_score": 0.8,
                "supporting_factors": [], "invalidation_conditions": [],
                "ttl_bars": 20, "symbol": "ESH6", "timeframe": "5m",
                "timestamp": "2026-02-18T10:00:00",
            }
            with patch.object(svc, "_run_setup_plugins", return_value=[fake_signal]):
                await svc._process_bar("ESH6", "5m", bar, features, frames, ts)

        # insert_signals was called with at least one entry
        assert mock_insert.called
        entries = mock_insert.call_args[0][1]
        assert len(entries) >= 1


@pytest.mark.asyncio
async def test_process_bar_publishes_winner_to_redis():
    """When aggregate selects a winner, it publishes to signals_aggregated stream."""
    svc = _make_service()
    svc.db_manager = MagicMock()
    svc.redis_client = AsyncMock()
    svc.redis_client.xadd = AsyncMock()

    with patch("services.signal_orchestrator_service.insert_signals", new=AsyncMock()):
        with patch("services.signal_orchestrator_service.get_active_signals", new=AsyncMock(return_value=[])):
            fake_signal = {
                "type": "signal.v1", "signal_type": "trend_following",
                "setup_plugin": "trad_TrendFollowing", "direction": 1,
                "entry_price": 5103.0, "stop_loss": 5083.0,
                "targets": [5123.0, 5143.0, 5163.0],
                "confidence": 0.72, "risk_reward_ratio": 1.0,
                "regime_context": "trending_bull", "confluence_score": 0.8,
                "supporting_factors": [], "invalidation_conditions": [],
                "ttl_bars": 20, "symbol": "ESH6", "timeframe": "5m",
                "timestamp": "2026-02-18T10:00:00",
            }
            bar = {"open": 5100.0, "high": 5105.0, "low": 5098.0, "close": 5103.0, "volume": 10000}
            features = {"trend_regime": 0.7, "ctf_score": 0.8}
            ts = datetime(2026, 2, 18, 10, 0, 0, tzinfo=timezone.utc)
            frames = _make_frames(60)

            with patch.object(svc, "_run_setup_plugins", return_value=[fake_signal]):
                await svc._process_bar("ESH6", "5m", bar, features, frames, ts)

    # xadd must have been called for the aggregated stream
    assert svc.redis_client.xadd.called


@pytest.mark.asyncio
async def test_process_bar_skips_when_too_few_bars():
    """Processing is skipped when bar history is below min_history_bars."""
    svc = _make_service()
    svc.db_manager = MagicMock()
    svc.redis_client = AsyncMock()

    with patch("services.signal_orchestrator_service.insert_signals", new=AsyncMock()) as mock_insert:
        import pandas as pd
        # Only 10 bars — below min_history_bars=50
        frames = {"main": pd.DataFrame({"close": [100.0] * 10}), "features": {}}
        bar = {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000}
        ts = datetime(2026, 2, 18, 10, 0, 0, tzinfo=timezone.utc)

        await svc._process_bar("ESH6", "5m", bar, {}, frames, ts)

    assert not mock_insert.called
