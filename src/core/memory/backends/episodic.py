"""
PgvectorEpisodicBackend — Tier-1 episodic recall from memory_episodes_labeled.

Implements the EpisodicBackend Protocol with:
- HNSW ef_search=100 set per-session via SET LOCAL (D-11)
- Over-fetch limit * over_fetch_multiplier then epoch-weighted Python rerank (D-23)
- Cohort filter on (agent_id, symbol, hmm_regime, entry_type) for MEM-02 scoping
- 40ms asyncio.wait_for hard timeout; returns [] on any error, never raises (D-13/D-19)

Ring 0: no Ring 1 imports. Episode is imported from src.core.memory.types.

Phase: 097 (agent-memory)
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

import asyncpg
import structlog

from src.core.memory.types import Episode

if TYPE_CHECKING:
    pass  # keep TYPE_CHECKING block for future use

log = structlog.get_logger(__name__)

_DEFAULT_EPOCH_DECAY = 0.3
_DEFAULT_OVER_FETCH_MULTIPLIER = 3
_DEFAULT_EF_SEARCH = 100
_DEFAULT_TIMEOUT_MS = 40


class PgvectorEpisodicBackend:
    """EpisodicBackend implementation against memory_episodes_labeled via HNSW.

    Constructor Args:
        pool: asyncpg connection pool to the TimescaleDB instance.
        epoch_decay: Multiplicative weight per epoch delta (default 0.3).
            Episodes from the current epoch get weight 1.0; prior epoch
            episodes get weight epoch_decay^delta. (D-19/D-23)
        over_fetch_multiplier: HNSW over-fetch factor. Fetches
            limit * over_fetch_multiplier results then reranks in Python. (D-23)
        ef_search: hnsw.ef_search parameter set per query session. (D-11)
        timeout_ms: Hard asyncio.wait_for timeout in milliseconds. (D-13)
        current_epoch_provider: Optional callable returning the live regime
            epoch. Not used by recall() — caller always passes regime_epoch
            directly from memory_system_state. Exposed for completeness.
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        epoch_decay: float = _DEFAULT_EPOCH_DECAY,
        over_fetch_multiplier: int = _DEFAULT_OVER_FETCH_MULTIPLIER,
        ef_search: int = _DEFAULT_EF_SEARCH,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
        current_epoch_provider: Callable[[], int] | None = None,
    ) -> None:
        self._pool = pool
        self._epoch_decay = epoch_decay
        self._over_fetch = over_fetch_multiplier
        self._ef_search = ef_search
        self._timeout_ms = timeout_ms
        self._current_epoch_provider = current_epoch_provider

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
        """Recall episodically similar memories scoped by cohort (MEM-01, MEM-02).

        Executes within asyncio.wait_for(timeout_ms). Returns [] on timeout,
        connection error, or any unexpected exception — never raises (D-19).

        Args:
            embedding: 768-dim query vector (nomic-embed-text output).
            agent_id: Calling agent — filters to agent-specific episodes.
            symbol: Instrument symbol filter.
            hmm_regime: Current HMM regime — filters to matching episodes.
            entry_type: Entry type filter.
            regime_epoch: Current epoch from memory_system_state — used for
                epoch-decay weighting during Python rerank (D-23).
            limit: Max episodes to return after rerank.

        Returns:
            Up to `limit` Episode objects, sorted by similarity * epoch_weight
            descending. Empty list on timeout or any exception.
        """
        try:
            return await asyncio.wait_for(
                self._recall_inner(
                    embedding, agent_id, symbol, hmm_regime, entry_type, regime_epoch, limit
                ),
                timeout=self._timeout_ms / 1000.0,
            )
        except TimeoutError:
            log.warning(
                "episodic_recall_timeout",
                agent_id=agent_id,
                symbol=symbol,
                hmm_regime=hmm_regime,
                timeout_ms=self._timeout_ms,
            )
            return []
        except Exception as error:
            log.warning(
                "episodic_recall_error",
                agent_id=agent_id,
                symbol=symbol,
                error=str(error),
                error_type=type(error).__name__,
            )
            return []

    async def _recall_inner(
        self,
        embedding: list[float],
        agent_id: str,
        symbol: str,
        hmm_regime: str,
        entry_type: str,
        regime_epoch: int,
        limit: int,
    ) -> list[Episode]:
        """Core recall logic — runs inside the wait_for wrapper."""
        fetch_limit = limit * self._over_fetch

        # Build the vector literal for asyncpg. asyncpg sends list[float] as text
        # so we must append ::vector cast for pgvector to parse it.
        vector_literal = "[" + ",".join(str(v) for v in embedding) + "]"

        # Cohort filter (MEM-02): all four cohort dimensions when provided.
        # All four are non-nullable strings so we always filter on them.
        sql = """
            SELECT
                id,
                ts,
                kind,
                signal_id,
                symbol,
                timeframe,
                agent_id,
                hmm_regime,
                vol_regime,
                entry_type,
                regime_epoch,
                outcome,
                pnl_r,
                mae,
                mfe,
                bars_in_trade,
                memory_assisted,
                payload,
                1.0 - (embedding <=> $1::vector) AS similarity
            FROM memory_episodes_labeled
            WHERE agent_id = $2
              AND symbol   = $3
              AND hmm_regime = $4
              AND entry_type = $5
            ORDER BY embedding <=> $1::vector
            LIMIT $6
        """

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # D-11: set ef_search on this transaction — SET LOCAL scopes
                # to the transaction only and does not leak into the pool.
                await conn.execute(f"SET LOCAL hnsw.ef_search = {self._ef_search}")

                rows = await conn.fetch(
                    sql,
                    vector_literal,
                    agent_id,
                    symbol,
                    hmm_regime,
                    entry_type,
                    fetch_limit,
                )

        # Python-side epoch-weighted rerank (D-23).
        # epoch_weight = 1.0 for current epoch, epoch_decay^delta for prior epochs.
        scored: list[tuple[float, asyncpg.Record]] = []
        for row in rows:
            row_epoch: int = row["regime_epoch"]
            delta = max(0, regime_epoch - row_epoch)
            epoch_weight = 1.0 if delta == 0 else (self._epoch_decay**delta)
            score = row["similarity"] * epoch_weight
            scored.append((score, row))

        # Sort descending by weighted score, take top limit.
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:limit]

        return [self._row_to_episode(score, row) for score, row in top]

    @staticmethod
    def _row_to_episode(weighted_score: float, row: asyncpg.Record) -> Episode:
        """Map a DB row to an Episode frozen dataclass.

        UUIDs are stringified (asyncpg returns uuid.UUID objects; Kafka payload
        convention requires str). JSONB payload is passed as dict directly —
        asyncpg returns dict for JSONB; no json.loads() needed.
        """
        regime_epoch: int = row["regime_epoch"]
        similarity: float = row["similarity"]
        # Compute epoch_weight independently from the weighted_score so the
        # agent can inspect it directly. (weighted_score = similarity * epoch_weight)
        epoch_weight = weighted_score / similarity if similarity > 0 else 0.0

        return Episode(
            id=str(row["id"]),
            ts=row["ts"],
            kind=str(row["kind"]),
            signal_id=str(row["signal_id"]),
            symbol=row["symbol"],
            timeframe=row["timeframe"],
            agent_id=row["agent_id"] or "",
            hmm_regime=row["hmm_regime"] or "",
            vol_regime=row["vol_regime"] or "",
            entry_type=row["entry_type"] or "",
            regime_epoch=regime_epoch,
            outcome=row["outcome"],
            pnl_r=row["pnl_r"],
            mae=row["mae"],
            mfe=row["mfe"],
            bars_in_trade=row["bars_in_trade"],
            memory_assisted=row["memory_assisted"],
            payload=dict(row["payload"]) if row["payload"] else {},
            similarity=similarity,
            epoch_weight=epoch_weight,
        )
