"""Phase 80 integration verification — swarm dispatch + writer round trip."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

SWARM_METRIC_ATTRS = (
    "SWARM_INVOCATIONS_TOTAL",
    "SWARM_MULTIPLIER_DISTRIBUTION",
    "SWARM_AGGREGATED_MULTIPLIER",
    "SWARM_AGENT_WEIGHT",
    "SWARM_SIGNAL_LEDGER_UPDATE_TOTAL",
)


def test_metrics_registered() -> None:
    """All five Phase 80 swarm metrics must exist in the OTel metrics module.

    Metrics are now OTel SDK instruments on the single _meter in metrics.py.
    Verify each constant is exported and is a non-None OTel instrument.
    """
    import src.observability.metrics as m

    for attr in SWARM_METRIC_ATTRS:
        instrument = getattr(m, attr, None)
        assert (
            instrument is not None
        ), f"swarm metric not registered: {attr!r} not found in src.observability.metrics"


@pytest.mark.asyncio
async def test_aggregate_event_round_trips_to_writer() -> None:
    from unittest.mock import patch

    from services.swarm_ledger_writer import SwarmLedgerWriter

    w = SwarmLedgerWriter.__new__(SwarmLedgerWriter)
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

    mock_counter = MagicMock()
    with patch("services.swarm_ledger_writer.SWARM_SIGNAL_LEDGER_UPDATE_TOTAL", mock_counter):
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

    # OTel counter was incremented for a success outcome
    mock_counter.add.assert_called_once()
    # .add(1, {"status": "success"}) — positional args: (amount, attrs)
    call_positional = mock_counter.add.call_args.args
    assert call_positional[0] == 1
    assert call_positional[1].get("status") == "success"
    # First positional arg of the executed UPDATE should be signal_id
    assert any("sig-int-1" in str(c) for c in captured_calls)


def test_compute_final_multiplier_weighted_average() -> None:
    """Aggregator math: explicit weights override default 1/N."""
    from services.alpha_swarm import AlphaSwarm
    from src.core.ai.output import AgentOutput

    a = AlphaSwarm.__new__(AlphaSwarm)
    a.settings = MagicMock()
    a.logger = MagicMock()
    a._agents = []
    # weights: x=1, y=3 -> (1*0.4 + 3*0.8)/(1+3) = 2.8/4 = 0.7
    a._agent_weights = {("x", "5m"): 1.0, ("y", "5m"): 3.0}
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
    result, count = a._compute_final_multiplier(agents_list, [out_x, out_y], "5m")
    assert result == pytest.approx(0.7)
    assert count == 2


def test_no_regression_on_existing_swarm_tests() -> None:
    """Pre-existing test_alpha_swarm.py must keep passing."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-x",
            "tests/unit/services/test_alpha_swarm.py",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        cwd="/home/bg/dev/indicagent",
    )
    assert (
        result.returncode == 0
    ), f"existing swarm tests failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
