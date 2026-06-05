"""
Backend Protocols for the memory subsystem — Ring 0 contract layer.

Four runtime-checkable Protocols define the interface each backend must satisfy.
Implementations live in Wave 2 (Plans 03-04). MemoryClient composes them.

Graceful degradation contract (D-19):
    Every method returns [] or None on timeout, connection error, or any
    unexpected exception. Backends NEVER raise — the live signal pipeline
    must be shielded from memory subsystem failures at all times.

All methods are async. Mem0Backend wraps the synchronous SDK in
asyncio.to_thread() at the implementation layer (D-13).

Phase: 097 (agent-memory)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from src.core.memory.types import CalibrationStats, Episode, RegimeHistory


@runtime_checkable
class EpisodicBackend(Protocol):
    """Backend for episodic recall from memory_episodes_labeled via HNSW.

    Over-fetch contract (D-23): implementations fetch limit * over_fetch_multiplier
    results by cosine similarity, apply epoch-decay weights in Python, then return
    the top limit after rerank. The over-fetch is intentional — HNSW does not
    natively support weighted distance.
    """

    async def recall(
        self,
        embedding: list[float],
        agent_id: str,
        symbol: str,
        hmm_regime: str,
        entry_type: str,
        regime_epoch: int,
        limit: int,
    ) -> list[Episode]:
        """Recall the top-limit episodically similar memories for a given context.

        Args:
            embedding: Query embedding vector (768-dim nomic-embed-text).
            agent_id: Calling agent ID — filters to agent-specific episodes.
            symbol: Instrument symbol filter.
            hmm_regime: Current HMM regime — filters to matching episodes.
            entry_type: Signal entry type filter.
            regime_epoch: Current epoch from memory_system_state — used for
                epoch-decay weighting during Python-side rerank.
            limit: Max episodes to return after epoch-weighted rerank.

        Returns:
            Up to `limit` Episode objects sorted by epoch-weighted similarity,
            descending. Returns [] on timeout, connection error, or any exception.
            Never raises.
        """
        ...  # pragma: no cover


@runtime_checkable
class CalibrationBackend(Protocol):
    """Backend for outcome-driven calibration stats from memory_calibration_promoted.

    Reads from the promoted table only — agents never see raw or partial rows.
    Partial sample counts (below N=30) are surfaced via get_partial_sample_n()
    for the cold-start path (D-F3).
    """

    async def get_calibration(
        self,
        agent_id: str,
        symbol: str,
        hmm_regime: str,
        entry_type: str,
        regime_epoch: int,
    ) -> CalibrationStats | None:
        """Retrieve promoted calibration stats for an agent/cohort combination.

        Args:
            agent_id: Agent ID to look up.
            symbol: Instrument symbol.
            hmm_regime: HMM regime label.
            entry_type: Entry type.
            regime_epoch: Current epoch — may fall back to prior epochs when
                current-epoch row is absent (cold start).

        Returns:
            CalibrationStats if a promoted row exists (sample_n >= 30 guaranteed
            by DB CHECK constraint). None if no promoted row exists for this
            cohort, on timeout, or on any exception. Never raises.
        """
        ...  # pragma: no cover

    async def get_partial_sample_n(
        self,
        agent_id: str,
        symbol: str,
        hmm_regime: str,
        entry_type: str,
        regime_epoch: int,
    ) -> int:
        """Count labeled episodes for a cohort that are below the N>=30 gate.

        Used by MemoryClient on the cold-start path (D-F3): if partial_n > 0 but
        a promoted row does not yet exist, agents know calibration is accumulating.

        Args:
            agent_id: Agent ID to look up.
            symbol: Instrument symbol.
            hmm_regime: HMM regime label.
            entry_type: Entry type.
            regime_epoch: Epoch to query.

        Returns:
            Count of labeled episodes for this cohort (may be 0). Returns 0 on
            timeout or any exception. Never raises.
        """
        ...  # pragma: no cover


@runtime_checkable
class RegimeBackend(Protocol):
    """Backend for regime transition priors from memory_regime_transitions.

    Provides Markov transition probabilities and duration statistics for
    the current regime (tier 5 — schema-only in Phase 097, live in Phase 098+).
    """

    async def get_regime_history(
        self,
        symbol: str,
        timeframe: str,
    ) -> RegimeHistory | None:
        """Retrieve regime duration and Markov transition priors.

        Args:
            symbol: Instrument symbol.
            timeframe: Bar timeframe string (e.g. '5m', '15m').

        Returns:
            RegimeHistory for the currently open regime period. None when no
            open period exists, on timeout, or on any exception. Never raises.

            Note: transition_probs and win_rate will be None when their
            respective sample counts are below the N>=30 gate (C-03).
        """
        ...  # pragma: no cover


@runtime_checkable
class Mem0Backend(Protocol):
    """Backend for Mem0-managed qualitative memory (tiers 4 and 7 only).

    Tiers 4 (narrative continuity) and 7 (operator annotations) use Mem0's
    LLM-based fact extraction. All other tiers use custom pgvector (D-14).
    Implementations wrap the synchronous Mem0 SDK in asyncio.to_thread() (D-13).
    """

    async def search(
        self,
        query: str,
        tier: str,
        symbol: str,
        timeframe: str,
        limit: int,
    ) -> list[dict]:
        """Search Mem0 for qualitative memories matching a natural-language query.

        Args:
            query: Natural-language search query (e.g. narrative text snippet).
            tier: Memory tier string ('narrative' or 'annotation').
            symbol: Instrument symbol — scoped via Mem0 metadata filter.
            timeframe: Bar timeframe — scoped via Mem0 metadata filter.
            limit: Max results to return.

        Returns:
            List of Mem0 memory dicts (raw Mem0 response items). Returns [] on
            timeout, SDK error, or any exception. Never raises.
        """
        ...  # pragma: no cover
