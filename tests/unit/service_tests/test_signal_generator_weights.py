"""Unit tests for CIS weight refresh loop in signal_generator_service.

Tests for:
- _load_cis_weights_from_db() updates CISScorer with learned weights
- _load_cis_weights_from_db() keeps bootstrap when no rows with sample_size >= 100
- _load_cis_weights_from_db() keeps current weights on DB exception
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.intelligence.trading.cis_scorer import BOOTSTRAP_WEIGHTS, CISScorer

# ---------------------------------------------------------------------------
# Factory — bypass __init__ using __new__ pattern (per CLAUDE.md)
# ---------------------------------------------------------------------------


def _make_svc():
    """Build a SignalGeneratorService without calling __init__."""
    from services.signal_generator_service import SignalGeneratorService

    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    svc.logger = MagicMock()
    # Minimal instance attributes required by _load_cis_weights_from_db
    svc._cis_scorer = CISScorer()
    svc._cis_weights_cache = {}
    return svc


# ---------------------------------------------------------------------------
# _load_cis_weights_from_db() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_cis_weights_updates_scorer():
    """_load_cis_weights_from_db() calls update_weights on _cis_scorer when DB has
    rows with sample_size >= 100 for ('global', 'global') key."""
    svc = _make_svc()

    mock_db = MagicMock()
    mock_db.execute_query = AsyncMock(
        return_value=[
            {
                "asset_cluster": "global",
                "timeframe": "global",
                "version": 7,
                "sample_size": 150,
                "trend_w": 0.25,
                "momentum_w": 0.20,
                "structure_w": 0.18,
                "pattern_w": 0.07,
                "institutional_w": 0.20,
                "regime_w": 0.10,
            }
        ]
    )
    svc.db_manager = mock_db

    initial_version = svc._cis_scorer._weights_version
    await svc._load_cis_weights_from_db()

    # Scorer version should have been updated to 7
    assert svc._cis_scorer._weights_version == 7
    assert svc._cis_scorer._weights_version != initial_version


@pytest.mark.asyncio
async def test_load_cis_weights_no_learned_keeps_bootstrap():
    """_load_cis_weights_from_db() keeps BOOTSTRAP_WEIGHTS when DB returns no rows
    with sample_size >= 100."""
    svc = _make_svc()

    mock_db = MagicMock()
    mock_db.execute_query = AsyncMock(return_value=[])
    svc.db_manager = mock_db

    await svc._load_cis_weights_from_db()

    # Scorer should retain bootstrap weights unchanged
    assert svc._cis_scorer._weights == BOOTSTRAP_WEIGHTS
    assert svc._cis_scorer._weights_version == 0  # bootstrap version


@pytest.mark.asyncio
async def test_load_cis_weights_db_error_keeps_current():
    """_load_cis_weights_from_db() keeps current weights and logs a warning when
    the DB query raises an exception."""
    svc = _make_svc()

    mock_db = MagicMock()
    mock_db.execute_query = AsyncMock(side_effect=Exception("DB connection refused"))
    svc.db_manager = mock_db

    original_weights = dict(svc._cis_scorer._weights)
    original_version = svc._cis_scorer._weights_version

    await svc._load_cis_weights_from_db()

    # Weights should be unchanged
    assert svc._cis_scorer._weights == original_weights
    assert svc._cis_scorer._weights_version == original_version
    # Warning should have been logged
    svc.logger.warning.assert_called_once()
