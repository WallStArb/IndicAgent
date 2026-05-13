"""Phase 80 integration verification — swarm dispatch + writer round trip."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import REGISTRY

SWARM_METRIC_NAMES = (
    "swarm_invocations_total",
    "swarm_multiplier_distribution",
    "swarm_aggregated_multiplier",
    "swarm_agent_weight",
    "swarm_signal_ledger_update_total",
)

# prometheus_client strips _total suffix from Counter names in REGISTRY.collect()
_REGISTRY_NAME_MAP = {
    "swarm_invocations_total": "swarm_invocations",
    "swarm_signal_ledger_update_total": "swarm_signal_ledger_update",
}


def test_metrics_registered() -> None:
    """All five Phase 80 swarm metrics must exist in the global REGISTRY.

    prometheus_client strips the _total suffix from Counter metric names when
    they are collected from the REGISTRY — e.g. 'swarm_invocations_total'
    is stored under 'swarm_invocations'. _REGISTRY_NAME_MAP handles this
    translation so the test checks canonical metric names without depending
    on internal prometheus_client naming conventions.
    """
    # Trigger registration by importing the metrics module
    import src.observability.metrics  # noqa: F401

    registered = {m.name for m in REGISTRY.collect()}
    for name in SWARM_METRIC_NAMES:
        registry_name = _REGISTRY_NAME_MAP.get(name, name)
        assert registry_name in registered, (
            f"swarm metric not registered: {name!r} (looked up as {registry_name!r}; "
            f"registered subset: {sorted(n for n in registered if 'swarm' in n)})"
        )


@pytest.mark.asyncio
async def test_aggregate_event_round_trips_to_writer() -> None:
    from services.swarm_ledger_writer_agent import SwarmLedgerWriterAgent

    w = SwarmLedgerWriterAgent.__new__(SwarmLedgerWriterAgent)
    w.settings = MagicMock()
    w.logger = MagicMock()

    captured_calls: list = []

    mock_conn = AsyncMock()

    async def fake_execute(*args, **kwargs):
        captured_calls.append(args)
        return "UPDATE 1"

    mock_conn.execute = fake_execute
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=ctx)
    w._pool = pool

    before = (
        REGISTRY.get_sample_value("swarm_signal_ledger_update_total", {"status": "success"}) or 0.0
    )
    await w._handle_event(
        {
            "signal_id": "sig-int-1",
            "symbol": "ES",
            "timeframe": "5m",
            "swarm_multiplier": 0.75,
            "adjusted_confidence": 0.6,
            "swarm_agent_count": 4,
            "ts": "2026-05-05T00:00:00Z",
        }
    )
    after = (
        REGISTRY.get_sample_value("swarm_signal_ledger_update_total", {"status": "success"}) or 0.0
    )
    assert after == before + 1
    # First positional arg of the executed UPDATE should be signal_id
    assert any("sig-int-1" in str(c) for c in captured_calls)


def test_compute_final_multiplier_weighted_average() -> None:
    """Aggregator math: explicit weights override default 1/N."""
    from services.alpha_swarm_agent import AlphaSwarmComputeAgent
    from src.core.ai.output import AgentOutput

    a = AlphaSwarmComputeAgent.__new__(AlphaSwarmComputeAgent)
    a.settings = MagicMock()
    a.logger = MagicMock()
    a._agents = []
    agents_list = [MagicMock(agent_id="x"), MagicMock(agent_id="y")]
    out_x = AgentOutput(
        agent_id="x",
        group="alpha",
        signal_id=None,
        symbol="ES",
        timeframe="5m",
        ts=datetime.now(UTC),
        output_type="multiplier",
        payload={"multiplier": 0.4},
        shadow_only=True,
    )
    out_y = AgentOutput(
        agent_id="y",
        group="alpha",
        signal_id=None,
        symbol="ES",
        timeframe="5m",
        ts=datetime.now(UTC),
        output_type="multiplier",
        payload={"multiplier": 0.8},
        shadow_only=True,
    )
    # weights: x=1, y=3 -> (1*0.4 + 3*0.8)/(1+3) = 2.8/4 = 0.7
    weights = {("x", "5m"): 1.0, ("y", "5m"): 3.0}
    result, count = a._compute_final_multiplier(agents_list, [out_x, out_y], weights, "5m")
    assert result == pytest.approx(0.7)
    assert count == 2


def test_no_regression_on_existing_swarm_tests() -> None:
    """Pre-existing test_alpha_swarm_agent.py must keep passing."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-x",
            "tests/unit/service_tests/test_alpha_swarm_agent.py",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        cwd="/home/bg/dev/indicagent",
    )
    assert (
        result.returncode == 0
    ), f"existing swarm tests failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
