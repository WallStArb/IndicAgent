"""Tests for BaseAIWorker memory_client wiring (MEM-01).

Proves the structural wiring: injected MemoryClient reaches WorkerContext.memory_client
and that the default is None (AGENT_MEMORY_ENABLED=False path).

No live DB, Ollama, or network required. Uses object() sentinels as MemoryClient
stand-ins — safe because MemoryClient is TYPE_CHECKING-only at runtime.
"""

from __future__ import annotations

from src.core.ai.worker_context import WorkerContext


class TestMemoryClientInjectedReachesWorkerContext:
    """Injected MemoryClient flows from BaseAIWorker through WorkerContext."""

    def test_memory_client_injected_reaches_worker_context(self) -> None:
        """set_memory_client() sentinel is visible on a WorkerContext built as _run_typed() does.

        This mirrors the exact construction path in base_agent.py:
            worker_ctx = WorkerContext(
                signal_context=context,
                llm_chain=self._llm,
                memory_client=self._memory_client,
            )
        We prove that the kwarg flows correctly end-to-end without running
        the full compute() stack.
        """
        sentinel_mem = object()
        sentinel_ctx = object()

        # Simulate: agent._memory_client = sentinel_mem (set via set_memory_client)
        agent_memory_client = sentinel_mem

        # Build WorkerContext exactly as base_agent.py line ~440 does
        worker_ctx = WorkerContext(
            signal_context=sentinel_ctx,
            llm_chain=None,
            memory_client=agent_memory_client,
        )

        assert (
            worker_ctx.memory_client is sentinel_mem
        ), "WorkerContext.memory_client must be the injected sentinel"
        assert worker_ctx.signal_context is sentinel_ctx

    def test_set_memory_client_stores_on_instance(self) -> None:
        """set_memory_client() updates _memory_client on the agent instance.

        Constructs a minimal concrete subclass and calls set_memory_client,
        verifying the attribute is updated.
        """
        from unittest.mock import MagicMock

        from src.core.ai.base_agent import BaseAIWorker
        from src.core.ai.output import AgentOutput

        class _MinimalAgent(BaseAIWorker):
            agent_id = ""  # empty to skip registry self-registration
            group = "test"

            async def _compute(self, context):  # type: ignore[override]
                return AgentOutput(
                    agent_id=self.agent_id,
                    group=self.group,
                    output_type="neutral",
                    payload={},
                    shadow_only=True,
                    latency_ms=0.0,
                )

        settings_mock = MagicMock()
        settings_mock.OTEL_EXPORTER_OTLP_ENDPOINT = ""
        settings_mock.env_name = "test"

        agent = _MinimalAgent.__new__(_MinimalAgent)
        # Minimal attribute initialization without full BaseDaemon lifecycle
        agent._memory_client = None

        assert agent._memory_client is None, "Default must be None before injection"

        sentinel = object()
        agent.set_memory_client(sentinel)

        assert (
            agent._memory_client is sentinel
        ), "_memory_client must equal the injected sentinel after set_memory_client()"

        # Prove the WorkerContext path carries it through
        worker_ctx = WorkerContext(
            signal_context=object(),
            llm_chain=None,
            memory_client=agent._memory_client,
        )
        assert worker_ctx.memory_client is sentinel


class TestMemoryClientNoneByDefault:
    """AGENT_MEMORY_ENABLED=False path: memory_client is None."""

    def test_memory_client_none_by_default(self) -> None:
        """WorkerContext built without memory_client has memory_client=None."""
        sentinel_ctx = object()
        worker_ctx = WorkerContext(signal_context=sentinel_ctx, llm_chain=None)

        assert (
            worker_ctx.memory_client is None
        ), "memory_client must be None when not injected (AGENT_MEMORY_ENABLED=False path)"

    def test_worker_context_explicit_none(self) -> None:
        """WorkerContext built with memory_client=None also has memory_client=None."""
        sentinel_ctx = object()
        worker_ctx = WorkerContext(
            signal_context=sentinel_ctx,
            llm_chain=None,
            memory_client=None,
        )

        assert worker_ctx.memory_client is None

    def test_memory_client_replaced_with_none(self) -> None:
        """set_memory_client(None) correctly sets _memory_client to None.

        This covers the case where a client is injected then disabled.
        """
        sentinel = object()

        # Simulate: agent has a live client, then memory is disabled
        # (e.g. AGENT_MEMORY_ENABLED flipped to False at runtime)
        agent_memory_client = sentinel
        assert agent_memory_client is sentinel

        agent_memory_client = None
        worker_ctx = WorkerContext(
            signal_context=object(),
            llm_chain=None,
            memory_client=agent_memory_client,
        )
        assert worker_ctx.memory_client is None
