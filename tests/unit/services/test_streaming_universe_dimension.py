"""Streaming-path daemons read the `live` universe, never the default `compute` one.

Phase 174 code review CR-02: migration 337 split `live_tradeable` out of `is_active` so a
provider restart cannot subscribe to the whole compute universe (233+ symbols) against
IBKR's 80-simultaneous-subscription cap, but no caller passed dimension="live". These tests
pin the dimension at every streaming call site and the provider's fail-loud startup guard.
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.models import AssetClass, Instrument

_REPO = Path(__file__).resolve().parents[3]

# Streaming-path call sites and the dimension each must pass explicitly. provider_merger's
# lookup table is deliberately the widest dimension: it maps, it does not choose a universe.
_EXPECTED_DIMENSION = {
    "src/providers/base_provider_agent.py": "live",
    "services/feature_vector_pipeline.py": "live",
    "services/bar_auditor.py": "live",
    "services/signal_auditor.py": "live",
    "services/service_auditor.py": "live",
    "services/provider_merger.py": "backfill",
}


def _get_active_contracts_calls(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text())
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "get_active_contracts"
    ]


@pytest.mark.parametrize(("rel_path", "dimension"), sorted(_EXPECTED_DIMENSION.items()))
def test_streaming_call_sites_pass_explicit_dimension(rel_path, dimension):
    calls = _get_active_contracts_calls(_REPO / rel_path)
    assert calls, f"{rel_path}: expected at least one get_active_contracts() call"
    for call in calls:
        kw = {k.arg: k.value for k in call.keywords}
        assert "dimension" in kw, (
            f"{rel_path}:{call.lineno} relies on the default dimension ('compute'); "
            f"streaming daemons must pass dimension={dimension!r} explicitly"
        )
        assert isinstance(kw["dimension"], ast.Constant) and kw["dimension"].value == dimension


def _instruments(n: int) -> list[Instrument]:
    return [
        Instrument(symbol=f"S{i}", asset_class=AssetClass.EQUITY, exchange="SMART")
        for i in range(n)
    ]


def _agent(cap: int | None):
    from src.providers.base_provider_agent import BaseProvider

    class _Agent(BaseProvider):
        def _agent_name(self) -> str:
            return "test_provider_agent"

        def _provider_name_str(self) -> str:
            return "test"

        def _create_adapter(self):
            return MagicMock()

        def _max_live_subscriptions(self) -> int | None:
            return cap

    agent = _Agent.__new__(_Agent)
    agent.name = "test_provider_agent"
    agent.settings = MagicMock()
    return agent


def test_provider_reads_live_dimension():
    agent = _agent(cap=80)
    with patch(
        "src.providers.base_provider_agent.get_active_contracts", return_value=[]
    ) as mock_gac:
        agent._get_instruments()
    mock_gac.assert_called_once_with(agent.settings, dimension="live")


def test_empty_streaming_universe_fails_loudly():
    with pytest.raises(RuntimeError, match="live_tradeable"):
        _agent(cap=80)._validate_streaming_universe([])


def test_over_cap_streaming_universe_fails_loudly():
    with pytest.raises(RuntimeError, match="81 live_tradeable.*80-subscription cap"):
        _agent(cap=80)._validate_streaming_universe(_instruments(81))


def test_universe_exactly_at_cap_passes():
    _agent(cap=80)._validate_streaming_universe(_instruments(80))


def test_uncapped_provider_accepts_any_nonempty_universe():
    _agent(cap=None)._validate_streaming_universe(_instruments(500))


def test_setup_validates_before_connecting_to_provider():
    """A misconfigured universe must abort before any provider connection is opened."""
    agent = _agent(cap=80)
    agent.settings.database_url = "postgresql://unused"
    agent.settings.kafka_bootstrap_servers = "localhost:9092"
    agent._create_adapter = MagicMock()
    with (
        patch("src.providers.base_provider_agent.create_db_pool", new=AsyncMock()),
        patch("src.providers.base_provider_agent.KafkaProducerClient") as mock_producer,
        patch("src.providers.base_provider_agent.get_active_contracts", return_value=[]),
    ):
        mock_producer.return_value.start = AsyncMock()
        with pytest.raises(RuntimeError, match="streaming universe is empty"):
            asyncio.run(agent._setup())
    agent._create_adapter.assert_not_called()


def test_ibkr_provider_cap_comes_from_settings():
    from services.ibkr_provider import IBKRProvider

    agent = IBKRProvider.__new__(IBKRProvider)
    agent.settings = MagicMock(ibkr_max_subscriptions=80)
    assert agent._max_live_subscriptions() == 80
