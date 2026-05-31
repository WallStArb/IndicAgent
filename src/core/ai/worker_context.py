"""WorkerContext — immutable per-run dependency container for _run_typed()."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.llm.chain import LLMProviderChain  # ring0-ok: TYPE_CHECKING only, not at runtime


@dataclass(frozen=True)
class WorkerContext:
    """Immutable dependency container passed into _run_typed() and the LLMAdapter bridge.

    Never serialized — in-memory only. Constructed once per _run_typed() invocation
    and passed down to the FunctionModel bridge without coupling it to BaseAIWorker.

    Fields:
        signal_context: Typed Any because Ring 0 must not reference Ring 1 SignalContext
            at runtime. Callers pass a concrete SignalContext; Ring 0 code treats it as Any.
        llm_chain: The active LLMProviderChain for this run. String annotation keeps the
            import TYPE_CHECKING-only (mirrors base_agent.py precedent).
        db_pool: Reserved for Phase 097 Zep memory integration. Defaults to None.
        memory_client: Reserved for Phase 097 Zep memory integration. Defaults to None.
    """

    signal_context: Any
    llm_chain: LLMProviderChain
    db_pool: Any | None = None
    memory_client: Any | None = None
