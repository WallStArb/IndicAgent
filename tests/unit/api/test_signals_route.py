"""
Unit tests for GET /api/signals/{symbol} route.

Uses a test-local FastAPI app (not main.py) to avoid lifespan complications.
All tests mock the db_manager dependency via FastAPI dependency overrides.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes.signals import router as signals_router
from src.api import dependencies

# ---------------------------------------------------------------------------
# Test app setup (avoids main.py lifespan)
# ---------------------------------------------------------------------------

test_app = FastAPI()
test_app.include_router(signals_router, prefix="/api")


def _make_client(mock_db):
    """Build a TestClient with the db_manager dependency overridden."""
    test_app.dependency_overrides[dependencies.get_db_manager] = lambda: mock_db
    client = TestClient(test_app)
    return client


def _make_mock_db():
    """Return an AsyncMock db_manager whose fetch() returns []."""
    mock_db = MagicMock()
    mock_db.fetch = AsyncMock(return_value=[])
    return mock_db


# ---------------------------------------------------------------------------
# Row factory helpers
# ---------------------------------------------------------------------------

def _base_row(**overrides):
    """Return a dict-like mock row for base (no feature JOIN) queries."""
    row = {
        "signal_id": str(uuid.uuid4()),
        "timestamp": datetime(2026, 2, 24, 10, 0, 0),
        "symbol": "ESH6",
        "timeframe": "5m",
        "setup_plugin": "TrendFollowing",
        "signal_type": "long_entry",
        "direction": "long",
        "entry_price": 5950.25,
        "stop_loss": 5930.00,
        "confidence": 0.82,
        "status": "pending",
        "feature_ts": datetime(2026, 2, 24, 10, 0, 0),
        "feature_tf": "5m",
    }
    row.update(overrides)
    return row


def _features_row(**overrides):
    """Return a dict-like mock row for include_features=true queries."""
    row = _base_row(**overrides)
    row.update(
        {
            "bar": '{"open": 5950.0, "close": 5951.5}',
            "i1": '{"rsi_14": 62.5}',
            "i3": None,
            "i4": '{"garch_sigma": 0.5}',
            "i5": None,
            "smc": None,
            "i6": None,
        }
    )
    return row


class _DictRow(dict):
    """Dict subclass that supports attribute-style access for asyncpg row compat."""
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc


def _row(data: dict) -> _DictRow:
    return _DictRow(data)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


class TestGetSignals:
    """Tests for GET /api/signals/{symbol}"""

    @pytest.mark.unit
    def test_get_signals_returns_list(self):
        """GET /api/signals/ESH6 returns 200 with a list of 2 signals."""
        mock_db = _make_mock_db()
        rows = [_row(_base_row()), _row(_base_row(symbol="ESH6", confidence=0.75))]
        mock_db.fetch = AsyncMock(return_value=rows)

        client = _make_client(mock_db)
        response = client.get("/api/signals/ESH6")

        assert response.status_code == 200
        body = response.json()
        assert "signals" in body
        assert len(body["signals"]) == 2

        sig = body["signals"][0]
        assert "signal_id" in sig
        assert "symbol" in sig
        assert "timeframe" in sig
        assert "setup_plugin" in sig
        assert "direction" in sig
        assert "confidence" in sig
        assert "status" in sig

    @pytest.mark.unit
    def test_get_signals_no_features_by_default(self):
        """Without include_features, signal objects do NOT include a 'features' key."""
        mock_db = _make_mock_db()
        mock_db.fetch = AsyncMock(return_value=[_row(_base_row())])

        client = _make_client(mock_db)
        response = client.get("/api/signals/ESH6")

        assert response.status_code == 200
        sig = response.json()["signals"][0]
        assert "features" not in sig

    @pytest.mark.unit
    def test_get_signals_with_include_features_true(self):
        """include_features=true returns signals with parsed feature dicts."""
        mock_db = _make_mock_db()
        mock_db.fetch = AsyncMock(return_value=[_row(_features_row())])

        client = _make_client(mock_db)
        response = client.get("/api/signals/ESH6?include_features=true")

        assert response.status_code == 200
        sig = response.json()["signals"][0]
        assert "features" in sig
        features = sig["features"]
        assert features is not None
        assert isinstance(features["i4"], dict)
        assert features["i4"]["garch_sigma"] == 0.5

    @pytest.mark.unit
    def test_get_signals_null_feature_ts_returns_null_features(self):
        """Signal with NULL feature_ts returns features: null — does not crash."""
        mock_db = _make_mock_db()
        null_row = _row(
            _features_row(
                feature_ts=None,
                feature_tf=None,
                bar=None,
                i1=None,
                i3=None,
                i4=None,
                i5=None,
                smc=None,
                i6=None,
            )
        )
        mock_db.fetch = AsyncMock(return_value=[null_row])

        client = _make_client(mock_db)
        response = client.get("/api/signals/ESH6?include_features=true")

        assert response.status_code == 200
        sig = response.json()["signals"][0]
        assert "features" in sig
        assert sig["features"] is None

    @pytest.mark.unit
    def test_get_signals_limit_param(self):
        """limit query param is forwarded to db_manager.fetch."""
        mock_db = _make_mock_db()
        mock_db.fetch = AsyncMock(return_value=[])

        client = _make_client(mock_db)
        response = client.get("/api/signals/ESH6?limit=50")

        assert response.status_code == 200
        # Check that 50 was passed as one of the positional args to fetch
        call_args = mock_db.fetch.call_args
        assert 50 in call_args.args or 50 in list(call_args.args)

    @pytest.mark.unit
    def test_get_signals_empty_returns_200(self):
        """Empty result returns 200 with count=0 and empty signals list."""
        mock_db = _make_mock_db()
        mock_db.fetch = AsyncMock(return_value=[])

        client = _make_client(mock_db)
        response = client.get("/api/signals/ESH6")

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 0
        assert body["signals"] == []

    @pytest.mark.unit
    def test_get_signals_base_symbol_resolved(self):
        """Base symbol 'ES' resolves to 'ESH6' before the DB query."""
        mock_db = _make_mock_db()
        mock_db.fetch = AsyncMock(return_value=[])

        client = _make_client(mock_db)
        response = client.get("/api/signals/ES")

        assert response.status_code == 200
        call_args = mock_db.fetch.call_args
        # First positional arg after the query string should be the resolved contract
        positional = list(call_args.args)
        # positional[0] is the SQL query, positional[1] is the symbol
        assert positional[1] == "ESH6"
