"""Tests for GET /api/signals/edge-series and /api/signals/intraday-heatmap."""

from datetime import date
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import dependencies
from src.api.routes.signals import router as signals_router

test_app = FastAPI()
test_app.include_router(signals_router, prefix="/api")


def _make_client(mock_db):
    test_app.dependency_overrides[dependencies.get_db_manager] = lambda: mock_db
    return TestClient(test_app)


@pytest.mark.unit
class TestEdgeSeries:
    def teardown_method(self):
        test_app.dependency_overrides.clear()

    def test_edge_series_returns_200(self):
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(
            return_value=[
                {"day": date(2026, 6, 3), "n": 100, "avg_r": 0.15, "win_rate": 0.12},
            ]
        )
        data = _make_client(mock_db).get("/api/signals/edge-series").json()
        assert "series" in data
        assert len(data["series"]) == 1

    def test_edge_series_point_schema(self):
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(
            return_value=[
                {"day": date(2026, 6, 3), "n": 100, "avg_r": 0.15, "win_rate": 0.12},
            ]
        )
        data = _make_client(mock_db).get("/api/signals/edge-series").json()
        pt = data["series"][0]
        assert "day" in pt
        assert pt["avg_r"] == pytest.approx(0.15)
        assert pt["win_rate"] == pytest.approx(0.12)
        assert pt["n"] == 100


@pytest.mark.unit
class TestIntradayHeatmap:
    def teardown_method(self):
        test_app.dependency_overrides.clear()

    def test_intraday_heatmap_returns_200(self):
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(
            return_value=[
                {"hour": 9, "dow": 1, "n": 250, "avg_r": 0.22},
            ]
        )
        data = _make_client(mock_db).get("/api/signals/intraday-heatmap").json()
        assert "cells" in data
        assert len(data["cells"]) == 1

    def test_intraday_cell_schema(self):
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(
            return_value=[
                {"hour": 10, "dow": 3, "n": 180, "avg_r": -0.05},
            ]
        )
        data = _make_client(mock_db).get("/api/signals/intraday-heatmap").json()
        cell = data["cells"][0]
        assert cell["hour"] == 10
        assert cell["dow"] == 3
        assert cell["avg_r"] == pytest.approx(-0.05)
