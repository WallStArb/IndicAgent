"""Tests for GET /api/signals/attribution — reads pre-computed signal_metrics table."""
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from src.api.dependencies import get_db_manager
from src.api.main import app


def _row(**kwargs):
    """Mock row matching signal_metrics + LEFT JOIN signal_metrics_ic columns."""
    defaults = {
        "group_key": "trad_TrendFollowing",
        "n": 120,
        "win_rate": 0.58,
        "avg_pnl_r": 0.42,
        "sharpe_proxy": 1.35,
        "p_value": 0.003,
        "n_outliers": 2,
        "never_activated_pct": 0.05,
        "ic_score": 0.12,
        "ic_significant": True,
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

    def test_p_value_passed_through_from_signal_metrics(self):
        """p_value is read directly from signal_metrics — no inline computation."""
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[_row(p_value=0.001)])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get("/api/signals/attribution?window=30d&group_by=setup").json()
        assert data["groups"][0]["p_value"] == pytest.approx(0.001)

    def test_p_value_none_when_null_in_db(self):
        """NULL p_value in DB → None in response."""
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[_row(p_value=None)])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get("/api/signals/attribution?window=30d&group_by=setup").json()
        assert data["groups"][0]["p_value"] is None

    def test_sharpe_passed_through_from_signal_metrics(self):
        """sharpe read from signal_metrics.sharpe column directly."""
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[_row(sharpe_proxy=2.5)])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get("/api/signals/attribution?window=30d&group_by=setup").json()
        assert data["groups"][0]["sharpe_proxy"] == pytest.approx(2.5)

    def test_track_param_zone_accepted(self):
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        resp = TestClient(app).get("/api/signals/attribution?window=30d&group_by=setup&track=zone")
        assert resp.status_code == 200

    def test_track_param_market_accepted(self):
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        resp = TestClient(app).get("/api/signals/attribution?window=30d&group_by=setup&track=market")
        assert resp.status_code == 200

    def test_window_param_7d_accepted(self):
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        resp = TestClient(app).get("/api/signals/attribution?window=7d&group_by=setup")
        assert resp.status_code == 200

    def test_insufficient_data_flag_set_when_n_lt_30(self):
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[_row(n=15)])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get("/api/signals/attribution?window=30d&group_by=setup").json()
        assert data["groups"][0]["insufficient_data"] is True

    def test_insufficient_data_false_when_n_gte_30(self):
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[_row(n=30)])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get("/api/signals/attribution?window=30d&group_by=setup").json()
        assert data["groups"][0]["insufficient_data"] is False
