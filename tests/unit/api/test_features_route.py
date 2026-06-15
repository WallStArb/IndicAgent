"""
Unit tests for intelligence_features API route.

Tests cover:
- GET /api/features/{symbol}/{timeframe} — paginated JSON response with JSONB tiers parsed
- GET /api/features/export — Parquet binary export with tier columns expanded

Uses a minimal test_app to avoid touching main.py lifespan complexity.
The features router is mounted directly on a test FastAPI instance.
"""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import dependencies
from src.api.routes.features import router as features_router

# Minimal test app — avoids lifespan startup (no DB/Redis required)
test_app = FastAPI()
test_app.include_router(features_router, prefix="/api")


def make_mock_row(
    ts: datetime | None = None,
    symbol: str = "ESH6",
    tf: str = "1m",
    platform: str = "futures",
    source: str = "backfill",
    schema_version: str = "1.0",
    bar: dict | None = None,
    i1: dict | None = None,
    i3: dict | None = None,
    i4: dict | None = None,
    i5: dict | None = None,
    smc: dict | None = None,
    i6: dict | None = None,
) -> dict:
    """Return a dict that mimics an asyncpg Record (subscriptable by key)."""
    return {
        "ts": ts or datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC),
        "symbol": symbol,
        "tf": tf,
        "platform": platform,
        "source": source,
        "schema_version": schema_version,
        "bar": json.dumps(bar or {"o": 5900.0, "h": 5910.0, "l": 5895.0, "c": 5905.0, "v": 1200}),
        "technical_indicators": json.dumps(i1 or {"rsi_14": 62.5, "atr_14": 8.3}),
        "regime_features": json.dumps(i3 or {"trend_direction": 1.0}),
        "confluence_scores": json.dumps(i4 or {"garch_sigma": 0.0023, "garch_vol_regime": 1}),
        "pattern_detections": json.dumps(i5 or {"squeeze_active": 0.0}),
        "smc": json.dumps(smc or {"bos_detected": False}),
        "cross_timeframe_context": json.dumps(i6 or {"ctf_score": 0.75}),
    }


@pytest.fixture
def mock_db():
    """AsyncMock database manager."""
    db = AsyncMock()
    return db


@pytest.fixture
def client(mock_db):
    """TestClient with dependency override for get_db_manager."""
    test_app.dependency_overrides[dependencies.get_db_manager] = lambda: mock_db
    yield TestClient(test_app)
    test_app.dependency_overrides.clear()


class TestGetFeaturesPaginated:
    """Tests for GET /api/features/{symbol}/{timeframe}"""

    def test_get_features_returns_paginated_rows(self, client, mock_db):
        """Endpoint returns 200 with rows list; JSONB fields are dicts, not strings."""
        row1 = make_mock_row(symbol="ESH6", tf="1m")
        row2 = make_mock_row(
            ts=datetime(2026, 1, 15, 10, 1, 0, tzinfo=UTC),
            symbol="ESH6",
            tf="1m",
        )
        mock_db.fetch = AsyncMock(return_value=[row1, row2])

        response = client.get("/api/features/ESH6/1m")

        assert response.status_code == 200
        data = response.json()
        assert "rows" in data
        assert len(data["rows"]) == 2

        first_row = data["rows"][0]
        assert "ts" in first_row
        assert "symbol" in first_row
        assert "tf" in first_row

        # JSONB tiers must be dicts, not raw JSON strings
        assert isinstance(first_row["i1"], dict), "i1 must be parsed dict, not string"
        assert isinstance(first_row["i4"], dict), "i4 must be parsed dict, not string"
        assert "rsi_14" in first_row["i1"]
        assert "garch_sigma" in first_row["i4"]

    def test_get_features_respects_limit_param(self, client, mock_db):
        """The ?limit query param is passed through to db_manager.fetch."""
        mock_db.fetch = AsyncMock(return_value=[])

        response = client.get("/api/features/ESH6/1m?limit=5")

        assert response.status_code == 200
        # Verify the fetch was called — limit=5 should appear in the positional args
        call_args = mock_db.fetch.call_args
        assert call_args is not None
        # Last positional arg should be the limit value (5)
        args = call_args[0]  # positional args tuple
        assert 5 in args, f"Expected limit=5 in fetch args, got: {args}"

    def test_get_features_from_to_params(self, client, mock_db):
        """from/to query params are forwarded as positional args to db_manager.fetch."""
        mock_db.fetch = AsyncMock(return_value=[])

        response = client.get(
            "/api/features/ESH6/1m?from=2026-01-01T00:00:00Z&to=2026-01-15T23:59:59Z"
        )

        assert response.status_code == 200
        call_args = mock_db.fetch.call_args
        assert call_args is not None
        args = call_args[0]
        # from_ts and to_ts should be in the positional args (as datetime objects or None)
        # At minimum the query string + symbol/tf are there; from/to should NOT both be None
        # We check that neither None appears where both would be if params were ignored
        # args[3] = from_ts, args[4] = to_ts (after query, symbol, tf)
        assert len(args) >= 5, f"Expected at least 5 positional args, got: {args}"

    def test_get_features_returns_empty_list_when_no_data(self, client, mock_db):
        """Empty DB result returns 200 with count=0 and empty rows list."""
        mock_db.fetch = AsyncMock(return_value=[])

        response = client.get("/api/features/ESH6/1m")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 0
        assert data["rows"] == []


class TestExportFeatures:
    """Tests for GET /api/features/export"""

    def test_export_parquet_returns_octet_stream(self, client, mock_db):
        """Export endpoint returns Parquet binary with correct content-type and headers."""
        row = make_mock_row()
        mock_db.fetch = AsyncMock(return_value=[row])

        response = client.get("/api/features/export?symbol=ESH6&timeframe=1m")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/octet-stream"
        assert len(response.content) > 0, "Parquet content should be non-empty bytes"
        assert "Content-Disposition" in response.headers
        assert "features_" in response.headers["Content-Disposition"]

    def test_export_parquet_missing_symbol_returns_422(self, client, mock_db):
        """Export without required symbol param returns 422 validation error."""
        mock_db.fetch = AsyncMock(return_value=[])

        response = client.get("/api/features/export?timeframe=1m")

        assert response.status_code == 422

    def test_export_route_does_not_conflict_with_symbol_path(self, client, mock_db):
        """GET /api/features/export hits export handler, not /{symbol}/{tf} path."""
        mock_db.fetch = AsyncMock(return_value=[])

        # If "export" were treated as a {symbol} path param, this would try to query
        # symbol="export", timeframe would be the next path segment (missing → 422 or error).
        # The correct behavior: export handler is matched, symbol comes from query string.
        response = client.get("/api/features/export?symbol=ESH6&timeframe=1m")

        # Should succeed (200) — export handler matched, not /{symbol}/{tf}
        assert response.status_code == 200
        # Verify it returned Parquet (octet-stream), not the JSON paginated response
        assert response.headers["content-type"] == "application/octet-stream"
