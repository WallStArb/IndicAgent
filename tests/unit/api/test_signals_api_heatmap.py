"""Tests for GET /api/signals/heatmap."""

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


def _heatmap_row(**kwargs):
    defaults = {
        "setup_plugin": "trad_FailedBreakout",
        "regime": 0,
        "n": 41715,
        "avg_r": 0.175,
        "win_rate": 0.083,
    }
    return {**defaults, **kwargs}


@pytest.mark.unit
class TestSignalsHeatmap:
    def teardown_method(self):
        test_app.dependency_overrides.clear()

    def test_heatmap_returns_200(self):
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[_heatmap_row()])
        data = _make_client(mock_db).get("/api/signals/heatmap").json()
        assert "cells" in data
        assert len(data["cells"]) == 1

    def test_heatmap_cell_schema(self):
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[_heatmap_row()])
        data = _make_client(mock_db).get("/api/signals/heatmap").json()
        cell = data["cells"][0]
        assert cell["setup_plugin"] == "trad_FailedBreakout"
        assert cell["regime"] == 0
        assert cell["n"] == 41715
        assert cell["avg_r"] == pytest.approx(0.175)
        assert cell["win_rate"] == pytest.approx(0.083)

    def test_heatmap_empty_returns_empty_cells(self):
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[])
        data = _make_client(mock_db).get("/api/signals/heatmap").json()
        assert data["cells"] == []
