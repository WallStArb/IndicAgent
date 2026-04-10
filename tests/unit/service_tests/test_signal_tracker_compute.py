"""Tests for SignalTrackerCompute — DB-ignorant lifecycle evaluation agent.

Uses __new__ pattern per CLAUDE.md to bypass __init__ and manually set
instance attributes required by each test.
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.signal_tracker_compute import SignalTrackerCompute


def _read_source() -> str:
    """Read the agent source file for structural assertions."""
    from pathlib import Path

    return Path("services/signal_tracker_compute.py").read_text()


def _make_agent() -> SignalTrackerCompute:
    """Create a SignalTrackerCompute bypassing __init__."""
    agent = SignalTrackerCompute.__new__(SignalTrackerCompute)
    agent.logger = MagicMock()
    agent._stop_event = MagicMock()
    agent._stop_event.is_set.return_value = False

    # In-memory state
    agent._active_index: dict[tuple[str, str], list[dict]] = defaultdict(list)
    agent._active_symbols: set[str] = set()
    agent._signal_ids: set[str] = set()
    agent._mae: dict[str, float] = {}
    agent._mfe: dict[str, float] = {}
    agent._chandelier_state: dict[str, dict] = {}
    agent._staleness_consecutive: dict[str, int] = {}
    agent._activated_at: dict[str, datetime] = {}
    agent._point_values: dict[str, float] = {}

    # Kafka producer mock
    agent._producer = AsyncMock()

    # Metrics mocks (avoid Prometheus registry collision in tests)
    agent._transitions_total = MagicMock()
    agent._active_signals_gauge = MagicMock()

    # Settings
    agent._settings = MagicMock()
    agent._settings.env_name = "dev"
    agent._settings.kafka_bootstrap_servers = "localhost:19092"
    agent._env_name = "dev"

    return agent


# ---------------------------------------------------------------------------
# Structural tests — read source, assert patterns
# ---------------------------------------------------------------------------


class TestStructural:
    """Verify naming, inheritance, and absence of DB writes in source."""

    def test_class_name(self):
        src = _read_source()
        assert "SignalTrackerCompute" in src

    def test_inherits_base_agent(self):
        src = _read_source()
        assert "BaseAgent" in src

    def test_no_db_writes(self):
        """ComputeAgent must not contain any direct DB write methods."""
        src = _read_source()
        forbidden = [
            "record_activation",
            "record_zone_resolution",
            "record_market_resolution",
            "execute_batch",
        ]
        for word in forbidden:
            assert word not in src, f"Forbidden DB-write method found: {word}"

    def test_uses_lifecycle_transitions(self):
        src = _read_source()
        assert "lifecycle_transitions" in src
        assert "TransitionType" in src

    def test_has_symbol_filter(self):
        src = _read_source()
        assert "_active_symbols" in src

    def test_uses_evaluate_signal(self):
        src = _read_source()
        assert "evaluate_signal" in src

    def test_consumes_i7_signals(self):
        src = _read_source()
        assert "topic_intelligence_i7_signals" in src


# ---------------------------------------------------------------------------
# Behavioral tests — using __new__ pattern
# ---------------------------------------------------------------------------


class TestSymbolFilter:
    """Symbol filter skips ~70% of bars for irrelevant symbols."""

    def test_symbol_filter_skips_irrelevant_bars(self):
        agent = _make_agent()
        agent._active_symbols = {"ESM6", "NQM6"}
        assert agent._should_process_bar("VXM6", "1m") is False

    def test_symbol_filter_passes_relevant_symbols(self):
        agent = _make_agent()
        agent._active_symbols = {"ESM6", "NQM6"}
        assert agent._should_process_bar("ESM6", "1m") is True

    def test_symbol_filter_empty_set(self):
        agent = _make_agent()
        agent._active_symbols = set()
        assert agent._should_process_bar("ESM6", "1m") is False


class TestTimeframeFilter:
    """Only signals matching the bar's timeframe are evaluated."""

    def test_timeframe_filter_returns_matching_signals(self):
        agent = _make_agent()
        sig_1m = {"signal_id": "s1", "timeframe": "1m", "status": "pending"}
        sig_5m = {"signal_id": "s2", "timeframe": "5m", "status": "pending"}
        agent._active_index[("ESM6", "1m")] = [sig_1m]
        agent._active_index[("ESM6", "5m")] = [sig_5m]

        result = agent._get_signals_for_bar("ESM6", "1m")
        assert len(result) == 1
        assert result[0]["signal_id"] == "s1"

    def test_timeframe_filter_empty_for_unknown_tf(self):
        agent = _make_agent()
        agent._active_index[("ESM6", "1m")] = [
            {"signal_id": "s1", "timeframe": "1m", "status": "pending"}
        ]

        result = agent._get_signals_for_bar("ESM6", "4h")
        assert result == []


