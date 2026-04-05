"""Tests for SignalMetricsWriterAgent."""
from unittest.mock import AsyncMock

import pytest

from services.signal_metrics_writer_agent import (
    _handle_dq_failure,
    _handle_ic_computed,
    _handle_metrics_computed,
)


class TestHandleMetricsComputed:
    @pytest.mark.asyncio
    async def test_upserts_signal_metrics_table(self):
        conn = AsyncMock()
        event = {
            "track": "zone",
            "setup_plugin": "trad_TrendFollowing",
            "tf": "5m",
            "regime_type": "trend",
            "window_days": 30,
            "n": 45,
            "n_outliers": 2,
            "never_activated_pct": 0.15,
            "win_rate": 0.52,
            "avg_r": 0.31,
            "std_r": 0.88,
            "sharpe": 0.35,
            "p_value": 0.03,
            "avg_mae": -0.42,
            "avg_mfe": 0.95,
            "computed_at": "2026-04-05T12:00:00+00:00",
        }
        await _handle_metrics_computed(conn, event)
        conn.execute.assert_called_once()
        sql = conn.execute.call_args[0][0]
        assert "signal_metrics" in sql
        assert "ON CONFLICT" in sql

    @pytest.mark.asyncio
    async def test_updates_setup_performance_shim_for_market_track_30d(self):
        conn = AsyncMock()
        event = {
            "track": "market",
            "setup_plugin": "trad_TrendFollowing",
            "tf": "5m",
            "regime_type": "all",
            "window_days": 30,
            "n": 45,
            "n_outliers": 0,
            "never_activated_pct": None,
            "win_rate": 0.52,
            "avg_r": 0.31,
            "std_r": 0.88,
            "sharpe": 0.35,
            "p_value": 0.03,
            "avg_mae": -0.42,
            "avg_mfe": 0.95,
            "computed_at": "2026-04-05T12:00:00+00:00",
        }
        await _handle_metrics_computed(conn, event)
        assert conn.execute.call_count == 2  # signal_metrics + setup_performance shim

    @pytest.mark.asyncio
    async def test_no_setup_performance_update_for_zone_track(self):
        conn = AsyncMock()
        event = {
            "track": "zone",
            "setup_plugin": "trad_TrendFollowing",
            "tf": "5m",
            "regime_type": "all",
            "window_days": 30,
            "n": 45,
            "n_outliers": 0,
            "never_activated_pct": 0.1,
            "win_rate": 0.52,
            "avg_r": 0.31,
            "std_r": 0.88,
            "sharpe": 0.35,
            "p_value": 0.03,
            "avg_mae": -0.42,
            "avg_mfe": 0.95,
            "computed_at": "2026-04-05T12:00:00+00:00",
        }
        await _handle_metrics_computed(conn, event)
        assert conn.execute.call_count == 1  # signal_metrics only


class TestHandleIcComputed:
    @pytest.mark.asyncio
    async def test_upserts_signal_metrics_ic(self):
        conn = AsyncMock()
        event = {
            "setup_plugin": "trad_TrendFollowing",
            "tf": "5m",
            "regime_type": "trend",
            "window_days": 30,
            "n": 45,
            "ic": 0.12,
            "p_value": 0.02,
            "is_significant": True,
            "computed_at": "2026-04-05T12:00:00+00:00",
        }
        await _handle_ic_computed(conn, event)
        conn.execute.assert_called_once()
        assert "signal_metrics_ic" in conn.execute.call_args[0][0]


class TestHandleDqFailure:
    @pytest.mark.asyncio
    async def test_inserts_to_dq_failures(self):
        conn = AsyncMock()
        event = {
            "signal_id": "00000000-0000-0000-0000-000000000001",
            "reason_code": "risk_below_min_tick",
            "entry_price": 5000.0,
            "stop_loss": 5000.01,
            "pnl_r": -193.0,
            "direction": 1,
            "hmm_regime": 1,
            "setup_plugin": "trad_CVDDivergence",
            "created_at": "2026-04-05T12:00:00+00:00",
        }
        await _handle_dq_failure(conn, event)
        conn.execute.assert_called_once()
        assert "signal_metrics_dq_failures" in conn.execute.call_args[0][0]
