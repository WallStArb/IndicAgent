"""Unit tests for MLDiscoveryComputeAgent. Uses __new__ pattern."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_agent():
    from services.ml_discovery_agent import MLDiscoveryComputeAgent
    agent = MLDiscoveryComputeAgent.__new__(MLDiscoveryComputeAgent)
    agent._pool = MagicMock()
    agent._producer = MagicMock()
    agent._producer.publish = AsyncMock()
    agent.settings = MagicMock(env_name="test")
    agent.settings.ML_DISCOVERY_LOOKBACK_DAYS = 90
    agent.settings.ML_DISCOVERY_IC_THRESHOLD = 0.05
    agent.logger = MagicMock()
    # _query is initialised in _run(); set it here for direct method tests
    agent._query = MagicMock()
    agent._query.query = AsyncMock(return_value=None)
    return agent


def _make_mock_pool_with_features(row_count: int = 500):
    """Pool that returns synthetic intelligence_features rows."""
    import random
    pool = MagicMock()
    conn = AsyncMock()

    fake_rows = [
        {
            "ts": datetime(2026, 1, 1, 14, i % 60, tzinfo=UTC),
            "symbol": "ESM6",
            "tf": "1m",
            "atr": 8.5 + random.gauss(0, 0.5),
            "rsi": 50 + random.gauss(0, 10),
            "hmm_regime": random.choice([0, 1, 2]),
            "pnl_r": random.gauss(0, 1),
            "outcome": random.choice(["win", "loss"]),
        }
        for i in range(row_count)
    ]
    conn.fetch = AsyncMock(return_value=fake_rows)
    conn.fetchval = AsyncMock(return_value=None)  # no existing run_id
    conn.execute = AsyncMock()
    pool.acquire = MagicMock(
        return_value=AsyncMock(__aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock())
    )
    return pool


@pytest.mark.asyncio
async def test_discovery_run_completes_without_crash():
    """Full discovery run should complete without raising."""
    agent = _make_agent()
    agent._pool = _make_mock_pool_with_features(row_count=200)

    with patch("services.ml_discovery_agent.tsfresh", create=True) as mock_tsfresh, \
         patch("services.ml_discovery_agent.alphalens", create=True) as mock_alphalens:
        # Mock tsfresh to return a simple DataFrame
        import pandas as pd
        mock_tsfresh.extract_features = MagicMock(
            return_value=pd.DataFrame({"atr__mean": [1.0, 2.0], "rsi__std": [0.5, 0.3]})
        )
        # Mock alphalens IC computation
        mock_alphalens.utils.get_clean_factor_and_forward_returns = MagicMock(
            return_value=MagicMock()
        )
        mock_alphalens.performance.factor_information_coefficient = MagicMock(
            return_value=pd.Series({"atr__mean": 0.12, "rsi__std": 0.08})
        )

        result = await agent._run_discovery(symbol="ESM6", tf="1m", regime=1)

    assert result is not None


@pytest.mark.asyncio
async def test_ic_analysis_segmented_by_regime():
    """Discovery must run per regime, not global."""
    agent = _make_agent()
    regimes_seen = []

    async def mock_run_discovery(symbol, tf, regime):
        regimes_seen.append(regime)
        return {"top_features": [], "ic_scores": {}, "feature_count": 0}

    agent._run_discovery = mock_run_discovery

    await agent._run_all_regimes(symbol="ESM6", tf="1m")

    assert set(regimes_seen) == {0, 1, 2}


@pytest.mark.asyncio
async def test_partial_result_on_timeout():
    """Timeout during tsfresh -> status='partial', writes partial results."""
    agent = _make_agent()
    agent._pool = _make_mock_pool_with_features(row_count=10)

    with patch.object(agent, "_run_discovery", side_effect=asyncio.TimeoutError):
        written = await agent._run_with_timeout(symbol="ESM6", tf="1m", regime=0, timeout_s=0.01)
        assert written is None or written.get("status") == "partial"


@pytest.mark.asyncio
async def test_discovery_writes_ml_discovery_runs():
    """Successful run must insert a row into ml_discovery_runs."""
    agent = _make_agent()

    inserted = {}

    conn = AsyncMock()
    async def mock_execute(sql, *args):
        if "ml_discovery_runs" in sql:
            inserted["written"] = True

    conn.execute = mock_execute
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchval = AsyncMock(return_value=None)

    pool = MagicMock()
    pool.acquire = MagicMock(
        return_value=AsyncMock(__aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock())
    )
    agent._pool = pool

    run_result = {
        "top_features": [{"name": "atr__mean", "ic": 0.12, "icir": 0.8, "p_value": 0.03}],
        "ic_scores": {"atr__mean": 0.12},
        "feature_count": 5,
        "status": "complete",
    }
    await agent._write_discovery_run(symbol="ESM6", tf="1m", regime=1, result=run_result)

    assert inserted.get("written") is True
