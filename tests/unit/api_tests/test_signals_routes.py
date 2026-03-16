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
from datetime import UTC, datetime
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
        assert (
            positional[-1] is None
        ), f"Expected None as last fetch arg (timeframe), got: {positional[-1]}"

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
        assert "timeframe" in sql_query.lower(), "SQL query must reference 'timeframe' column"

    @pytest.mark.unit
    def test_timeframe_param_in_no_features_query(self):
        """The no-features SQL query text must also contain the $5 timeframe filter."""
        mock_db = _make_mock_db(rows=[])
        client = _make_client(mock_db)

        client.get("/api/signals/ESH6?timeframe=5m")

        call_args = mock_db.fetch.call_args
        sql_query = call_args.args[0]
        assert "$5" in sql_query, "No-features SQL query must reference $5 parameter"
        assert (
            "timeframe" in sql_query.lower()
        ), "No-features SQL query must reference 'timeframe' column"


# ---------------------------------------------------------------------------
# /api/signals/recent helpers
# ---------------------------------------------------------------------------


def _make_recent_signal_row(**overrides):
    """Minimal signal row for /api/signals/recent fetch() return value."""
    import uuid

    base = _DictRow(
        {
            "signal_id": uuid.uuid4(),
            "setup_plugin": "trad_TrendFollowing",
            "signal_type": "trend_long",
            "direction": 1,
            "entry_price": 4521.50,
            "stop_loss": 4515.25,
            "confidence": 0.87,
            "was_selected": True,
            "cis_score": 0.45,
            "status": "expired",
            "outcome": "ttl_expired_ahead",
            "exit_price": None,
            "pnl_r": None,
            "signal_computed_at": datetime(2026, 3, 11, 14, 23, 45, tzinfo=UTC),
            "timeframe": "1m",
            "symbol": "ESH6",
            "setup_win_rate": 0.58,
            "setup_avg_pnl_r": 0.38,
        }
    )
    base.update(overrides)
    return base


def _make_summary_row(**overrides):
    """Minimal summary row for /api/signals/recent fetchrow() return value."""
    base = _DictRow(
        {
            "n_total": 10,
            "n_resolved": 7,
            "n_suppressed": 2,
            "win_rate": 0.571,
            "avg_pnl_r": 0.31,
        }
    )
    base.update(overrides)
    return base


def _make_recent_mock_db(signal_rows=None, summary_row=None):
    """Return a mock db with fetch + fetchrow set up for /api/signals/recent."""
    mock_db = MagicMock()
    mock_db.fetch = AsyncMock(return_value=signal_rows if signal_rows is not None else [])
    mock_db.fetchrow = AsyncMock(
        return_value=summary_row if summary_row is not None else _make_summary_row()
    )
    return mock_db


# ---------------------------------------------------------------------------
# TestGetRecentSignals
# ---------------------------------------------------------------------------


