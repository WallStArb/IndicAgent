"""
MemoryClient — read-only facade over the four memory backends.

Composes EpisodicBackend, CalibrationBackend, RegimeBackend, and Mem0Backend
behind a uniform async API. Agents receive this client via WorkerContext.memory_client
(MEM-01). All methods return typed value objects or [] / None on error (D-19).

OTel instrumentation (MEM-04):
    memory_recall_latency_ms  — p95 measurable end-to-end recall latency
    memory_recall_results_total — hit / miss / timeout counts
    memory_calibration_applied  — calibration applied with stable label

Design decisions:
    D-19: read-only; NO write methods; MemoryEpisodeWriter is a separate class
    D-13: 40ms timeout per method (backends already gate; client records timeouts)
    D-11: ef_search=100 is enforced by EpisodicBackend, not here
    D-23: epoch-weighted rerank is in EpisodicBackend, not here
    F3 cold-start: calibration() returns partial CalibrationStats when sample_n > 0
                   but promoted row absent; returns None only when sample_n == 0

Phase: 097 (agent-memory)
Ring 0 — no Ring 1 imports.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import structlog

from src.observability.metrics import (
    MEMORY_CALIBRATION_APPLIED,
    MEMORY_RECALL_LATENCY_MS,
    MEMORY_RECALL_RESULTS_TOTAL,
)

if TYPE_CHECKING:
    from src.core.memory.backends import (
        CalibrationBackend,
        EpisodicBackend,
        Mem0Backend,
        RegimeBackend,
    )
    from src.core.memory.embedding import EmbeddingService
    from src.core.memory.types import CalibrationStats, Episode, RegimeHistory

log = structlog.get_logger(__name__)

# Default annotation recall limit (plan spec: 10)
_DEFAULT_ANNOTATION_LIMIT = 10


class MemoryClient:
    """Read-only facade over the four memory backends.

    Constructed once per service via MemoryClientFactory (behind AGENT_MEMORY_ENABLED).
    Passed into WorkerContext.memory_client at compute time.

    All methods:
    - Return typed value objects or [] / None on any error, timeout, or misconfiguration
    - Never raise — graceful degradation is structural (D-19)
    - Record OTel metrics for latency and outcome tracking
    """

    def __init__(
        self,
        episodic: EpisodicBackend,
        calibration: CalibrationBackend,
        regime: RegimeBackend,
        mem0: Mem0Backend,
        embedding: EmbeddingService,
        recall_limit: int = 10,
        embed_timeout_ms: int = 30,
    ) -> None:
        self._episodic = episodic
        self._calibration = calibration
        self._regime = regime
        self._mem0 = mem0
        self._embedding = embedding
        self._recall_limit = recall_limit
        self._embed_timeout_ms = embed_timeout_ms

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def recall(
        self,
        context: Any,
        agent_id: str,
        limit: int | None = None,
    ) -> list[Episode]:
        """Recall the top episodically similar memories for a given SignalContext.

        Embeds `context`, extracts cohort keys (symbol, hmm_regime, entry_type,
        regime_epoch), delegates to EpisodicBackend, and records MEM-04 metrics.

        Latency budget (MEM-04 / D-13):
            The embed step is bounded by self._embed_timeout_ms (default 30ms) via
            asyncio.wait_for. The HNSW+rerank step uses the backend's own 40ms timeout
            (config timeout_ms). Total recall budget = embed_timeout (30ms) + backend
            timeout (40ms). p95 is measured empirically in memory_recall_benchmark.py.
            On embed timeout: returns [], records timeout counter, never raises.

        Args:
            context: Duck-typed SignalContext (Ring 0 cannot import Ring 1 types).
            agent_id: Calling agent ID.
            limit: Max episodes to return. Defaults to self._recall_limit.

        Returns:
            Up to `limit` Episode objects sorted by epoch-weighted similarity.
            Returns [] on embedding failure, timeout, or any error. Never raises.
        """
        effective_limit = limit if limit is not None else self._recall_limit
        t0 = time.monotonic()

        symbol = str(getattr(context, "symbol", "") or "")

        try:
            # Embed the context — bounded by embed_timeout_ms to cap its latency
            # contribution. Query context is new per bar; precomputation is not viable.
            try:
                embedding_vector, _embedding_text = await asyncio.wait_for(
                    self._embedding.embed_context(context),
                    timeout=self._embed_timeout_ms / 1000.0,
                )
            except TimeoutError:
                elapsed_ms = (time.monotonic() - t0) * 1000.0
                MEMORY_RECALL_LATENCY_MS.record(elapsed_ms, {"tier": "1", "symbol": symbol})
                MEMORY_RECALL_RESULTS_TOTAL.add(1, {"tier": "1", "result": "timeout"})
                log.warning(
                    "memory_client.embed_timeout",
                    agent_id=agent_id,
                    embed_timeout_ms=self._embed_timeout_ms,
                )
                return []

            if embedding_vector is None:
                # Embedding failed — record miss and return empty
                MEMORY_RECALL_RESULTS_TOTAL.add(1, {"tier": "1", "result": "miss"})
                return []

            # Extract cohort keys from duck-typed context (D-22 / Ring 0 duck-typing)
            hmm_regime = str(getattr(context, "hmm_regime", "") or "")
            entry_type = str(getattr(context, "entry_type", "") or "")
            regime_epoch = int(getattr(context, "regime_epoch", 1) or 1)

            results: list[Episode] = await self._episodic.recall(
                embedding=embedding_vector,
                agent_id=agent_id,
                symbol=symbol,
                hmm_regime=hmm_regime,
                entry_type=entry_type,
                regime_epoch=regime_epoch,
                limit=effective_limit,
            )

            elapsed_ms = (time.monotonic() - t0) * 1000.0
            MEMORY_RECALL_LATENCY_MS.record(elapsed_ms, {"tier": "1", "symbol": symbol})

            if results:
                MEMORY_RECALL_RESULTS_TOTAL.add(1, {"tier": "1", "result": "hit"})
            else:
                MEMORY_RECALL_RESULTS_TOTAL.add(1, {"tier": "1", "result": "miss"})

            return results

        except Exception as error:
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            MEMORY_RECALL_LATENCY_MS.record(elapsed_ms, {"tier": "1", "symbol": symbol})
            # Distinguish timeout from generic error — both recorded as timeout for
            # downstream alerting purposes (MEM-04 timeout counter).
            MEMORY_RECALL_RESULTS_TOTAL.add(1, {"tier": "1", "result": "timeout"})
            log.warning("memory_client.recall_failed", agent_id=agent_id, error=str(error))
            return []

    async def calibration(
        self,
        agent_id: str,
        symbol: str,
        hmm_regime: str,
        entry_type: str,
        regime_epoch: int,
    ) -> CalibrationStats | None:
        """Retrieve outcome-driven calibration stats for an agent/cohort.

        Cold-start path (F3): when no promoted row exists (get_calibration returns None),
        checks raw labeled episode count via get_partial_sample_n(). If sample_n > 0,
        returns a partial CalibrationStats(bootstrapped=False) so agents know data is
        accumulating. Returns None only when sample_n == 0 (no data at all).

        When a promoted row is returned, increments MEMORY_CALIBRATION_APPLIED with
        stable label for downstream Grafana alerting.

        Args:
            agent_id: Agent requesting calibration.
            symbol: Instrument symbol.
            hmm_regime: HMM regime label.
            entry_type: Entry type.
            regime_epoch: Current regime epoch.

        Returns:
            CalibrationStats if promoted row exists (bootstrapped=True), partial
            CalibrationStats if data accumulating (bootstrapped=False), or None
            when no data exists. Never raises.
        """
        try:
            stats: CalibrationStats | None = await self._calibration.get_calibration(
                agent_id=agent_id,
                symbol=symbol,
                hmm_regime=hmm_regime,
                entry_type=entry_type,
                regime_epoch=regime_epoch,
            )

            if stats is not None:
                # Promoted row found — record metric and return
                MEMORY_CALIBRATION_APPLIED.add(
                    1,
                    {
                        "agent_id": agent_id,
                        "stable": str(stats.correction_factor_stable).lower(),
                    },
                )
                return stats

            # No promoted row — check partial sample count (D-F3 cold-start path)
            sample_n: int = await self._calibration.get_partial_sample_n(
                agent_id=agent_id,
                symbol=symbol,
                hmm_regime=hmm_regime,
                entry_type=entry_type,
                regime_epoch=regime_epoch,
            )

            if sample_n == 0:
                return None  # No data at all

            # Data exists but below N>=30 promotion gate — return partial CalibrationStats
            from src.core.memory.types import CalibrationStats as _CalibrationStats  # noqa: PLC0415

            return _CalibrationStats(
                agent_id=agent_id,
                symbol=symbol,
                hmm_regime=hmm_regime,
                entry_type=entry_type,
                regime_epoch=regime_epoch,
                sample_n=sample_n,
                mean_prediction=0.0,
                actual_rate=0.0,
                calibration_error=0.0,
                calibration_error_variance=0.0,
                correction_factor=None,
                correction_factor_stable=False,
                bootstrapped=False,
                skill_score=0.0,
                information_coefficient=0.0,
                ic_p_value=1.0,
                brier_score=0.0,
                base_rate=0.0,
                ci_lower=0.0,
                ci_upper=0.0,
                p_value_corrected=1.0,
                p_signal=None,
                feedback_loop_quarantine=False,
                quarantine_review_at=None,
                promoted_at=None,
                window_start=None,
                window_end=None,
            )

        except Exception as error:
            log.warning(
                "memory_client.calibration_failed",
                agent_id=agent_id,
                symbol=symbol,
                error=str(error),
            )
            return None

    async def recall_regime_history(
        self,
        symbol: str,
        timeframe: str,
    ) -> RegimeHistory | None:
        """Retrieve regime duration and Markov transition priors.

        Delegates to RegimeBackend. Records MEMORY_RECALL_LATENCY_MS with tier "5".

        Args:
            symbol: Instrument symbol.
            timeframe: Bar timeframe string.

        Returns:
            RegimeHistory for the current open regime period, or None when no
            open period exists, on timeout, or any error. Never raises.
        """
        t0 = time.monotonic()
        try:
            result: RegimeHistory | None = await self._regime.get_regime_history(
                symbol=symbol,
                timeframe=timeframe,
            )
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            MEMORY_RECALL_LATENCY_MS.record(elapsed_ms, {"tier": "5", "symbol": symbol})
            return result
        except Exception as error:
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            MEMORY_RECALL_LATENCY_MS.record(elapsed_ms, {"tier": "5", "symbol": symbol})
            log.warning(
                "memory_client.regime_history_failed",
                symbol=symbol,
                timeframe=timeframe,
                error=str(error),
            )
            return None

    async def recall_annotations(
        self,
        symbol: str,
        timeframe: str,
        limit: int = _DEFAULT_ANNOTATION_LIMIT,
    ) -> list[dict]:
        """Retrieve operator annotations (tier 7) from Mem0.

        Args:
            symbol: Instrument symbol.
            timeframe: Bar timeframe string.
            limit: Max results to return.

        Returns:
            List of Mem0 annotation dicts. Returns [] on any error. Never raises.
        """
        try:
            return await self._mem0.search(
                query=f"{symbol} {timeframe} operator annotation",
                tier="annotation",
                symbol=symbol,
                timeframe=timeframe,
                limit=limit,
            )
        except Exception as error:
            log.warning(
                "memory_client.annotations_failed",
                symbol=symbol,
                timeframe=timeframe,
                error=str(error),
            )
            return []
