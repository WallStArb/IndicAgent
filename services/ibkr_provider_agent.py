#!/usr/bin/env python3
"""IBKRProviderAgent — thin subclass of BaseProviderAgent for IBKR.

Delegates all lifecycle, metrics, reconnect, and gap-fill logic to
BaseProviderAgent. This file only describes what makes IBKR unique:
- agent name, metrics port, provider name string
- how to build the IBKRAdapter

Metrics port: :9129
"""

from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.providers.base import DataProviderAdapter
from src.providers.base_provider_agent import BaseProviderAgent
from src.providers.ibkr_adapter import IBKRAdapter


class IBKRProviderAgent(BaseProviderAgent):
    """IBKR-specific provider agent.

    One thin subclass — all heavy lifting in BaseProviderAgent.
    Publishes to market.bars.raw.ibkr; MergerAgent routes to market.bars.
    """

    def _agent_name(self) -> str:
        return "ibkr_provider_agent"

    def _agent_metrics_port(self) -> int:
        return 9129

    def _provider_name_str(self) -> str:
        return "ibkr"

    def _create_adapter(self) -> DataProviderAdapter:
        """Return an IBKRAdapter using settings from base class."""
        return IBKRAdapter(
            host=self._settings.ib_host,
            port=self._settings.ib_port,
            client_id=self._settings.ib_client_id,
        )


if __name__ == "__main__":
    import asyncio

    from src.observability.otel import init_tracing

    init_tracing("ibkr_provider_agent")
    agent = IBKRProviderAgent()
    asyncio.run(agent.start())
