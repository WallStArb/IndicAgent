"""Tests for GET /api/signals/detail/{signal_id}."""

from datetime import UTC
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from src.api.dependencies import get_db_manager
from src.api.main import app

_SIGNAL_ID = "12345678-1234-1234-1234-123456789012"


def _detail_row(**kwargs):
    from datetime import datetime

    now = datetime.now(UTC)
    defaults = {
        "signal_id": _SIGNAL_ID,
        "timestamp": now,
        "symbol": "ESH6",
        "timeframe": "1m",
        "tf": "1m",
        "setup_plugin": "trad_TrendFollowing",
        "direction": "long",
        "entry_price": 5200.0,
        "stop_loss": 5180.0,
        "targets": [5240.0],
        "confidence": 0.65,
        "was_selected": True,
        "cis_score": 0.45,
        "status": "active",
        "pnl_r": None,
        "exit_price": None,
        "signal_computed_at": now,
        "entry_zone_low": None,
        "entry_zone_high": None,
        "hmm_regime_at_fire": None,
        "activated_at": None,
        "exit_reason": None,
        "ttl_bars": None,
        "exit_at": None,
        "feature_ts": None,
        "stop_basis": None,
        "counterfactual_pnl_r": None,
        "entry_type": None,
        "r_multiple": None,
    }
    return {**defaults, **kwargs}


@pytest.mark.unit
class TestSignalsApiDetail:
    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_detail_returns_200(self):
        mock_db = AsyncMock()
        mock_db.fetchrow = AsyncMock(return_value=_detail_row())
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        resp = TestClient(app).get(f"/api/signals/detail/{_SIGNAL_ID}")
        assert resp.status_code == 200

    def test_detail_returns_signal_tier(self):
        mock_db = AsyncMock()
        mock_db.fetchrow = AsyncMock(
            return_value=_detail_row(confidence=0.65, was_selected=True, cis_score=0.45)
        )
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get(f"/api/signals/detail/{_SIGNAL_ID}").json()
        assert data["signal_tier"] == "hero"

    def test_detail_returns_404_when_not_found(self):
        mock_db = AsyncMock()
        mock_db.fetchrow = AsyncMock(return_value=None)
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        resp = TestClient(app).get(f"/api/signals/detail/{_SIGNAL_ID}")
        assert resp.status_code == 404

    def test_detail_includes_lifecycle_fields(self):
        from datetime import datetime

        mock_db = AsyncMock()
        row = _detail_row(
            hmm_regime_at_fire=0,
            activated_at=datetime(2026, 6, 4, 14, 32, 9),
            exit_reason="target_1",
            ttl_bars=10,
            exit_at=datetime(2026, 6, 4, 14, 58, 41),
        )
        mock_db.fetchrow = AsyncMock(return_value=row)
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get(f"/api/signals/detail/{row['signal_id']}").json()
        assert data["hmm_regime_at_fire"] == 0
        assert data["exit_reason"] == "target_1"
        assert data["ttl_bars"] == 10
        assert "activated_at" in data
        assert "exit_at" in data

    def test_detail_does_not_shadow_symbol_route(self):
        """GET /api/signals/ESH6 must NOT be caught by the detail route."""
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[])
        mock_db.fetchrow = AsyncMock(
            return_value={
                "n_total": 0,
                "n_resolved": 0,
                "n_suppressed": 0,
                "win_rate": None,
                "avg_pnl_r": None,
            }
        )
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        resp = TestClient(app).get("/api/signals/ESH6")
        # Must hit the symbol route (200), not detail (would 404 for non-UUID)
        assert resp.status_code == 200
