"""
Unit tests for GET /api/signals/{symbol} route.

Uses a test-local FastAPI app (not main.py) to avoid lifespan complications.
All tests mock the db_manager dependency via FastAPI dependency overrides.
"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import dependencies
from src.api.routes.signals import router as signals_router

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
        "tf": "5m",
        "setup_plugin": "TrendFollowing",
        "direction": "long",
        "entry_price": 5950.25,
        "stop_loss": 5930.00,
        "raw_confidence": 0.82,
        "status": "pending",
        "feature_ts": datetime(2026, 2, 24, 10, 0, 0),
        "signal_computed_at": None,
        "entry_zone_low": None,
        "entry_zone_high": None,
    }
    row.update(overrides)
    return row


def _features_row(**overrides):
    """Return a dict-like mock row for include_features=true queries."""
    row = _base_row(**overrides)
    row.update(
        {
            "bar": '{"open": 5950.0, "close": 5951.5}',
            "technical_indicators": '{"rsi_14": 62.5}',
            "regime_features": None,
            "confluence_scores": '{"garch_sigma": 0.5}',
            "pattern_detections": None,
            "smc": None,
            "cross_timeframe_context": None,
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
                bar=None,
                technical_indicators=None,
                regime_features=None,
                confluence_scores=None,
                pattern_detections=None,
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
        """Base symbol 'ES' resolves to the active ES contract before the DB query."""
        from unittest.mock import patch

        from src.core.models import AssetClass, Instrument

        fake_es = Instrument(
            symbol="ESM6",
            base="ES",
            exchange="CME",
            expiry="202606",
            name="E-mini S&P 500",
            point_value=50,
            tick_size=0.25,
            sector="equity_index",
            asset_class=AssetClass.FUTURES,
        )

        mock_db = _make_mock_db()
        mock_db.fetch = AsyncMock(return_value=[])

        client = _make_client(mock_db)
        with patch("src.api.routes.signals._resolve_contract", return_value="ESM6"):
            response = client.get("/api/signals/ES")

        assert response.status_code == 200
        call_args = mock_db.fetch.call_args
        positional = list(call_args.args)
        # positional[0] is the SQL query, positional[1] is the resolved contract symbol
        assert positional[1] == "ESM6"


# ---------------------------------------------------------------------------
# Tests for GET /api/signals/active
# ---------------------------------------------------------------------------


def _active_row(**overrides):
    """Return a complete mock row for get_active_signals queries (3-table schema)."""
    row = {
        "signal_id": str(uuid.uuid4()),
        "symbol": "ESH6",
        "timeframe": "5m",
        "setup_plugin": "TrendFollowing",
        "direction": "long",
        "entry_price": "5950.25",
        "stop_loss": "5930.00",
        "status": "pending",
        "was_selected": True,
        "cis_score": "0.75",
        "targets": [5970.0, 5990.0, 6010.0],
        "stop_basis": "atr",
        "entry_zone_low": "5948.00",
        "entry_zone_high": "5955.00",
        "signal_computed_at": datetime(2026, 2, 24, 10, 0, 0),
        "bar_close_ts": datetime(2026, 2, 24, 10, 0, 0),
        "timestamp": datetime(2026, 2, 24, 10, 0, 0),
        "ttl_bars": 10,
        "hmm_regime_at_fire": 0,
        "setup_win_rate": "0.58",
        "setup_avg_pnl_r": "1.2",
    }
    row.update(overrides)
    return row


class TestGetActiveSignals:
    """Tests for GET /api/signals/active"""

    @pytest.mark.unit
    def test_active_signals_regime_staleness_fields(self):
        """Active signals response includes hmm_regime_at_fire, ttl_bars; dropped staleness/bucket cols."""
        mock_db = _make_mock_db()
        mock_db.fetch = AsyncMock(return_value=[_row(_active_row())])

        client = _make_client(mock_db)
        response = client.get("/api/signals/active")

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 1
        sig = body["signals"][0]

        assert sig["hmm_regime_at_fire"] == 0
        assert sig["ttl_bars"] == 10
        # bucket_scores and staleness_score removed from 3-table schema
        assert "bucket_scores" not in sig
        assert "staleness_score" not in sig
