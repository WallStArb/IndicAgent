"""
Unit tests for the Market Data API route.

Regression guard: GET /api/market-data/{symbol}/{timeframe} must return 404 (not
500) when no rows match -- the route raises HTTPException(404) itself but the
surrounding `except Exception` used to re-catch it and re-wrap it as a 500,
found by the request-level route smoke test (todo 137).
"""

from unittest.mock import AsyncMock


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
