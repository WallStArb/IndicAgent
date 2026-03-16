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
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        resp = TestClient(app).get("/api/signals/stats")
        assert resp.status_code == 200

    def test_stats_schema(self):
        mock_db = AsyncMock()
        mock_db.fetchrow = AsyncMock(return_value=_stats_row())
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
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get("/api/signals/stats").json()
        assert data["edge_trend"] == "expanding"

    def test_edge_trend_compressing(self):
        """alpha_7d < alpha_30d → edge_trend='compressing'."""
        mock_db = AsyncMock()
        mock_db.fetchrow = AsyncMock(return_value=_stats_row(avg_pnl_r_7d=0.1, avg_pnl_r_30d=0.3))
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get("/api/signals/stats").json()
        assert data["edge_trend"] == "compressing"

    def test_hero_rate_zero_denominator(self):
        """selected_count_today=0 → hero_rate=0.0 (no division by zero)."""
        mock_db = AsyncMock()
        mock_db.fetchrow = AsyncMock(
            return_value=_stats_row(hero_count_today=0, selected_count_today=0)
        )
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get("/api/signals/stats").json()
        assert data["hero_rate"] == 0.0
