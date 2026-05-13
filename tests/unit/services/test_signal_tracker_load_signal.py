"""Tests for SignalTrackerComputeAgent._load_signal canonical contract.

Covers:
1. test__load_signal_canonical — all 17 canonical fields present with correct types
2. test__load_signal_rejects_empty_timestamp — rejects "" and None timestamps, increments counter
3. test__load_signal_bootstrap_kafka_identical — kafka-shape and bootstrap-shape produce identical dicts
"""

from collections import defaultdict
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from services.signal_tracker_compute_agent import SignalTrackerComputeAgent
from src.observability.metrics import SIGNAL_TRACKER_INVALID_SIGNAL_TOTAL


def _make_agent() -> SignalTrackerComputeAgent:
    """Create a SignalTrackerComputeAgent bypassing __init__."""
    agent = SignalTrackerComputeAgent.__new__(SignalTrackerComputeAgent)
    agent.logger = MagicMock()
    agent._active_index: dict = defaultdict(list)
    agent._active_symbols: set = set()
    agent._signal_ids: set = set()
    agent._mae: dict = {}
    agent._mfe: dict = {}
    agent._market_mae: dict = {}
    agent._market_mfe: dict = {}
    agent._chandelier_state: dict = {}
    agent._staleness_consecutive: dict = {}
    agent._activated_at: dict = {}
    agent._point_values: dict = {}
    agent._producer = MagicMock()
    agent._transitions_total = MagicMock()
    agent._active_signals_gauge = MagicMock()
    agent.settings = MagicMock(env_name="test")
    return agent


def _complete_kafka_payload() -> dict:
    """Complete kafka-shape signal dict with all required fields."""
    return {
        "signal_id": "test-signal-abc",
        "symbol": "ES",
        "tf": "1m",  # kafka uses tf (not timeframe)
        "timestamp": "2026-01-01T10:00:00+00:00",  # kafka uses ISO string
        "entry_price": 5000.0,
        "stop_loss": 4990.0,
        "direction": 1,
        "targets": [5010.0, 5020.0],
        "entry_zone_low": 4998.0,
        "entry_zone_high": 5002.0,
        "is_backfill": False,
        "ttl_bars": 12,
        "signal_schema_version": "v1",
        "status": "pending",
        "market_entry_price": 5001.0,
        "activated_at": None,
        "garch_sigma_at_fire": 0.5,
        "hmm_regime_at_fire": 1,
        # Extra fields that should be ignored
        "extra_field_1": "ignore_me",
        "adjusted_rank": 5,
    }


class TestLoadSignalCanonical:
    """test__load_signal_canonical — all 17 canonical fields present and typed correctly."""

    @pytest.mark.unit
    def test__load_signal_canonical(self):
        agent = _make_agent()
        raw = _complete_kafka_payload()
        result = agent._load_signal(raw)

        assert result is not None, "_load_signal returned None unexpectedly"

        # Must have all 17 canonical fields
        canonical_fields = [
            "signal_id",
            "symbol",
            "timeframe",
            "timestamp",
            "entry_price",
            "stop_loss",
            "is_backfill",
            "ttl_bars",
            "signal_schema_version",
            "status",
            "direction",
            "targets",
            "entry_zone_low",
            "entry_zone_high",
            "market_entry_price",
            "activated_at",
            "garch_sigma_at_fire",
        ]
        for field in canonical_fields:
            assert field in result, f"Missing canonical field: {field}"

        # Type checks
        assert isinstance(result["signal_id"], str)
        assert isinstance(result["timestamp"], datetime)
        assert result["timestamp"].tzinfo is not None, "timestamp must be tz-aware"
        assert result["timestamp"].tzinfo.utcoffset(result["timestamp"]) is not None
        assert isinstance(result["ttl_bars"], int)
        assert isinstance(result["is_backfill"], bool)
        assert isinstance(result["entry_price"], float)
        assert isinstance(result["stop_loss"], float)
        assert isinstance(result["direction"], int)
        assert isinstance(result["targets"], list)
        assert isinstance(result["signal_schema_version"], str)

        # Value assertions
        assert result["signal_id"] == "test-signal-abc"
        assert result["symbol"] == "ES"
        assert result["timeframe"] == "1m"  # _load_signal normalizes tf -> timeframe
        assert result["entry_price"] == 5000.0
        assert result["stop_loss"] == 4990.0
        assert result["ttl_bars"] == 12
        assert result["is_backfill"] is False
        assert result["signal_schema_version"] == "v1"
        assert result["targets"] == [5010.0, 5020.0]


