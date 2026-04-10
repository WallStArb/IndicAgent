"""Tests for SignalMetricsComputeAgent."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.signal_metrics_compute_agent import SignalMetricsComputeAgent


class TestSignalMetricsComputeAgent:
    def _make_agent(self):
        agent = SignalMetricsComputeAgent.__new__(SignalMetricsComputeAgent)
        agent.logger = MagicMock()
        agent._stop_event = MagicMock()
        agent._stop_event.is_set.return_value = False
        agent._settings = MagicMock()
        agent._settings.env_name = ""
        agent._db = MagicMock()
        agent._producer = MagicMock()
        agent._interval_seconds = 900
        agent._tick_sizes = {"ES": 0.25}
        agent._published_dq_keys = set()
        agent._cycle_count = 1  # skip tick_sizes refresh (already populated)
        return agent

    def test_agent_has_required_attributes(self):
        agent = self._make_agent()
        assert hasattr(agent, "_interval_seconds")
        assert agent._interval_seconds == 900  # 15 min

    @pytest.mark.asyncio
    async def test_run_compute_cycle_queries_signal_ledger(self):
        agent = self._make_agent()
        agent._db.execute_query = AsyncMock(return_value=[])
        agent._producer.publish = AsyncMock()
        await agent._run_compute_cycle()
        # tick_sizes already populated in fixture; only signal_ledger query expected
        assert agent._db.execute_query.call_count == 1

    @pytest.mark.asyncio
    async def test_run_compute_cycle_publishes_no_events_for_empty_db(self):
        agent = self._make_agent()
        agent._db.execute_query = AsyncMock(return_value=[])
        agent._producer.publish = AsyncMock()
        await agent._run_compute_cycle()
        agent._producer.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_dq_failures_published_as_separate_events(self):
        """Rows failing DQ validation produce MetricsDQEvent payloads."""
        agent = self._make_agent()
        # Row with near-zero risk — should fail Gate 2 (ES tick=0.25, risk=0.01)
        bad_row = {
            "signal_id": "00000000-0000-0000-0000-000000000001",
            "setup_plugin": "trad_CVDDivergence",
            "tf": "5m",
            "symbol": "ESM6",
            "hmm_regime_at_fire": 1,
            "direction": 1,
            "entry_price": 5000.0,
            "stop_loss": 5000.01,  # risk = 0.01 < ES tick (0.25)
            "pnl_r": -193.0,
            "mae": -193.0,
            "mfe": 0.0,
            "outcome": "stopped_in_trade",
            "confidence": 0.6,
            "exit_at": None,
            "market_entry_pnl_r": None,
            "market_entry_mae": None,
            "market_entry_mfe": None,
            "market_entry_outcome": None,
        }
        agent._db.execute_query = AsyncMock(return_value=[bad_row])
        agent._producer.publish = AsyncMock()
        await agent._run_compute_cycle()
        # Should have published a DQ failure event
        calls = agent._producer.publish.call_args_list
        dq_calls = [c for c in calls if "dq_failure" in str(c)]
        assert len(dq_calls) >= 1

    @pytest.mark.asyncio
    async def test_dq_failures_not_republished_on_second_cycle(self):
        """Same signal should not produce duplicate DQ failure on second cycle."""
        agent = self._make_agent()
        bad_row = {
            "signal_id": "00000000-0000-0000-0000-000000000001",
            "setup_plugin": "trad_CVDDivergence",
            "tf": "5m",
            "symbol": "ESM6",
            "hmm_regime_at_fire": 1,
            "direction": 1,
            "entry_price": 5000.0,
            "stop_loss": 5000.01,
            "pnl_r": -193.0,
            "mae": -193.0,
            "mfe": 0.0,
            "outcome": "stopped_in_trade",
            "confidence": 0.6,
            "exit_at": None,
            "market_entry_pnl_r": None,
            "market_entry_mae": None,
            "market_entry_mfe": None,
            "market_entry_outcome": None,
        }
        agent._db.execute_query = AsyncMock(return_value=[bad_row])
        agent._producer.publish = AsyncMock()
        # First cycle
        await agent._run_compute_cycle()
        first_dq_count = len([c for c in agent._producer.publish.call_args_list if "dq_failure" in str(c)])
        assert first_dq_count == 1
        # Second cycle — same data
        agent._producer.publish.reset_mock()
        await agent._run_compute_cycle()
        second_dq_count = len([c for c in agent._producer.publish.call_args_list if "dq_failure" in str(c)])
        assert second_dq_count == 0  # dedup: already published
