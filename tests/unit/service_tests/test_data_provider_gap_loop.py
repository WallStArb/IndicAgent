"""Unit tests for DataProviderAgent._gap_requests_loop.

Tests _gap_requests_loop in isolation using __new__ pattern to bypass __init__.
Covers:
- KafkaConsumerClient created for topic_gap_requests
- Valid BarGapRequest triggers fetch_historical_bars with correct args
- Fetched bars re-published to topic_market_bars with source="ibkr_gap_fill"
- Malformed payloads log error and don't crash the loop
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.schemas.market_events import BarGapRequest
from src.core.stream_keys import topic_gap_requests, topic_market_bars


def _make_dpa_stub(env_name="development"):
    """Create DataProviderAgent via __new__ with minimal attrs for gap loop tests."""
    from services.data_provider_agent import DataProviderAgent

    dpa = DataProviderAgent.__new__(DataProviderAgent)
    dpa.running = True
    dpa.env_name = env_name

    settings = MagicMock()
    settings.kafka_bootstrap_servers = "localhost:9092"
    dpa.settings = settings

    dpa.provider = AsyncMock()
    dpa._kafka_producer = AsyncMock()
    dpa.logger = MagicMock()
    dpa.logger.info = MagicMock()
    dpa.logger.error = MagicMock()
    dpa.logger.warning = MagicMock()
    return dpa


def _make_bar(symbol="ES", tf="1m"):
    """Create a minimal OHLCVBar-like mock."""
    bar = MagicMock()
    bar.timestamp = datetime(2026, 3, 23, 10, 0, tzinfo=UTC)
    bar.open = 5000.0
    bar.high = 5010.0
    bar.low = 4990.0
    bar.close = 5005.0
    bar.volume = 1000
    return bar


class AsyncIterableMock:
    """Async-iterable mock for KafkaConsumerClient.messages() — yields then stops.

    Using a real class with __aiter__ on the type (not instance) avoids the
    AsyncMock __aiter__ gotcha (instance-level dunder silently yields 0 items).
    """

    def __init__(self, items):
        self._items = items

    def __aiter__(self):
        return self._aiter()

    async def _aiter(self):
        for item in self._items:
            yield item


class TestGapRequestsLoopConsumer:
    """Test _gap_requests_loop creates consumer for correct topic."""

    @pytest.mark.asyncio
    async def test_gap_requests_loop_creates_consumer_for_gap_topic(self):
        """_gap_requests_loop creates KafkaConsumerClient for topic_gap_requests."""
        dpa = _make_dpa_stub()

        # KafkaConsumerClient mock — returns empty message stream so loop exits
        mock_consumer = AsyncMock()
        mock_consumer.messages = MagicMock(
            return_value=AsyncIterableMock([])
        )

        with patch("services.data_provider_agent.KafkaConsumerClient") as mock_cls:
            mock_cls.return_value = mock_consumer
            await dpa._gap_requests_loop()

        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args
        # First positional arg is the topic
        topic_arg = call_kwargs[0][0]
        assert "gap_requests" in topic_arg
        assert topic_gap_requests("development") == topic_arg
        # Verify group_id is set
        assert call_kwargs[1].get("group_id") == "data_provider_consumer"


class TestGapRequestsLoopFetch:
    """Test _gap_requests_loop fetches and re-publishes bars on valid request."""

    @pytest.mark.asyncio
    async def test_valid_gap_request_calls_fetch_historical_bars(self):
        """On receiving valid BarGapRequest, calls provider.fetch_historical_bars."""
        dpa = _make_dpa_stub()

        gap_req = BarGapRequest(
            symbol="ES",
            tf="1m",
            start_ts=datetime(2026, 3, 23, 0, 0, tzinfo=UTC),
            end_ts=datetime(2026, 3, 24, 0, 0, tzinfo=UTC),
        )
        payload = gap_req.model_dump(mode="json")

        # Provider returns one bar
        mock_bar = _make_bar()
        dpa.provider.fetch_historical_bars = AsyncMock(return_value=[mock_bar])

        mock_consumer = AsyncMock()
        mock_consumer.messages = MagicMock(
            return_value=AsyncIterableMock([("topic", "ES", payload)])
        )

        with patch("services.data_provider_agent.KafkaConsumerClient") as mock_cls:
            mock_cls.return_value = mock_consumer
            await dpa._gap_requests_loop()

        dpa.provider.fetch_historical_bars.assert_called_once_with(
            symbol="ES",
            timeframe="1m",
            start=gap_req.start_ts,
            end=gap_req.end_ts,
        )

    @pytest.mark.asyncio
    async def test_fetched_bars_published_with_ibkr_gap_fill_source(self):
        """Each fetched bar is published to topic_market_bars with source='ibkr_gap_fill'."""
        dpa = _make_dpa_stub()

        gap_req = BarGapRequest(
            symbol="ES",
            tf="1m",
            start_ts=datetime(2026, 3, 23, 0, 0, tzinfo=UTC),
            end_ts=datetime(2026, 3, 24, 0, 0, tzinfo=UTC),
        )
        payload = gap_req.model_dump(mode="json")

        mock_bar = _make_bar()
        dpa.provider.fetch_historical_bars = AsyncMock(return_value=[mock_bar])

        mock_consumer = AsyncMock()
        mock_consumer.messages = MagicMock(
            return_value=AsyncIterableMock([("topic", "ES", payload)])
        )

        with patch("services.data_provider_agent.KafkaConsumerClient") as mock_cls:
            mock_cls.return_value = mock_consumer
            await dpa._gap_requests_loop()

        dpa._kafka_producer.publish.assert_called_once()
        call_args = dpa._kafka_producer.publish.call_args
        topic_published = call_args[0][0]
        bar_payload = call_args[0][1]

        assert topic_published == topic_market_bars("development")
        assert bar_payload["source"] == "ibkr_gap_fill"
        assert bar_payload["symbol"] == "ES"
        assert bar_payload["tf"] == "1m"


class TestGapRequestsLoopErrorHandling:
    """Test _gap_requests_loop handles errors without crashing."""

    @pytest.mark.asyncio
    async def test_malformed_payload_logs_error_and_continues(self):
        """Malformed payload logs error and does not crash the loop."""
        dpa = _make_dpa_stub()

        # Invalid payload — missing required fields
        bad_payload = {"symbol": "ES"}  # missing tf, start_ts, end_ts

        mock_consumer = AsyncMock()
        mock_consumer.messages = MagicMock(
            return_value=AsyncIterableMock([("topic", "ES", bad_payload)])
        )

        # DPA uses module-level logger, not self.logger — patch at module level
        _logger_path = "services.data_provider_agent.logger"
        with patch("services.data_provider_agent.KafkaConsumerClient") as mock_cls:
            with patch(_logger_path) as mock_logger:
                mock_cls.return_value = mock_consumer
                # Should complete without raising
                await dpa._gap_requests_loop()

        # Error should have been logged via module-level logger
        mock_logger.error.assert_called()
        # Provider fetch should NOT have been called for invalid payload
        dpa.provider.fetch_historical_bars.assert_not_called()