class TestIngestSignal:
    """New signals from i7.signals topic are added to the active index."""

    def test_ingest_new_signal(self):
        agent = _make_agent()
        signal_payload = {
            "signal_id": "abc-123",
            "symbol": "ESM6",
            "timeframe": "1m",
            "status": "pending",
            "direction": 1,
            "entry_price": 5000.0,
            "stop_loss": 4990.0,
            "targets": [5010.0, 5020.0],
            "confidence": 0.7,
        }

        agent._ingest_signal_payload(signal_payload)

        key = ("ESM6", "1m")
        assert key in agent._active_index
        assert len(agent._active_index[key]) == 1
        assert agent._active_index[key][0]["signal_id"] == "abc-123"
        assert "ESM6" in agent._active_symbols

    def test_ingest_multiple_signals_same_symbol(self):
        agent = _make_agent()
        for i in range(3):
            agent._ingest_signal_payload(
                {
                    "signal_id": f"s-{i}",
                    "symbol": "ESM6",
                    "timeframe": "1m",
                    "status": "pending",
                    "direction": 1,
                    "entry_price": 5000.0,
                    "stop_loss": 4990.0,
                    "targets": [5010.0],
                }
            )

        key = ("ESM6", "1m")
        assert len(agent._active_index[key]) == 3


class TestRemoveSignal:
    """Resolved signals are cleaned up from all in-memory state."""

    def test_remove_resolved_signal(self):
        agent = _make_agent()
        agent._active_symbols = {"ESM6"}
        agent._active_index[("ESM6", "1m")] = [
            {"signal_id": "s1", "timeframe": "1m"},
            {"signal_id": "s2", "timeframe": "1m"},
        ]
        agent._mae["s1"] = -0.5
        agent._mfe["s1"] = 1.2
        agent._chandelier_state["s1"] = {"trailing_stop": 5010.0}
        agent._staleness_consecutive["s1"] = 2
        agent._activated_at["s1"] = datetime.now(tz=UTC)

        agent._remove_signal("s1", "ESM6", "1m")

        # s1 removed from index, s2 remains
        assert len(agent._active_index[("ESM6", "1m")]) == 1
        assert agent._active_index[("ESM6", "1m")][0]["signal_id"] == "s2"

        # Per-signal state cleaned up
        assert "s1" not in agent._mae
        assert "s1" not in agent._mfe
        assert "s1" not in agent._chandelier_state
        assert "s1" not in agent._staleness_consecutive
        assert "s1" not in agent._activated_at

        # Symbol stays in _active_symbols (s2 still active)
        assert "ESM6" in agent._active_symbols

    def test_remove_last_signal_removes_symbol(self):
        agent = _make_agent()
        agent._active_symbols = {"ESM6"}
        agent._active_index[("ESM6", "1m")] = [
            {"signal_id": "s1", "timeframe": "1m"},
        ]

        agent._remove_signal("s1", "ESM6", "1m")

        # No more signals for ESM6, so symbol should be removed
        assert "ESM6" not in agent._active_symbols

    def test_remove_signal_with_empty_index(self):
        """Removing a signal that doesn't exist in index should not error."""
        agent = _make_agent()
        agent._active_symbols = set()
        agent._active_index = defaultdict(list)
        # Should not raise
        agent._remove_signal("nonexistent", "ESM6", "1m")


