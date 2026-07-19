"""
Unit tests for the Market Data API route.

Regression guard: GET /api/market-data/{symbol}/{timeframe} must return 404 (not
500) when no rows match -- the route raises HTTPException(404) itself but the
surrounding `except Exception` used to re-catch it and re-wrap it as a 500,
found by the request-level route smoke test (todo 137).
"""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import dependencies
from src.api.routes.market_data import router as market_data_router

test_app = FastAPI()
test_app.include_router(market_data_router, prefix="/api")


@pytest.fixture
def mock_db():
    return AsyncMock()


@pytest.fixture
def client(mock_db):
    test_app.dependency_overrides[dependencies.get_db_manager] = lambda: mock_db
    yield TestClient(test_app)
    test_app.dependency_overrides.clear()


class TestGetMarketData:
    def test_no_rows_returns_404_not_500(self, client, mock_db):
        mock_db.fetch = AsyncMock(return_value=[])

        response = client.get("/api/market-data/SPY/5m")

        assert response.status_code == 404
        assert "SPY" in response.json()["detail"]

    def test_genuine_db_error_still_returns_500(self, client, mock_db):
        mock_db.fetch = AsyncMock(side_effect=RuntimeError("connection refused"))

        response = client.get("/api/market-data/SPY/5m")

        assert response.status_code == 500
