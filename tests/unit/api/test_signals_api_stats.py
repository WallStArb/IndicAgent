"""Tests for GET /api/signals/stats."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from src.api.dependencies import get_db_manager
from src.api.main import app


def _stats_row(**kwargs):
    defaults = {
        "signals_today": 42,
        "signals_prev_session": 38,
        "hero_count_today": 12,
        "selected_count_today": 20,
        "avg_confidence_today": 0.52,
        "avg_confidence_7d": 0.48,
        "latency_p50": 4.2,
        "latency_p95": 12.1,
        "avg_pnl_r_7d": 0.31,
        "avg_pnl_r_30d": 0.22,
    }
    return {**defaults, **kwargs}


@pytest.mark.unit
class TestSignalsApiStats:
    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_stats_returns_200(self):
        mock_db = AsyncMock()
        mock_db.fetchrow = AsyncMock(return_value=_stats_row())
        mock_db.fetch = AsyncMock(return_value=[])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        resp = TestClient(app).get("/api/signals/stats")
        assert resp.status_code == 200

    def test_stats_schema(self):
        mock_db = AsyncMock()
        mock_db.fetchrow = AsyncMock(return_value=_stats_row())
        mock_db.fetch = AsyncMock(return_value=[])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get("/api/signals/stats").json()
        assert "signals_today" in data
        assert "hero_rate" in data
        assert "avg_confidence" in data
        assert "pipeline_latency_p50" in data
        assert "alpha_7d" in data
        assert "edge_trend" in data

    def test_edge_trend_expanding(self):
        """alpha_7d > alpha_30d → edge_trend='expanding'."""
        mock_db = AsyncMock()
        mock_db.fetchrow = AsyncMock(return_value=_stats_row(avg_pnl_r_7d=0.4, avg_pnl_r_30d=0.2))
        mock_db.fetch = AsyncMock(return_value=[])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get("/api/signals/stats").json()
        assert data["edge_trend"] == "expanding"

    def test_edge_trend_compressing(self):
        """alpha_7d < alpha_30d → edge_trend='compressing'."""
        mock_db = AsyncMock()
        mock_db.fetchrow = AsyncMock(return_value=_stats_row(avg_pnl_r_7d=0.1, avg_pnl_r_30d=0.3))
        mock_db.fetch = AsyncMock(return_value=[])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get("/api/signals/stats").json()
        assert data["edge_trend"] == "compressing"

    def test_hero_rate_zero_denominator(self):
        """selected_count_today=0 → hero_rate=0.0 (no division by zero)."""
        mock_db = AsyncMock()
        mock_db.fetchrow = AsyncMock(
            return_value=_stats_row(hero_count_today=0, selected_count_today=0)
        )
        mock_db.fetch = AsyncMock(return_value=[])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get("/api/signals/stats").json()
        assert data["hero_rate"] == 0.0

    def test_stats_includes_recent_outcomes(self):
        mock_db = AsyncMock()
        mock_db.fetchrow = AsyncMock(return_value=_stats_row())
        mock_db.fetch = AsyncMock(
            return_value=[
                {"exit_reason": "target_1", "actual_pnl_r": 1.5},
                {"exit_reason": "stop_loss", "actual_pnl_r": -1.0},
            ]
        )
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get("/api/signals/stats").json()
        assert "recent_outcomes" in data
        assert len(data["recent_outcomes"]) == 2
        assert data["recent_outcomes"][0]["outcome"] == "target_1"
        assert data["recent_outcomes"][0]["pnl_r"] == 1.5

    def test_stats_recent_outcomes_empty_when_no_resolved(self):
        mock_db = AsyncMock()
        mock_db.fetchrow = AsyncMock(return_value=_stats_row())
        mock_db.fetch = AsyncMock(return_value=[])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get("/api/signals/stats").json()
        assert data["recent_outcomes"] == []


def _recent_row(**kwargs):
    import json
    import uuid
    from datetime import datetime

    defaults = {
        "signal_id": str(uuid.uuid4()),
        "setup_plugin": "trad_FailedBreakout",
        "direction": "long",
        "entry_price": 5285.5,
        "stop_loss": 5278.0,
        "confidence": 0.72,
        "was_selected": True,
        "cis_score": 0.45,
        "status": "expired",
        "pnl_r": 1.5,
        "signal_computed_at": datetime(2026, 6, 4, 14, 32, 7),
        "timeframe": "1m",
        "symbol": "ES",
        "setup_win_rate": 0.083,
        "setup_avg_pnl_r": 0.175,
        "hmm_regime_at_fire": 0,
        "exit_reason": "target_1",
        "ttl_bars": 10,
        "targets": json.dumps([5296.0, 5302.0]),
        "entry_type": "at_close",
    }
    return {**defaults, **kwargs}


@pytest.mark.unit
class TestRecentSignalsEnhanced:
    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_recent_includes_regime_and_r_ratio(self):
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[_recent_row()])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get("/api/signals/recent?tier=all&limit=10").json()
        sig = data["signals"][0]
        assert sig["hmm_regime_at_fire"] == 0
        assert sig["exit_reason"] == "target_1"
        assert sig["ttl_bars"] == 10
        assert sig["r_ratio"] == pytest.approx(1.37, abs=0.05)

    def test_r_ratio_null_when_no_targets(self):
        import json

        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[_recent_row(targets=json.dumps([]))])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get("/api/signals/recent?tier=all&limit=10").json()
        assert data["signals"][0]["r_ratio"] is None
