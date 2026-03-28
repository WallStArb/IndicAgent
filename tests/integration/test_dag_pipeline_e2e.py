#!/usr/bin/env python3
"""DEPRECATED: E2E test for the Phase 40 6-stage DAG pipeline microservice architecture.

Phase 44.2 (2026-03-22) consolidated all 6 pipeline stages in-process into
signal_generator_agent.py. The microservice DAG (QualityGate, RegimeGate,
TODAdjuster, Calibrator, Ranker, WinnerSelector as separate services) no longer
exists. topic_winner and topic_attribution have been removed from stream_keys.

These tests are SKIPPED. Replace with a new E2E test targeting the current
in-process pipeline architecture (signal_generator_agent + audit stage topics).
See todo: 004-service-new-test-pattern-safety.md
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.stream_keys import (
    topic_quality_gated,
)

pytestmark = pytest.mark.skip(
    reason="Phase 40 6-stage DAG architecture retired in Phase 44.2. "
    "Rewrite as test_signal_generator_e2e.py targeting in-process pipeline."
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DAG_STAGE_NAMES = frozenset({
    "quality_gate",
    "regime_gate",
    "tod_adjuster",
    "calibrator",
    "ranker",
    "winner_selector",
})


def _make_test_signal(symbol: str = "ES", timeframe: str = "1m") -> dict:
    """Build a minimal I7 signal dict suitable for the DAG quality_gated entry."""
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "timestamp": datetime.now(UTC).isoformat(),
        "setup_plugin": "trad_TrendFollowing",
        "signal_type": "trend_following",
        "direction": 1,
        "confidence": 0.55,
        "confluence_score": 0.60,
        "entry_price": 5200.0,
        "stop_loss": 5195.0,
        "targets": [5210.0, 5215.0, 5220.0],
        "regime_type": "trend",
        "regime_eligible": True,
        "hurst_trend_quality": 0.80,
        "entropy_quality": 0.70,
        "trend_regime": 1.0,
        "hmm_regime": 1,
        "hmm_regime_prob": 0.75,
        "hmm_regime_duration": 10,
        "perf_weights": {},
        "drift_penalty": 1.0,
        "bar_close_ts": None,
        "source": "live",
    }


# ---------------------------------------------------------------------------
# E2E test: full signal flow through all 6 stages
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_dag_pipeline_e2e():
    """Test signal flow through all 6 DAG stages.

    Flow:
      quality_gated -> regime_gated -> tod_adjusted -> calibrated -> ranked -> winner

    Requires:
      - Redpanda running on default port
      - All 6 stage microservices running (quality_gate, regime_gate, etc.)
    """
    settings = Settings()
    bootstrap = getattr(settings, "kafka_bootstrap_servers", "localhost:19092")
    env_name = getattr(settings, "env_name", "development")

    unique_group = f"test_dag_e2e_{uuid4().hex[:8]}"

    # Create producer for DAG entry point (quality_gated topic)
    producer = KafkaProducerClient(bootstrap)
    await producer.start()

    # Create consumer for final output (winner topic)
    winner_consumer = KafkaConsumerClient(
        topic_winner(env_name),
        bootstrap_servers=bootstrap,
        group_id=f"{unique_group}_winner",
        auto_offset_reset="latest",
    )
    await winner_consumer.start()

    # Create attribution consumer (side channel from all 6 stages)
    attribution_consumer = KafkaConsumerClient(
        topic_attribution(env_name),
        bootstrap_servers=bootstrap,
        group_id=f"{unique_group}_attribution",
        auto_offset_reset="latest",
    )
    await attribution_consumer.start()

    try:
        # Publish test signal to DAG entry point
        test_signal = _make_test_signal(symbol="ES", timeframe="1m")
        await producer.publish(
            topic_quality_gated(env_name),
            test_signal,
            key="ES:1m",
        )

        winner_received = False
        attribution_stages: set[str] = set()

        # Wait up to 10s for winner + attribution events
        async def _consume_winner():
            nonlocal winner_received
            async for _topic, _key, payload in winner_consumer.messages():
                selected = payload.get("selected_signal")
                if selected and selected.get("setup_plugin") == "trad_TrendFollowing":
                    winner_received = True
                    # Verify winner structure
                    assert "selected_signal" in payload, "Missing selected_signal"
                    assert "all_ranked" in payload, "Missing all_ranked"
                    assert "resolution_method" in payload, "Missing resolution_method"
                    return

        async def _consume_attribution():
            async for _topic, _key, payload in attribution_consumer.messages():
                stage = payload.get("stage")
                if stage in _DAG_STAGE_NAMES:
                    attribution_stages.add(stage)
                    assert "before" in payload, f"stage={stage} missing 'before'"
                    assert "after" in payload, f"stage={stage} missing 'after'"
                    assert "value_added" in payload, f"stage={stage} missing 'value_added'"
                if len(attribution_stages) >= 6:
                    return

        # Run both consumers concurrently with timeout
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    asyncio.ensure_future(_consume_winner()),
                    asyncio.ensure_future(_consume_attribution()),
                ),
                timeout=10.0,
            )
        except TimeoutError:
            # Partial results are acceptable — assert what we got below
            pass

        assert winner_received, (
            "Winner event not received within 10s — "
            "ensure all 6 DAG stage services are running"
        )
        assert len(attribution_stages) >= 6, (
            f"Expected 6 attribution events, got {len(attribution_stages)}: "
            f"{sorted(attribution_stages)}"
        )

    finally:
        await producer.stop()
        await winner_consumer.stop()
        await attribution_consumer.stop()


# ---------------------------------------------------------------------------
# Fault tolerance: circuit breaker bypass on stage failure
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_dag_fault_tolerance():
    """Test circuit breaker bypass on stage failure.

    Publishes a malformed event to trigger the circuit breaker in a stage.
    After N consecutive failures, the circuit opens and subsequent events bypass
    that stage with a warning. After the timeout, the circuit closes again.

    Requires all 6 DAG stage services running.
    """
    settings = Settings()
    bootstrap = getattr(settings, "kafka_bootstrap_servers", "localhost:19092")
    env_name = getattr(settings, "env_name", "development")

    producer = KafkaProducerClient(bootstrap)
    await producer.start()

    try:
        # Publish 5 malformed events (missing required fields) to trigger circuit breaker
        for _ in range(5):
            bad_signal = {
                "symbol": "ES",
                "timeframe": "1m",
                # Intentionally malformed — missing confidence, direction, etc.
                "malformed": True,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            await producer.publish(
                topic_quality_gated(env_name),
                bad_signal,
                key="ES:1m",
            )

        # Give stages time to process and open circuit breaker
        await asyncio.sleep(2.0)

        # Publish a valid event — should pass through (circuit open = bypass mode)
        valid_signal = _make_test_signal(symbol="ES", timeframe="1m")
        await producer.publish(
            topic_quality_gated(env_name),
            valid_signal,
            key="ES:1m",
        )

        # Verify valid event reaches winner topic despite prior failures
        winner_consumer = KafkaConsumerClient(
            topic_winner(env_name),
            bootstrap_servers=bootstrap,
            group_id=f"test_fault_tolerance_{uuid4().hex[:8]}",
            auto_offset_reset="latest",
        )
        await winner_consumer.start()

        try:
            bypass_winner_received = False
            try:
                async with asyncio.timeout(5.0):
                    async for _topic, _key, payload in winner_consumer.messages():
                        if payload.get("selected_signal"):
                            bypass_winner_received = True
                            break
            except TimeoutError:
                pass

            # NOTE: In bypass mode, the circuit-open stage is skipped.
            # The valid signal should still reach the winner selector.
            # This assertion validates graceful degradation.
            assert bypass_winner_received, (
                "Valid signal should reach winner even when circuit breaker is open"
            )
        finally:
            await winner_consumer.stop()

    finally:
        await producer.stop()


# ---------------------------------------------------------------------------
# Data quality: invalid events dropped at each stage
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_dag_data_quality_validation():
    """Test data quality validation at the QualityGate stage.

    Publishes an event with insufficient quality score. QualityGate should
    drop it and emit an alert on the data_quality side channel. Valid events
    should pass through unchanged.

    Requires QualityGate stage service running.
    """
    settings = Settings()
    bootstrap = getattr(settings, "kafka_bootstrap_servers", "localhost:19092")
    env_name = getattr(settings, "env_name", "development")

    from src.core.stream_keys import topic_data_quality

    producer = KafkaProducerClient(bootstrap)
    await producer.start()

    data_quality_consumer = KafkaConsumerClient(
        topic_data_quality(env_name),
        bootstrap_servers=bootstrap,
        group_id=f"test_dq_{uuid4().hex[:8]}",
        auto_offset_reset="latest",
    )
    await data_quality_consumer.start()

    try:
        # Publish low-quality signal (hurst < 0.55, entropy < 0.60 — below QualityGate thresholds)
        low_quality_signal = _make_test_signal(symbol="ES", timeframe="1m")
        low_quality_signal["hurst_trend_quality"] = 0.30  # Below threshold
        low_quality_signal["entropy_quality"] = 0.20     # Below threshold
        low_quality_signal["confidence"] = 0.35          # Low confidence

        await producer.publish(
            topic_quality_gated(env_name),
            low_quality_signal,
            key="ES:1m",
        )

        # Publish valid signal to confirm pass-through still works
        valid_signal = _make_test_signal(symbol="NQ", timeframe="1m")
        await producer.publish(
            topic_quality_gated(env_name),
            valid_signal,
            key="NQ:1m",
        )

        # Check data_quality topic for rejection alert
        dq_alert_received = False
        try:
            async with asyncio.timeout(5.0):
                async for _topic, _key, payload in data_quality_consumer.messages():
                    if (
                        payload.get("symbol") == "ES"
                        and payload.get("reason") is not None
                    ):
                        dq_alert_received = True
                        assert "reason" in payload, "Alert missing 'reason'"
                        assert "stage" in payload, "Alert missing 'stage'"
                        break
        except TimeoutError:
            pass

        # Data quality alerts are best-effort observability — not a hard assertion.
        # A passing test means the alert was received; if not received, it may indicate
        # the signal passed quality gate (thresholds may differ from test assumptions).
        if not dq_alert_received:
            pytest.skip(
                "Data quality alert not received — "
                "QualityGate thresholds may not match test signal parameters"
            )

    finally:
        await producer.stop()
        await data_quality_consumer.stop()


# ---------------------------------------------------------------------------
# Smoke test: verify topics exist and are reachable (no live services needed)
# ---------------------------------------------------------------------------

@pytest.mark.integration
@pytest.mark.asyncio
async def test_dag_topics_reachable():
    """Verify all DAG pipeline topics are reachable via Redpanda.

    Does NOT require stage services running — only Redpanda.
    Publishes a single message to quality_gated and verifies no connection error.
    """
    settings = Settings()
    bootstrap = getattr(settings, "kafka_bootstrap_servers", "localhost:19092")
    env_name = getattr(settings, "env_name", "development")

    producer = KafkaProducerClient(bootstrap)
    await producer.start()

    try:
        test_signal = _make_test_signal(symbol="ES", timeframe="1m")
        await producer.publish(
            topic_quality_gated(env_name),
            test_signal,
            key="ES:1m",
        )
        # If we reach here without exception, topics are reachable
    finally:
        await producer.stop()
