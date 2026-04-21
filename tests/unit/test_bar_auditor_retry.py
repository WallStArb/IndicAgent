"""Tests for bar_auditor_agent DB-backed retry logic."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.bar_auditor_agent import BarAuditorAgent, MAX_GAP_RETRIES, _RETRY_BACKOFFS_SECS


@pytest.fixture
def agent():
    with patch("services.bar_auditor_agent.asyncpg"), \
         patch("services.bar_auditor_agent.KafkaProducerClient"), \
         patch("services.bar_auditor_agent.KafkaConsumerClient"):
        a = BarAuditorAgent.__new__(BarAuditorAgent)
        a.name = "bar_auditor_agent"
        a.settings = MagicMock(database_url="postgresql://x", kafka_bootstrap_servers="x", env_name="test")
        a.logger = MagicMock()
        a._gap_fill_dlq_depth = MagicMock()
        a._gap_requests_published = MagicMock()
        a._kafka_producer = AsyncMock()
        a._db_pool = None
        a._post_roll_suppression = {}
        return a


def test_should_emit_first_request(agent):
    """First request (gap_requests_sent=0) always emits."""
    row = {"gap_requests_sent": 0, "last_request_sent_at": None, "resolved_at": None}
    assert agent._should_emit_gap_request(row) is True


def test_should_not_emit_within_backoff(agent):
    """Second request suppressed if within 5-min backoff window."""
    row = {
        "gap_requests_sent": 1,
        "last_request_sent_at": datetime.now(UTC) - timedelta(seconds=_RETRY_BACKOFFS_SECS[0] - 200),
        "resolved_at": None,
    }
    assert agent._should_emit_gap_request(row) is False


def test_should_emit_after_backoff_elapsed(agent):
    """Second request emits after 5-min backoff window expires."""
    row = {
        "gap_requests_sent": 1,
        "last_request_sent_at": datetime.now(UTC) - timedelta(seconds=_RETRY_BACKOFFS_SECS[0] + 100),
        "resolved_at": None,
    }
    assert agent._should_emit_gap_request(row) is True


def test_should_not_emit_after_max_retries(agent):
    """No emission after MAX_GAP_RETRIES attempts — DLQ path instead."""
    row = {
        "gap_requests_sent": MAX_GAP_RETRIES,
        "last_request_sent_at": datetime.now(UTC) - timedelta(hours=2),
        "resolved_at": None,
    }
    assert agent._should_emit_gap_request(row) is False


@pytest.mark.asyncio
async def test_dlq_published_at_max_retries(agent):
    """_publish_gap_fill_dlq is called when gap_requests_sent reaches MAX_GAP_RETRIES."""
    agent._publish_gap_fill_dlq = AsyncMock()
    now = datetime.now(UTC)
    symbol, tf = "ES", "1m"
    start_ts = now - timedelta(hours=2)
    end_ts = now - timedelta(hours=1)

    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={
        "gap_requests_sent": MAX_GAP_RETRIES,
        "last_request_sent_at": now - timedelta(hours=1),
        "last_request_id": "abc",
        "resolved_at": None,
    })

    result = await agent._check_gap_retry(conn, symbol, tf, start_ts, end_ts)
    assert result is False
    agent._publish_gap_fill_dlq.assert_awaited_once()


def test_roll_suppressed_within_2h(agent):
    """Gaps on old contract suppressed within 2h of roll detection."""
    agent._post_roll_suppression = {"ESH6": datetime.now(UTC) - timedelta(hours=1)}
    assert agent._is_roll_suppressed("ESH6") is True


def test_roll_suppression_expires_after_2h(agent):
    """Suppression expires after 2h."""
    agent._post_roll_suppression = {"ESH6": datetime.now(UTC) - timedelta(hours=3)}
    assert agent._is_roll_suppressed("ESH6") is False


def test_roll_suppression_cleans_up_stale_entries(agent):
    """_cleanup_roll_suppression removes entries older than 2h."""
    agent._post_roll_suppression = {
        "ESH6": datetime.now(UTC) - timedelta(hours=3),  # stale
        "CLJ6": datetime.now(UTC) - timedelta(hours=1),  # active
    }
    agent._cleanup_roll_suppression()
    assert "ESH6" not in agent._post_roll_suppression
    assert "CLJ6" in agent._post_roll_suppression
