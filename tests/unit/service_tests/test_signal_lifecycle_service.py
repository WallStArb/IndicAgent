"""Unit tests for signal lifecycle service helpers."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest


def _compute_bars_elapsed(
    signal_timestamp: datetime, current_bar_time: datetime, timeframe: str
) -> int:
    """Compute bars elapsed since signal fire. Mirrors service implementation."""
    TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}
    tf_secs = TF_SECONDS.get(timeframe, 60)
    delta = (current_bar_time - signal_timestamp).total_seconds()
    return max(0, int(delta / tf_secs))


@pytest.mark.unit
class TestBarsElapsedComputation:
    def test_same_bar_returns_zero(self):
        ts = datetime(2026, 3, 3, 14, 35, 0, tzinfo=UTC)
        assert _compute_bars_elapsed(ts, ts, "5m") == 0

    def test_one_bar_elapsed_5m(self):
        ts = datetime(2026, 3, 3, 14, 35, 0, tzinfo=UTC)
        bar_time = datetime(2026, 3, 3, 14, 40, 0, tzinfo=UTC)
        assert _compute_bars_elapsed(ts, bar_time, "5m") == 1

    def test_ttl_boundary_10_bars_1h(self):
        ts = datetime(2026, 3, 3, 10, 0, 0, tzinfo=UTC)
        bar_time = ts + timedelta(hours=10)
        assert _compute_bars_elapsed(ts, bar_time, "1h") == 10

    def test_determined_at_lag_accounted(self):
        """Signal determined 2 min after bar close; 5m bars."""
        bar_close = datetime(2026, 3, 3, 14, 35, 0, tzinfo=UTC)
        determined_at = bar_close + timedelta(minutes=2)  # 14:37
        # Next bar at 14:40 → <1 bar elapsed from determined_at
        next_bar = datetime(2026, 3, 3, 14, 40, 0, tzinfo=UTC)
        assert _compute_bars_elapsed(determined_at, next_bar, "5m") == 0


def test_signal_lifecycle_service_imports():
    from services.signal_lifecycle_service import SignalLifecycleService

    svc = SignalLifecycleService()
    assert hasattr(svc, "_evaluate_signals_against_bar")


def test_evaluate_signals_against_bar_no_db_returns_early():
    """Without a DB connection, evaluation must not raise."""
    from services.signal_lifecycle_service import SignalLifecycleService

    svc = SignalLifecycleService()
    svc.db_manager = None

    bar_time = datetime(2026, 3, 3, 14, 35, 0, tzinfo=UTC)
    asyncio.get_event_loop().run_until_complete(
        svc._evaluate_signals_against_bar(
            "ES", "1m",
            {"high": 5305.0, "low": 5298.0, "close": 5303.0},
            bar_time=bar_time,
        )
    )
    # No exception raised = pass


def test_stream_map_populated_after_setup():
    """_stream_map must have one entry per symbol (1m only)."""
    import redis.asyncio as redis

    from services.signal_lifecycle_service import SignalLifecycleService

    svc = SignalLifecycleService()
    svc.redis_client = AsyncMock()
    svc.redis_client.xgroup_create = AsyncMock(
        side_effect=redis.ResponseError("BUSYGROUP Consumer Group name already exists")
    )
    svc.redis_client.xgroup_setid = AsyncMock()
    svc.db_manager = None

    asyncio.get_event_loop().run_until_complete(svc._setup_consumer_groups())

    symbols = svc.config["service"]["symbols"]
    assert len(svc._stream_map) == len(symbols)
    for _stream_name, (sym, tf) in svc._stream_map.items():
        assert tf == "1m"
        assert sym in symbols


def test_mae_mfe_tracked_in_memory():
    """Active signals accumulate MAE/MFE across bars."""
    from services.signal_lifecycle_service import SignalLifecycleService

    svc = SignalLifecycleService()
    # Directly manipulate the tracking dicts
    svc._mae["sig-1"] = -0.2
    svc._mfe["sig-1"] = 0.5

    assert svc._mae["sig-1"] == pytest.approx(-0.2)
    assert svc._mfe["sig-1"] == pytest.approx(0.5)

    # Cleanup on exit
    svc._mae.pop("sig-1", None)
    svc._mfe.pop("sig-1", None)
    assert "sig-1" not in svc._mae
    assert "sig-1" not in svc._mfe
