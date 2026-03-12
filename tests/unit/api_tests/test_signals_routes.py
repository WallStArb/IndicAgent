"""
Unit tests for GET /api/signals/{symbol} timeframe filter.

Verifies that ?timeframe= query parameter is correctly injected into the
SQL WHERE clause (not silently ignored).

Covers:
  - timeframe=5m returns only 5m signals (parameter passed to fetch)
  - timeframe=1h returns only 1h signals (parameter passed to fetch)
  - no timeframe parameter passes None to fetch (all timeframes returned)
  - invalid timeframe value returns empty result gracefully (no crash)
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


def _make_mock_db(rows=None):
    """Return a MagicMock db_manager with fetch returning rows."""
    mock_db = MagicMock()
    mock_db.fetch = AsyncMock(return_value=rows or [])
    return mock_db


def _make_client(mock_db):
    """Build a TestClient with the db_manager dependency overridden."""
    test_app.dependency_overrides[dependencies.get_db_manager] = lambda: mock_db
    client = TestClient(test_app)
    return client


class _DictRow(dict):
    """Dict subclass with attribute access for asyncpg row compatibility."""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def get(self, key, default=None):
        return super().get(key, default)


def _make_signal_row(timeframe="5m", **overrides):
    """Minimal signal row dict for fetch() return value."""
    row = {
        "signal_id": uuid.uuid4(),
        "timestamp": datetime(2026, 3, 1, 14, 0, 0),
        "symbol": "ESH6",
        "timeframe": timeframe,
        "setup_plugin": "TrendFollowing",
        "signal_type": "long_entry",
        "direction": "long",
        "entry_price": 5950.25,
        "stop_loss": 5930.00,
        "confidence": 0.82,
        "status": "pending",
        "feature_ts": None,
        "feature_tf": None,
        "signal_computed_at": None,
        "market_price_at_signal": None,
        "ask_at_signal": None,
        "bid_at_signal": None,
        "entry_zone_low": None,
        "entry_zone_high": None,
        "zone_valid_at_signal": None,
    }
    row.update(overrides)
    return _DictRow(row)


# ---------------------------------------------------------------------------
# Timeframe filter tests
# ---------------------------------------------------------------------------


class TestGetSignalsTimeframeFilter:
    """Verify ?timeframe= query parameter is injected into SQL fetch call."""

    def teardown_method(self, method):
        """Clear dependency overrides after each test."""
        test_app.dependency_overrides.clear()

    @pytest.mark.unit
    def test_get_signals_timeframe_filter_5m(self):
        """Query with timeframe=5m passes '5m' as a bound parameter to fetch()."""
        mock_db = _make_mock_db(rows=[_make_signal_row(timeframe="5m")])
        client = _make_client(mock_db)

        response = client.get("/api/signals/ESH6?timeframe=5m")

        assert response.status_code == 200
        call_args = mock_db.fetch.call_args
        positional = list(call_args.args)
        # '5m' must appear in the positional args (SQL $5 parameter)
        assert "5m" in positional, f"Expected '5m' in fetch args, got: {positional}"

    @pytest.mark.unit
    def test_get_signals_timeframe_filter_1h(self):
        """Query with timeframe=1h passes '1h' as a bound parameter to fetch()."""
        mock_db = _make_mock_db(rows=[_make_signal_row(timeframe="1h")])
        client = _make_client(mock_db)

        response = client.get("/api/signals/ESH6?timeframe=1h")

        assert response.status_code == 200
        call_args = mock_db.fetch.call_args
        positional = list(call_args.args)
        assert "1h" in positional, f"Expected '1h' in fetch args, got: {positional}"

    @pytest.mark.unit
    def test_get_signals_no_timeframe_passes_none(self):
        """Query without timeframe param passes None to fetch() — all TFs returned."""
        mock_db = _make_mock_db(rows=[])
        client = _make_client(mock_db)

        response = client.get("/api/signals/ESH6")

        assert response.status_code == 200
        call_args = mock_db.fetch.call_args
        positional = list(call_args.args)
        # None must appear in positional args for the timeframe position
        # The args pattern is: (query, symbol, limit, from_ts, to_ts, timeframe)
        # timeframe is the last positional arg
        assert positional[-1] is None, (
            f"Expected None as last fetch arg (timeframe), got: {positional[-1]}"
        )

    @pytest.mark.unit
    def test_get_signals_invalid_timeframe_no_crash(self):
        """Invalid timeframe value ('xyz') returns 200 with empty list — no crash."""
        # fetch() returns [] (no matching rows) — the route must not crash
        mock_db = _make_mock_db(rows=[])
        client = _make_client(mock_db)

        response = client.get("/api/signals/ESH6?timeframe=xyz")

        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 0
        assert body["signals"] == []

    @pytest.mark.unit
    def test_timeframe_param_in_sql_query_string(self):
        """The SQL query text must contain the $5 timeframe filter pattern."""
        mock_db = _make_mock_db(rows=[])
        client = _make_client(mock_db)

        client.get("/api/signals/ESH6?timeframe=5m&include_features=true")

        call_args = mock_db.fetch.call_args
        sql_query = call_args.args[0]
        assert "$5" in sql_query, "SQL query must reference $5 parameter"
        assert "timeframe" in sql_query.lower(), (
            "SQL query must reference 'timeframe' column"
        )

    @pytest.mark.unit
    def test_timeframe_param_in_no_features_query(self):
        """The no-features SQL query text must also contain the $5 timeframe filter."""
        mock_db = _make_mock_db(rows=[])
        client = _make_client(mock_db)

        client.get("/api/signals/ESH6?timeframe=5m")

        call_args = mock_db.fetch.call_args
        sql_query = call_args.args[0]
        assert "$5" in sql_query, "No-features SQL query must reference $5 parameter"
        assert "timeframe" in sql_query.lower(), (
            "No-features SQL query must reference 'timeframe' column"
        )
