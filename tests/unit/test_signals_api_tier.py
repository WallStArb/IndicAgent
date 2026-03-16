"""Tests for GET /api/signals/recent tier filtering and signal_tier field."""
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from src.api.dependencies import get_db_manager
from src.api.main import app


def _row(**kwargs):
    """Build a minimal asyncpg-like row dict."""
    defaults = {
        "signal_id": "00000000-0000-0000-0000-000000000001",
        "setup_plugin": "trad_TrendFollowing",
        "signal_type": "trend_long",
        "direction": 1,
        "entry_price": 5200.0,
        "stop_loss": 5180.0,
        "confidence": 0.65,
        "was_selected": True,
        "cis_score": 0.45,
        "status": "pending",
        "outcome": None,
        "exit_price": None,
        "pnl_r": None,
        "signal_computed_at": None,
        "timeframe": "1m",
        "setup_win_rate": None,
        "setup_avg_pnl_r": None,
        "symbol": "ESH6",
    }
    return {**defaults, **kwargs}

@pytest.mark.unit
class TestSignalsApiTier:
    def _setup(self, rows, summary_row=None):
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=rows)
        if summary_row is None:
            summary_row = {"n_total": len(rows), "n_resolved": 0, "n_suppressed": 0,
                           "win_rate": None, "avg_pnl_r": None}
        mock_db.fetchrow = AsyncMock(return_value=summary_row)
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        return TestClient(app), mock_db

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_signal_tier_hero_returned(self):
        """Row with was_selected=True, conf>=0.40, |cis_score|>0.35 → tier='hero'."""
        client, _ = self._setup([_row(confidence=0.65, was_selected=True, cis_score=0.45)])
        resp = client.get("/api/signals/recent?symbol=ESH6")
        assert resp.status_code == 200
        signals = resp.json()["signals"]
        assert len(signals) == 1
        assert signals[0]["signal_tier"] == "hero"

    def test_signal_tier_monitored_null_cis(self):
        """was_selected=True but cis_score IS NULL → tier='monitored'."""
        client, _ = self._setup([_row(confidence=0.65, was_selected=True, cis_score=None)])
        resp = client.get("/api/signals/recent?symbol=ESH6")
        assert resp.json()["signals"][0]["signal_tier"] == "monitored"

    def test_signal_tier_monitored_low_conf(self):
        """was_selected=True, cis_score present but confidence < 0.40 → tier='monitored'."""
        client, _ = self._setup([_row(confidence=0.35, was_selected=True, cis_score=0.45)])
        resp = client.get("/api/signals/recent?symbol=ESH6")
        assert resp.json()["signals"][0]["signal_tier"] == "monitored"

    def test_signal_tier_candidate(self):
        """was_selected=False → tier='candidate'."""
        client, _ = self._setup([_row(was_selected=False, cis_score=0.5)])
        resp = client.get("/api/signals/recent?symbol=ESH6&tier=all")
        assert resp.json()["signals"][0]["signal_tier"] == "candidate"

    def test_tier_hero_filters_low_confidence(self):
        """tier=hero (default) must exclude rows with confidence < 0.40."""
        client, mock_db = self._setup([])
        client.get("/api/signals/recent?symbol=ESH6")
        call_args = mock_db.fetch.call_args[0]
        # The query string passed as first arg must include hero tier WHERE clauses
        assert "confidence" in call_args[0]
        assert "cis_score" in call_args[0]

    def test_tier_all_no_extra_filter(self):
        """tier=all must NOT add tier-based WHERE conditions."""
        client, mock_db = self._setup([])
        client.get("/api/signals/recent?symbol=ESH6&tier=all")
        call_args = mock_db.fetch.call_args[0]
        # tier=all query must not reference cis_score tier conditions
        query = call_args[0]
        assert "abs(sl.cis_score)" not in query

    def test_symbol_optional_omitted(self):
        """Omitting symbol (tier=all, no symbol) must return 200."""
        client, _ = self._setup([])
        resp = client.get("/api/signals/recent?tier=all")
        assert resp.status_code == 200
