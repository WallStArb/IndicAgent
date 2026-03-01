"""Tests for signal_tracker_service — standalone lifecycle tracking service."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def test_signal_tracker_service_imports():
    from services.signal_tracker_service import SignalTrackerService

    svc = SignalTrackerService()
    assert hasattr(svc, "_evaluate_signals_against_bar")


def test_evaluate_signals_against_bar_no_db_returns_empty():
    """Without a DB connection, evaluation must return empty list (not raise)."""
    from services.signal_tracker_service import SignalTrackerService

    svc = SignalTrackerService()
    svc.db_manager = None

    transitions = asyncio.get_event_loop().run_until_complete(
        svc._evaluate_signals_against_bar(
            "ES", "1m", {"high": 5305.0, "low": 5298.0, "close": 5303.0}
        )
    )
    assert transitions == []


def test_evaluate_signals_against_bar_calls_evaluate_signal():
    """Each active signal must be passed through evaluate_signal."""
    from services.signal_tracker_service import SignalTrackerService

    svc = SignalTrackerService()
    svc.db_manager = MagicMock()
    svc.point_values = {"ES": 50.0}

    fake_signal = {
        "signal_id": "abc",
        "symbol": "ES",
        "timeframe": "1m",
        "direction": 1,
        "entry_price": 5300.0,
        "stop_loss": 5295.0,
        "targets": [5310.0],
        "status": "active",
        "bars_open": 2,
        "timeframe_ttl": 30,
    }

    with patch(
        "services.signal_tracker_service.get_active_signals",
        new=AsyncMock(return_value=[fake_signal]),
    ):
        with patch(
            "services.signal_tracker_service.evaluate_signal", return_value=None
        ) as mock_eval:
            asyncio.get_event_loop().run_until_complete(
                svc._evaluate_signals_against_bar(
                    "ES", "1m", {"high": 5305.0, "low": 5299.0, "close": 5303.0}
                )
            )
            mock_eval.assert_called_once()


def test_stream_map_populated_after_setup():
    """_stream_map must have one entry per symbol (1m only)."""
    import asyncio
    from unittest.mock import AsyncMock

    from services.signal_tracker_service import SignalTrackerService

    svc = SignalTrackerService()
    svc.redis_client = AsyncMock()
    svc.redis_client.xgroup_create = AsyncMock(side_effect=Exception("exists"))
    svc.redis_client.xgroup_setid = AsyncMock()
    svc.db_manager = None

    asyncio.get_event_loop().run_until_complete(svc._setup_consumer_groups())

    symbols = svc.config["service"]["symbols"]
    assert len(svc._stream_map) == len(symbols)
    for stream_name, (sym, tf) in svc._stream_map.items():
        assert tf == "1m"
        assert sym in symbols
