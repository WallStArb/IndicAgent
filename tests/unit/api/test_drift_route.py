"""
Unit tests for the Drift Monitor API route.

Tests cover:
- GET /api/drift, happy path: returns KS and CUSUM entries from the drift_state table
- GET /api/drift, a DB query failure degrades to an empty response rather than a
  raw 500 (matches the route's existing try/except-and-log contract)
- Regression guard for todo 130: the route must not import a nonexistent module-level
  `get_connection` symbol from database_manager.py (it's only a DatabaseManager
  instance method). That bug made every real request 500 on an ImportError raised
  before the route's own try/except could catch it.

Uses a minimal test_app + TestClient, mirroring tests/unit/api/test_vocabulary_api.py.
No real DB required; the drift router uses Depends(get_db_manager), overridden here
with an AsyncMock.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import dependencies
from src.api.routes.drift import router as drift_router

test_app = FastAPI()
test_app.include_router(drift_router, prefix="/api/drift")


def make_row(symbol: str, tf: str, ks_severity, cusum_severity, updated_at: datetime) -> dict:
    """Return a dict that mimics an asyncpg Record (subscriptable by key)."""
    return {
        "symbol": symbol,
        "tf": tf,
        "ks_severity": ks_severity,
        "cusum_severity": cusum_severity,
        "updated_at": updated_at,
    }


NOW = datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC)

DRIFT_ROWS = [
    make_row("SPY", "5m", "moderate", None, NOW),
    make_row("mean_reversion_v1", "_cusum", None, "severe", NOW),
]


@pytest.fixture
def mock_db():
    db = AsyncMock()
    return db


@pytest.fixture
def client(mock_db):
    test_app.dependency_overrides[dependencies.get_db_manager] = lambda: mock_db
    yield TestClient(test_app)
    test_app.dependency_overrides.clear()


class TestGetDriftState:
    def test_returns_200_not_500(self, client, mock_db):
        """Regression guard for todo 130 -- this must not ImportError before reaching
        the route's own try/except."""
        mock_db.fetch = AsyncMock(return_value=DRIFT_ROWS)

        response = client.get("/api/drift")

        assert response.status_code == 200

    def test_splits_ks_and_cusum_entries(self, client, mock_db):
        mock_db.fetch = AsyncMock(return_value=DRIFT_ROWS)

        response = client.get("/api/drift")

        data = response.json()
        assert len(data["ks"]) == 1
        assert data["ks"][0]["symbol"] == "SPY"
        assert data["ks"][0]["ks_severity"] == "moderate"

        assert len(data["cusum"]) == 1
        assert data["cusum"][0]["setup_plugin"] == "mean_reversion_v1"
        assert data["cusum"][0]["severity"] == "severe"

        assert data["last_updated"] == NOW.isoformat()

    def test_db_error_returns_empty_state_not_500(self, client, mock_db):
        """Matches the route's existing contract: a query failure is logged and
        degrades to empty ks/cusum lists, not a 500."""
        mock_db.fetch = AsyncMock(side_effect=RuntimeError("connection refused"))

        response = client.get("/api/drift")

        assert response.status_code == 200
        data = response.json()
        assert data["ks"] == []
        assert data["cusum"] == []
        assert data["last_updated"] is None
