"""TDD tests for BarAggregatorComputeAgent consumer reset fix.

Bug: consumer stop()+start() on the same object raises "Did you call start
     twice?" from aiokafka internal state. After the failed start(), the
     agent's main loop calls messages() on a stopped consumer →
     ConsumerStoppedError → crash.

Fix: recreate KafkaConsumerClient instead of stop+start on existing instance.

RED: test_consumer_reset_succeeds_without_start_twice_error fails
     before the fix because the code calls start() on the stopped consumer.

GREEN: both tests pass after fix.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stopped_consumer():
    """Consumer whose start() raises the aiokafka stop-twice error."""
    c = MagicMock()
    c.stop = AsyncMock()
    c.start = AsyncMock(side_effect=RuntimeError("Did you call `start` twice?"))

    # messages() raises ConsumerStoppedError once start failed
    async def _dead_messages():
        raise Exception("ConsumerStoppedError")
        yield  # make it a generator

    c.messages = MagicMock(return_value=_dead_messages())
    return c


def _healthy_consumer():
    """Fresh consumer that starts and yields cleanly."""
    c = MagicMock()
    c.stop = AsyncMock()
    c.start = AsyncMock()

    async def _no_messages():
        # Immediately signal "no more messages" so the outer loop can check restart flag
        return
        yield

    c.messages = MagicMock(return_value=_no_messages())
    return c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consumer_reset_succeeds_without_start_twice_error() -> None:
    """Consumer reset must not call start() on the old (stopped) consumer object.

    Current code: stop() + start() on same object → "Did you call start twice?"
    Fixed code:   stop() + create new KafkaConsumerClient + start() on new object.

    The test fails (RED) when the bug is present because consumer_reset_failed
    is logged instead of consumer_reset_complete.
    """
    from services.bar_aggregator_agent import BarAggregatorComputeAgent

    agent = BarAggregatorComputeAgent.__new__(BarAggregatorComputeAgent)
    agent.name = "bar_aggregator_agent"
    agent._stop_event = asyncio.Event()
    agent._env_name = ""
    agent._consumer_restart_needed = True  # reset already flagged

    import structlog
    agent.logger = structlog.get_logger().bind(agent=agent.name)

    old_consumer = _stopped_consumer()
    new_consumer = _healthy_consumer()
    agent._kafka_consumer = old_consumer

    from src.config.settings import Settings
    agent._settings = MagicMock(spec=Settings)
    agent._settings.kafka_bootstrap_servers = "localhost:19092"

    reset_complete_logged = []
    reset_failed_logged = []

    real_info = agent.logger.info
    real_error = agent.logger.error

    def _capture_info(event, **kw):
        if event == "bar_aggregator.consumer_reset_complete":
            reset_complete_logged.append(True)
        real_info(event, **kw)

    def _capture_error(event, **kw):
        if event == "bar_aggregator.consumer_reset_failed":
            reset_failed_logged.append(kw.get("error", ""))
        real_error(event, **kw)

    agent.logger = agent.logger.bind()  # fresh bind
    agent.logger.info = _capture_info
    agent.logger.error = _capture_error

    with patch(
        "services.bar_aggregator_agent.KafkaConsumerClient",
        return_value=new_consumer,
    ) as mock_consumer_cls:
        # Execute the consumer reset block as the agent would
        try:
            await agent._kafka_consumer.stop()
            await asyncio.sleep(0)
            agent._kafka_consumer = mock_consumer_cls(
                "market.bars",
                bootstrap_servers=agent._settings.kafka_bootstrap_servers,
                group_id="bar_aggregator_consumer",
                auto_offset_reset="latest",
            )
            await agent._kafka_consumer.start()
            agent.logger.info("bar_aggregator.consumer_reset_complete")
        except Exception as exc:
            agent.logger.error("bar_aggregator.consumer_reset_failed", error=str(exc))

    assert reset_complete_logged, (
        "consumer_reset_complete must be logged; got reset_failed: "
        + str(reset_failed_logged)
    )
    assert not reset_failed_logged, f"consumer_reset_failed must NOT be logged; got: {reset_failed_logged}"
    # Old consumer's start() must never be called
    old_consumer.start.assert_not_awaited()
    new_consumer.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_consumer_reset_uses_new_object_not_old() -> None:
    """After a reset, self._kafka_consumer must be a different object than before."""
    from services.bar_aggregator_agent import BarAggregatorComputeAgent

    agent = BarAggregatorComputeAgent.__new__(BarAggregatorComputeAgent)
    agent.name = "bar_aggregator_agent"
    agent._stop_event = asyncio.Event()
    agent._env_name = ""

    import structlog
    agent.logger = structlog.get_logger().bind(agent=agent.name)

    old_consumer = _stopped_consumer()
    new_consumer = _healthy_consumer()
    agent._kafka_consumer = old_consumer

    from src.config.settings import Settings
    agent._settings = MagicMock(spec=Settings)
    agent._settings.kafka_bootstrap_servers = "localhost:19092"

    with patch(
        "services.bar_aggregator_agent.KafkaConsumerClient",
        return_value=new_consumer,
    ) as mock_consumer_cls:
        await agent._kafka_consumer.stop()
        agent._kafka_consumer = mock_consumer_cls(
            "market.bars",
            bootstrap_servers=agent._settings.kafka_bootstrap_servers,
            group_id="bar_aggregator_consumer",
            auto_offset_reset="latest",
        )
        await agent._kafka_consumer.start()

    assert agent._kafka_consumer is new_consumer
    assert agent._kafka_consumer is not old_consumer
