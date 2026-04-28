"""Tests for SignalTrackerCompute — DB-ignorant lifecycle evaluation agent.

Uses __new__ pattern per CLAUDE.md to bypass __init__ and manually set
instance attributes required by each test.
"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.signal_tracker_compute_agent import SignalTrackerCompute


def _read_source() -> str:
    """Read the agent source file for structural assertions."""
    from pathlib import Path

    return Path("services/signal_tracker_compute_agent.py").read_text()


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
    agent.settings = MagicMock(env_name="dev")
    agent.settings.kafka_bootstrap_servers = "localhost:19092"

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


class TestBootstrapTTLSweep:
    """D-03: Bootstrap expires signals past reasonable TTL before loading."""

    def test_sweep_runs_before_select(self):
        """Verify that TTL sweep UPDATE runs before the SELECT query.
        This is a structural test — we check the SQL exists in source.
        """
        src = _read_source()
        # Check that sweep SQL exists with UPDATE signal_ledger SET status = 'expired'
        assert "UPDATE signal_ledger" in src
        assert "SET status = 'expired'" in src
        assert "ttl_expired" in src

    def test_sweep_only_targets_pending(self):
        """Sweep should only expire pending signals, not active ones.
        Check WHERE clause in SQL.
        """
        src = _read_source()
        # Should have WHERE status = 'pending'
        assert "WHERE status = 'pending'" in src or "WHERE status IN ('pending'" in src


class TestActivationProbabilityGate:
    """D-05: Hopeless signals are filtered at ingestion."""

    def test_far_zone_and_low_ttl_filtered(self):
        """Zone > 3x risk away AND <20% TTL remaining -> filtered."""
        agent = _make_agent()
        signal_payload = {
            "signal_id": "gate-test-1",
            "symbol": "ESM6",
            "timeframe": "1m",
            "direction": 1,
            "entry_price": 5100.0,
            "stop_loss": 5085.0,  # risk = 15
            "entry_zone_low": 4950.0,  # 150 pts away = 10x risk -> far
            "entry_zone_high": 4960.0,
            "ttl_bars": 10,
            "bars_elapsed": 9,  # 90% elapsed -> 10% remaining
        }
        agent._ingest_signal_payload(signal_payload)
        # Signal should NOT be in active index (filtered by gate)
        assert "gate-test-1" not in agent._signal_ids

    def test_close_zone_not_filtered(self):
        """Zone close to entry -> NOT filtered, added to index."""
        agent = _make_agent()
        signal_payload = {
            "signal_id": "gate-test-2",
            "symbol": "ESM6",
            "timeframe": "1m",
            "direction": 1,
            "entry_price": 5100.0,
            "stop_loss": 5085.0,
            "entry_zone_low": 5095.0,  # 5 pts away = 0.33x risk -> close
            "entry_zone_high": 5105.0,
            "ttl_bars": 10,
            "bars_elapsed": 0,  # 100% remaining
        }
        agent._ingest_signal_payload(signal_payload)
        assert "gate-test-2" in agent._signal_ids

    def test_high_ttl_remaining_not_filtered(self):
        """Zone far away but >20% TTL remaining -> NOT filtered."""
        agent = _make_agent()
        signal_payload = {
            "signal_id": "gate-test-3",
            "symbol": "ESM6",
            "timeframe": "1m",
            "direction": 1,
            "entry_price": 5100.0,
            "stop_loss": 5085.0,
            "entry_zone_low": 4950.0,  # 10x risk -> far
            "entry_zone_high": 4960.0,
            "ttl_bars": 10,
            "bars_elapsed": 2,  # 80% remaining -> not filtered
        }
        agent._ingest_signal_payload(signal_payload)
        assert "gate-test-3" in agent._signal_ids

    def test_missing_zone_fields_not_filtered(self):
        """Missing zone fields -> gate is no-op, signal added normally."""
        agent = _make_agent()
        signal_payload = {
            "signal_id": "gate-test-4",
            "symbol": "ESM6",
            "timeframe": "1m",
            "direction": 1,
            "entry_price": 5100.0,
            "stop_loss": 5085.0,
            # No entry_zone_low/high
            "ttl_bars": 10,
            "bars_elapsed": 9,
        }
        agent._ingest_signal_payload(signal_payload)
        assert "gate-test-4" in agent._signal_ids

    def test_gate_logs_filtered_signal(self):
        """Gate should log when filtering a hopeless signal."""
        agent = _make_agent()
        signal_payload = {
            "signal_id": "gate-test-log",
            "symbol": "ESM6",
            "timeframe": "1m",
            "direction": 1,
            "entry_price": 5100.0,
            "stop_loss": 5085.0,
            "entry_zone_low": 4950.0,  # Far zone
            "entry_zone_high": 4960.0,
            "ttl_bars": 10,
            "bars_elapsed": 9,  # Low TTL remaining
        }
        agent._ingest_signal_payload(signal_payload)
        # Should have logged the filter action
        agent.logger.debug.assert_called()
        # Check the call contains "activation_gate_filtered"
        call_args = str(agent.logger.debug.call_args)
        assert "activation_gate_filtered" in call_args


class TestTemporalGuardWiring:
    """D-01: Temporal guard parameters passed to evaluate_signal()."""

    @pytest.mark.asyncio
    async def test_evaluate_bar_passes_timestamps(self):
        """_evaluate_bar should pass signal_timestamp and bar_time to evaluate_signal."""
        from unittest.mock import patch

        agent = _make_agent()
        now = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)
        sig_ts = now - timedelta(minutes=3)

        signal = {
            "signal_id": "temporal-test",
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

        # Patch evaluate_signal to inspect the call
        with patch("services.signal_tracker_compute_agent.evaluate_signal") as mock_eval:
            mock_eval.return_value = None  # No transition for this test
            await agent._evaluate_bar("ESM6", "1m", bar, now)

            # Verify evaluate_signal was called with signal_timestamp and bar_time
            assert mock_eval.call_count == 1
            call_kwargs = mock_eval.call_args.kwargs
            assert "signal_timestamp" in call_kwargs
            assert "bar_time" in call_kwargs
            assert call_kwargs["signal_timestamp"] == sig_ts
            assert call_kwargs["bar_time"] == now
