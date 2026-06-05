"""
Mem0BackendImpl — Tier 4 (narrative) and Tier 7 (annotation) memory backend.

Uses the Mem0 SDK as a pure pgvector store with structured metadata.
LLM-based fact extraction is DISABLED: enable_graph=False, no LLM calls.
All content is stored verbatim — no deduplication or extraction.

Embedding model: nomic-embed-text via Ollama (768-dim, same as custom tables — D-06).
Vector store: pgvector against same TimescaleDB instance, mem0_memories collection (D-18).

Async contract: the Mem0 SDK is synchronous. All calls are wrapped in
asyncio.to_thread() so the event loop is never blocked (D-13).

Graceful degradation: if mem0ai is not installed, the backend degrades to a no-op
returning [] — the rest of the system functions without Mem0. Log once at construction.

Valid tiers: 'narrative' (tier 4) and 'annotation' (tier 7) only (D-14).
Search returns [] for any other tier, on SDK error, or on timeout (D-19).

Phase: 097 (agent-memory)
Ring 0 — no Ring 1 imports.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from src.config.settings import Settings

log = structlog.get_logger(__name__)

# Tiers handled by Mem0 (D-14).
_VALID_TIERS: frozenset[str] = frozenset({"narrative", "annotation"})


class Mem0BackendImpl:
    """Mem0-backed memory for tiers 4 (narrative) and 7 (annotation).

    Implements the Mem0Backend Protocol.

    Lazy-initializes the synchronous Mem0 Memory client on first use so that:
    - Unit tests without mem0ai installed can import this module without error.
    - The client is created only when the memory subsystem is actually used.

    All public methods are async and wrap SDK calls in asyncio.to_thread().
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any | None = None  # lazy-initialized on first search()
        self._unavailable: bool = False  # set True when mem0ai missing or init fails

        # Build MEM0_CONFIG (D-18 / design Section 8) — used lazily in _get_client().
        self._config: dict[str, Any] = {
            "vector_store": {
                "provider": "pgvector",
                "config": {
                    "host": "localhost",
                    "port": 5432,
                    "dbname": "indicagent",
                    "user": "postgres",
                    "password": "postgres",
                    "collection_name": "mem0_memories",
                    "embedding_model_dims": 768,
                },
            },
            "embedder": {
                "provider": "ollama",
                "config": {
                    "model": "nomic-embed-text",
                    "ollama_base_url": settings.ollama_base_url,
                    "embedding_dims": 768,
                },
            },
            # No graph store — Neo4j dependency rejected (D-18).
            "graph_store": None,
            # Disable LLM-based fact extraction and graph building entirely.
            # Mem0 is used as a pure pgvector store with structured metadata only.
            "llm": None,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client(self) -> Any | None:
        """Lazily initialize the synchronous Mem0 Memory client.

        Returns None (and sets self._unavailable=True) if mem0ai is not
        installed or initialization fails.

        Called from asyncio.to_thread() so it is safe to block here.
        """
        if self._client is not None:
            return self._client
        if self._unavailable:
            return None

        try:
            from mem0 import Memory  # noqa: PLC0415 — guarded import (mem0ai optional)

            self._client = Memory.from_config(self._config)
        except ImportError:
            log.warning(
                "mem0.unavailable",
                reason="mem0ai not installed; Mem0Backend degraded to no-op",
            )
            self._unavailable = True
            return None
        except Exception as error:
            log.warning(
                "mem0.init_failed",
                error=str(error),
            )
            self._unavailable = True
            return None

        return self._client

    def _search_sync(
        self,
        query: str,
        tier: str,
        symbol: str,
        timeframe: str,
        limit: int,
    ) -> list[dict]:
        """Synchronous Mem0 search — called from asyncio.to_thread()."""
        client = self._get_client()
        if client is None:
            return []

        try:
            results = client.search(
                query=query,
                limit=limit,
                filters={
                    "tier": tier,
                    "symbol": symbol,
                    "timeframe": timeframe,
                },
            )
            # Mem0 returns a list of dicts; unwrap if wrapped in a container.
            if isinstance(results, dict) and "results" in results:
                return list(results["results"])
            if isinstance(results, list):
                return results
            return []
        except Exception as error:
            log.warning("mem0.search_failed", tier=tier, symbol=symbol, error=str(error))
            return []

    # ------------------------------------------------------------------
    # Protocol implementation
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        tier: str,
        symbol: str,
        timeframe: str,
        limit: int,
    ) -> list[dict]:
        """Search Mem0 for qualitative memories matching a natural-language query.

        Only tiers 'narrative' (4) and 'annotation' (7) are valid (D-14).
        Returns [] for any other tier, on SDK error, or on timeout. Never raises.

        Args:
            query: Natural-language search query.
            tier: Memory tier string -- must be 'narrative' or 'annotation'.
            symbol: Instrument symbol -- scoped via Mem0 metadata filter.
            timeframe: Bar timeframe -- scoped via Mem0 metadata filter.
            limit: Max results to return.

        Returns:
            List of Mem0 memory dicts. Returns [] on any error. Never raises.
        """
        if tier not in _VALID_TIERS:
            log.warning("mem0.invalid_tier", tier=tier, valid=list(_VALID_TIERS))
            return []

        try:
            results: list[dict] = await asyncio.to_thread(
                self._search_sync, query, tier, symbol, timeframe, limit
            )
            return results
        except Exception as error:
            log.warning("mem0.search_error", tier=tier, symbol=symbol, error=str(error))
            return []
