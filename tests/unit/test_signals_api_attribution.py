"""Tests for GET /api/signals/attribution."""
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from src.api.dependencies import get_db_manager
from src.api.main import app


def _row(**kwargs):
    defaults = {
        "group_key": "trad_TrendFollowing",
        "n": 120,
        "win_rate": 0.58,
        "avg_pnl_r": 0.42,
        "std_pnl_r": 1.1,
        "n_pnl": 100,
    }
    return {**defaults, **kwargs}

@pytest.mark.unit
class TestSignalsApiAttribution:
    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_attribution_returns_200(self):
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[_row()])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        resp = TestClient(app).get("/api/signals/attribution?window=30d&group_by=setup")
        assert resp.status_code == 200

    def test_attribution_schema(self):
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[_row()])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get("/api/signals/attribution?window=30d&group_by=setup").json()
        assert "groups" in data
        assert len(data["groups"]) == 1
        g = data["groups"][0]
        assert "name" in g
        assert "n" in g
        assert "win_rate" in g
        assert "avg_pnl_r" in g
        assert "sharpe_proxy" in g
        assert "p_value" in g

    def test_p_value_significant_for_large_n(self):
        """N=1000, avg=0.3, std=1.0 → t=9.5 → p < 0.05."""
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(
            return_value=[_row(n=1000, avg_pnl_r=0.3, std_pnl_r=1.0, n_pnl=1000)]
        )
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get("/api/signals/attribution?window=30d&group_by=setup").json()
        assert data["groups"][0]["p_value"] < 0.05

    def test_p_value_not_significant_for_small_n(self):
        """N=5, avg=0.1, std=2.0 → t=0.11 → p > 0.05."""
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[_row(n=5, avg_pnl_r=0.1, std_pnl_r=2.0, n_pnl=5)])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get("/api/signals/attribution?window=30d&group_by=setup").json()
        assert data["groups"][0]["p_value"] > 0.05

    def test_sharpe_zero_std_returns_none(self):
        """std_pnl_r=0 → sharpe_proxy=None (guard division by zero)."""
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[_row(std_pnl_r=0.0)])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get("/api/signals/attribution?window=30d&group_by=setup").json()
        assert data["groups"][0]["sharpe_proxy"] is None

    def test_window_param_7d_accepted(self):
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        resp = TestClient(app).get("/api/signals/attribution?window=7d&group_by=setup")
        assert resp.status_code == 200