class TestGetRecentSignals:
    """Tests for GET /api/signals/recent."""

    def teardown_method(self, method):
        test_app.dependency_overrides.clear()

    @pytest.mark.unit
    def test_empty_result_returns_200_with_structure(self):
        """Returns 200 with {signals:[], summary:{...}} when DB returns empty."""
        mock_db = _make_recent_mock_db(
            signal_rows=[],
            summary_row=_make_summary_row(
                n_total=0, n_resolved=0, n_suppressed=0, win_rate=None, avg_pnl_r=None
            ),
        )
        test_app.dependency_overrides[dependencies.get_db_manager] = lambda: mock_db
        client = TestClient(test_app)

        response = client.get("/api/signals/recent?symbol=ESH6")

        assert response.status_code == 200
        body = response.json()
        assert "signals" in body
        assert "summary" in body
        assert body["signals"] == []
        assert "n_total" in body["summary"]

    @pytest.mark.unit
    def test_passes_correct_args_to_fetch(self):
        """Passes symbol, timeframe and limit to db.fetch."""
        mock_db = _make_recent_mock_db()
        test_app.dependency_overrides[dependencies.get_db_manager] = lambda: mock_db
        client = TestClient(test_app)

        client.get("/api/signals/recent?symbol=ESH6&timeframe=1m&limit=5")

        call_args = mock_db.fetch.call_args
        positional = list(call_args.args)
        assert "ESH6" in positional
        assert "1m" in positional
        assert 5 in positional

    @pytest.mark.unit
    def test_limit_501_returns_422(self):
        """limit > 500 returns 422 validation error."""
        mock_db = _make_recent_mock_db()
        test_app.dependency_overrides[dependencies.get_db_manager] = lambda: mock_db
        client = TestClient(test_app)

        response = client.get("/api/signals/recent?symbol=ESH6&limit=501")

        assert response.status_code == 422

    @pytest.mark.unit
    def test_signal_row_includes_setup_performance(self):
        """Each signal row includes setup_win_rate and setup_avg_pnl_r."""
        row = _make_recent_signal_row(setup_win_rate=0.58, setup_avg_pnl_r=0.38)
        mock_db = _make_recent_mock_db(signal_rows=[row])
        test_app.dependency_overrides[dependencies.get_db_manager] = lambda: mock_db
        client = TestClient(test_app)

        response = client.get("/api/signals/recent?symbol=ESH6")

        assert response.status_code == 200
        body = response.json()
        assert len(body["signals"]) == 1
        sig = body["signals"][0]
        assert "setup_win_rate" in sig
        assert "setup_avg_pnl_r" in sig
        assert sig["setup_win_rate"] == pytest.approx(0.58)
        assert sig["setup_avg_pnl_r"] == pytest.approx(0.38)

    @pytest.mark.unit
    def test_signal_row_null_setup_performance_when_no_sample(self):
        """setup_win_rate and setup_avg_pnl_r are null when no JOIN match."""
        row = _make_recent_signal_row(setup_win_rate=None, setup_avg_pnl_r=None)
        mock_db = _make_recent_mock_db(signal_rows=[row])
        test_app.dependency_overrides[dependencies.get_db_manager] = lambda: mock_db
        client = TestClient(test_app)

        response = client.get("/api/signals/recent?symbol=ESH6")

        assert response.status_code == 200
        sig = response.json()["signals"][0]
        assert sig["setup_win_rate"] is None
        assert sig["setup_avg_pnl_r"] is None

    @pytest.mark.unit
    def test_summary_block_fields(self):
        """Summary block has n_total, n_resolved, n_suppressed, win_rate, avg_pnl_r."""
        mock_db = _make_recent_mock_db(
            summary_row=_make_summary_row(
                n_total=10, n_resolved=7, n_suppressed=2, win_rate=0.571, avg_pnl_r=0.31
            ),
        )
        test_app.dependency_overrides[dependencies.get_db_manager] = lambda: mock_db
        client = TestClient(test_app)

        response = client.get("/api/signals/recent?symbol=ESH6")

        assert response.status_code == 200
        summary = response.json()["summary"]
        assert summary["n_total"] == 10
        assert summary["n_resolved"] == 7
        assert summary["n_suppressed"] == 2
        assert summary["win_rate"] == pytest.approx(0.571)
        assert summary["avg_pnl_r"] == pytest.approx(0.31)

    @pytest.mark.unit
    def test_summary_win_rate_and_avg_pnl_r_null_when_no_data(self):
        """Summary win_rate and avg_pnl_r are None when no resolved signals."""
        mock_db = _make_recent_mock_db(
            summary_row=_make_summary_row(
                n_total=3, n_resolved=0, n_suppressed=0, win_rate=None, avg_pnl_r=None
            ),
        )
        test_app.dependency_overrides[dependencies.get_db_manager] = lambda: mock_db
        client = TestClient(test_app)

        response = client.get("/api/signals/recent?symbol=ESH6")

        assert response.status_code == 200
        summary = response.json()["summary"]
        assert summary["win_rate"] is None
        assert summary["avg_pnl_r"] is None

    @pytest.mark.unit
    def test_db_error_returns_500(self):
        """DB error during fetch returns 500."""
        mock_db = MagicMock()
        mock_db.fetch = AsyncMock(side_effect=Exception("connection lost"))
        mock_db.fetchrow = AsyncMock(return_value=_make_summary_row())
        test_app.dependency_overrides[dependencies.get_db_manager] = lambda: mock_db
        client = TestClient(test_app)

        response = client.get("/api/signals/recent?symbol=ESH6")

        assert response.status_code == 500