class TestLoadSignalRejectsEmptyTimestamp:
    """test__load_signal_rejects_empty_timestamp — None and "" both rejected + counter incremented."""

    @pytest.mark.unit
    def test__load_signal_rejects_empty_timestamp(self):
        agent = _make_agent()
        base = _complete_kafka_payload()

        # Capture counter before
        counter_before_empty = SIGNAL_TRACKER_INVALID_SIGNAL_TOTAL.labels(
            reason="empty_timestamp"
        )._value.get()

        # Test timestamp="" rejection
        raw_empty = {**base, "timestamp": ""}
        result = agent._load_signal(raw_empty)
        assert result is None, "Expected None for empty string timestamp"
        counter_after_empty = SIGNAL_TRACKER_INVALID_SIGNAL_TOTAL.labels(
            reason="empty_timestamp"
        )._value.get()
        assert (
            counter_after_empty > counter_before_empty
        ), "Counter not incremented for empty_timestamp"

        # Test timestamp=None rejection
        counter_before_none = SIGNAL_TRACKER_INVALID_SIGNAL_TOTAL.labels(
            reason="empty_timestamp"
        )._value.get()
        raw_none = {**base, "timestamp": None}
        result_none = agent._load_signal(raw_none)
        assert result_none is None, "Expected None for None timestamp"
        counter_after_none = SIGNAL_TRACKER_INVALID_SIGNAL_TOTAL.labels(
            reason="empty_timestamp"
        )._value.get()
        assert (
            counter_after_none > counter_before_none
        ), "Counter not incremented for None timestamp"


class TestLoadSignalBootstrapKafkaIdentical:
    """test__load_signal_bootstrap_kafka_identical — different input shapes → identical output dict."""

    @pytest.mark.unit
    def test__load_signal_bootstrap_kafka_identical(self):
        """Kafka-shape (tf, ISO string ts) and bootstrap-shape (timeframe, datetime) produce identical output."""
        agent = _make_agent()

        ts = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
        shared_fields = {
            "signal_id": "match-test-001",
            "symbol": "NQ",
            "entry_price": 22000.0,
            "stop_loss": 21900.0,
            "direction": -1,
            "targets": [21800.0],
            "entry_zone_low": 21990.0,
            "entry_zone_high": 22010.0,
            "is_backfill": True,
            "ttl_bars": 8,
            "signal_schema_version": "v1",
            "status": "pending",
            "market_entry_price": None,
            "activated_at": None,
            "garch_sigma_at_fire": None,
            "hmm_regime_at_fire": None,
        }

        # Kafka shape: tf field + ISO string timestamp
        kafka_raw = {
            **shared_fields,
            "tf": "15m",
            "timestamp": "2026-01-01T10:00:00+00:00",
        }

        # Bootstrap shape: timeframe field + datetime object
        bootstrap_raw = {
            **shared_fields,
            "timeframe": "15m",
            "timestamp": ts,
        }

        result_kafka = agent._load_signal(kafka_raw)
        result_bootstrap = agent._load_signal(bootstrap_raw)

        assert result_kafka is not None, "Kafka path returned None"
        assert result_bootstrap is not None, "Bootstrap path returned None"

        # Both paths must produce byte-identical canonical dicts
        assert result_kafka == result_bootstrap, (
            f"Kafka and bootstrap paths produced different results:\n"
            f"Kafka:     {result_kafka}\n"
            f"Bootstrap: {result_bootstrap}"
        )
