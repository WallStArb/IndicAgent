"""AgentDependencies: Ring 0 typed dependency container for AI workers.

Replaces loose constructor kwargs (llm_chain=, pool=, settings=) with a unified
typed container. Ring 0 must not import Ring 1 at runtime — all domain imports are
under TYPE_CHECKING.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.config.settings import Settings
    from src.core.llm.chain import LLMProviderChain


@dataclass
class AgentDependencies:
    """Typed dependency container for BaseAIWorker subclasses.

    All AI agents receive their runtime dependencies through this container
    rather than loose constructor kwargs. This enables mypy to catch
    wrong-dep access at type-check time and provides a uniform construction
    path for AgentRegistry.build.

    Ring 0: No runtime imports from Ring 1. All domain types are imported
    only for type checking via TYPE_CHECKING.
    """

    llm_chain: LLMProviderChain | None
    """The LLM chain for text generation. Required by LLM agents, None for ML-only agents."""

    pool: Any | None
    """The database connection pool. Required by ML agents, None for LLM-only agents."""

    settings: Settings | None
    """The global settings object. Optional — tests may pass None."""

    # Phase 097 extension point: memory_client: ZepMemoryClient | None = None
