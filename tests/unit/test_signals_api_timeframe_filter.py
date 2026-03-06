"""Test that /api/signals/{symbol} respects ?timeframe= filter."""
import pytest
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from src.api.main import app
from src.api.dependencies import get_db_manager


@pytest.mark.unit
class TestSignalsApiTimeframeFilter:
    def _client_with_mock_db(self, mock_db):
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        client = TestClient(app)
        yield client
        app.dependency_overrides.clear()

    def test_timeframe_param_accepted(self):
        """?timeframe=5m must not return 404 or 422."""
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        try:
            client = TestClient(app)
            resp = client.get("/api/signals/ESH6?timeframe=5m")
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()

    def test_timeframe_filter_passed_to_query(self):
        """fetch() must be called with timeframe as a bound parameter."""
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        try:
            client = TestClient(app)
            client.get("/api/signals/ESH6?timeframe=5m")
        finally:
            app.dependency_overrides.clear()

        call_args = mock_db.fetch.call_args[0]
        # timeframe="5m" must appear somewhere in the positional args
        assert "5m" in call_args
