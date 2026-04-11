"""Unit tests for MLDataQualityAuditorAgent. Uses __new__ pattern."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_agent():
    from services.ml_data_quality_agent import MLDataQualityAuditorAgent
    agent = MLDataQualityAuditorAgent.__new__(MLDataQualityAuditorAgent)
    agent._pool = MagicMock()
    agent._producer = MagicMock()
    agent._producer.publish = AsyncMock()
    agent._settings = MagicMock()
    agent._settings.env_name = "test"
    agent._settings.DATA_QUALITY_MIN_SCORE = 0.85
    agent.logger = MagicMock()
    return agent


def _mock_pool_with_results(cis_null_rate: float, outcome_coverage: float, gap_count: int = 0):
    """Return a mock pool that returns specified check results."""
    pool = MagicMock()
    conn = AsyncMock()

    async def mock_fetchval(sql, *args):
        if "cis" in sql.lower() or "i7" in sql.lower():
            return cis_null_rate
        if "outcome" in sql.lower():
            return outcome_coverage
        if "gap" in sql.lower():
            return gap_count
        return 0.0

    async def mock_fetchrow(sql, *args):
        return {"null_rate": cis_null_rate, "coverage": outcome_coverage}

    conn.fetchval = mock_fetchval
    conn.fetchrow = mock_fetchrow
    conn.fetch = AsyncMock(return_value=[])
    pool.acquire = MagicMock(
        return_value=AsyncMock(__aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock())
    )
    return pool


@pytest.mark.asyncio
async def test_quality_score_is_1_when_all_checks_pass():
    agent = _make_agent()
    agent._pool = _mock_pool_with_results(cis_null_rate=0.005, outcome_coverage=0.97)
    score = await agent._compute_quality_score()
    assert score >= 0.85


@pytest.mark.asyncio
async def test_quality_score_fails_on_high_cis_null_rate():
    agent = _make_agent()
    # CIS null rate at 50% (max) → cis_score=0.0; coverage OK → composite = 0.30*0 + 0.30*1 + 0.20*1 + 0.20*1 = 0.70
    agent._pool = _mock_pool_with_results(cis_null_rate=0.50, outcome_coverage=0.97)
    score = await agent._compute_quality_score()
    assert score < 0.85


@pytest.mark.asyncio
async def test_quality_gate_publishes_alert_when_score_low():
    agent = _make_agent()
    agent._pool = _mock_pool_with_results(cis_null_rate=0.15, outcome_coverage=0.50)
    score = await agent._compute_quality_score()
    await agent._maybe_publish_alert(score)
    agent._producer.publish.assert_awaited_once()
    call_args = agent._producer.publish.call_args
    assert "data_quality" in call_args[0][0]


@pytest.mark.asyncio
async def test_no_alert_when_score_above_threshold():
    agent = _make_agent()
    agent._pool = _mock_pool_with_results(cis_null_rate=0.005, outcome_coverage=0.98)
    score = await agent._compute_quality_score()
    assert score >= 0.85
    await agent._maybe_publish_alert(score)
    agent._producer.publish.assert_not_awaited()