class TestTransitionMapping:
    """Transition from evaluate_signal() is mapped to LifecycleTransition correctly."""

    def test_activation_transition(self):
        from src.intelligence.trading.lifecycle_tracker import Transition
        from src.intelligence.trading.lifecycle_transitions import TransitionType

        agent = _make_agent()
        transition = Transition(
            signal_id="s1",
            new_status="active",
            activation_price=5005.0,
            zone_entry_pct=0.3,
            bars_to_activation=3,
        )

        bar_time = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)
        lt = agent._transition_to_lifecycle(transition, "ESM6", "1m", bar_time)

        assert lt.transition_type == TransitionType.ACTIVATION
        assert lt.signal_id == "s1"
        assert lt.symbol == "ESM6"
        assert lt.timeframe == "1m"
        assert lt.bar_ts == bar_time
        assert lt.data["activated_at"] == bar_time
        assert lt.data["activation_price"] == 5005.0
        assert lt.data["zone_entry_pct"] == 0.3
        assert lt.data["bars_to_activation"] == 3

    def test_exit_transition(self):
        from src.intelligence.trading.lifecycle_tracker import Transition
        from src.intelligence.trading.lifecycle_transitions import TransitionType

        agent = _make_agent()
        transition = Transition(
            signal_id="s2",
            new_status="expired",
            exit_reason="stop_loss",
            exit_price=4990.0,
            pnl_r=-1.0,
            pnl_dollars=-50.0,
            mae=-1.0,
            mfe=0.3,
            bars_in_trade=5,
            outcome="stopped_in_trade",
        )

        bar_time = datetime(2026, 4, 10, 12, 5, tzinfo=UTC)
        lt = agent._transition_to_lifecycle(transition, "ESM6", "1m", bar_time)

        assert lt.transition_type == TransitionType.EXIT
        assert lt.data["exit_price"] == 4990.0
        assert lt.data["exit_reason"] == "stop_loss"
        assert lt.data["pnl_r"] == -1.0
        assert lt.data["outcome"] == "stopped_in_trade"
        assert lt.data["mae"] == -1.0
        assert lt.data["mfe"] == 0.3
        assert lt.data["bars_in_trade"] == 5

    def test_transition_data_uses_datetime_not_string(self):
        """Data dicts must use datetime objects, not ISO strings (asyncpg compat)."""
        from src.intelligence.trading.lifecycle_tracker import Transition

        agent = _make_agent()
        transition = Transition(
            signal_id="s1",
            new_status="active",
            activation_price=5000.0,
        )

        bar_time = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)
        lt = agent._transition_to_lifecycle(transition, "ESM6", "1m", bar_time)

        # activated_at must be a datetime, not a string
        assert isinstance(lt.data["activated_at"], datetime)


class TestBarEvaluation:
    """Test _evaluate_bar runs evaluate_signal and publishes transitions."""

    @pytest.mark.asyncio
    async def test_evaluate_bar_with_activation(self):
        """Pending signal that gets activated should produce an ACTIVATION transition."""
        agent = _make_agent()
        now = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)
        sig_ts = now - timedelta(minutes=3)

        signal = {
            "signal_id": "s1",
            "timeframe": "1m",
            "status": "pending",
            "direction": 1,
            "entry_price": 5000.0,
            "stop_loss": 4990.0,
            "entry_zone_low": 4998.0,
            "entry_zone_high": 5002.0,
            "targets": [5010.0],
            "ttl_bars": 20,
            "bars_elapsed": 3,
            "timestamp": sig_ts,
        }

        agent._active_index[("ESM6", "1m")] = [signal]
        agent._active_symbols = {"ESM6"}

        bar = {"high": 5005.0, "low": 4999.0, "close": 5003.0}

        await agent._evaluate_bar("ESM6", "1m", bar, now)

        # Should have published a transition
        assert agent._producer.publish.call_count == 1

    @pytest.mark.asyncio
    async def test_evaluate_bar_no_transition(self):
        """Signal that stays in same state produces no Kafka publish."""
        agent = _make_agent()
        now = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)
        sig_ts = now - timedelta(minutes=1)

        # Pending signal, bar outside entry zone
        signal = {
            "signal_id": "s1",
            "timeframe": "1m",
            "status": "pending",
            "direction": 1,
            "entry_price": 5000.0,
            "stop_loss": 4990.0,
            "entry_zone_low": 4998.0,
            "entry_zone_high": 5002.0,
            "targets": [5010.0],
            "ttl_bars": 20,
            "bars_elapsed": 1,
            "timestamp": sig_ts,
        }

        agent._active_index[("ESM6", "1m")] = [signal]
        agent._active_symbols = {"ESM6"}

        # Bar far from entry zone
        bar = {"high": 4950.0, "low": 4945.0, "close": 4948.0}

        await agent._evaluate_bar("ESM6", "1m", bar, now)

        # No transition, no publish
        agent._producer.publish.assert_not_called()
