"""FeatureRegistryService — DB-backed feature lifecycle governance.

Singleton service that loads all feature_registry rows at daemon startup and
provides read access throughout execution. Both the IC engine (psycopg2, sync)
and ensemble trainer (asyncpg, async) use this service.

Row count gate:
    load() and load_sync() raise RuntimeError if the DB row count (all statuses)
    does not equal 61 (the number of FeatureVector dataclass fields). This is a
    drift guard — the registry must always reflect the full FeatureVector schema.

Alignment gate (caller responsibility):
    Callers (ic_engine, ensemble_trainer) must compare get_all_features() against
    dataclasses.fields(FeatureVector) to detect name drift. They must use
    get_all_features() — NOT get_active_features() — because the alignment gate
    checks schema completeness, not lifecycle state.

Transition logging:
    record_transition() is a synchronous wrapper that schedules
    _write_transition_record() as a background asyncio task (fire-and-forget).
    Only ensemble_trainer calls record_transition() — ic_engine only reads
    registry status via get_status().
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import UTC, datetime
from typing import Any

import asyncpg
import structlog

from src.intelligence.schemas import FeatureVector

_logger = structlog.get_logger()

# Derived, not hardcoded: a fixed count (152, then 150 after the
# new_high_flag/new_low_flag removal 2026-07-09) is exactly the class of bug
# feature_vector_persistence.py's own docstring warns about -- a number that
# silently drifts out of sync with FeatureVector the next time a field is
# added or removed. Deriving it here makes drift structurally impossible.
_REGISTRY_ROW_COUNT = len(dataclasses.fields(FeatureVector))

_LOAD_QUERY = """
    SELECT feature_name, group_name, tier, status,
           min_ic_sharpe, min_ic_n, fdr_required, fdr_alpha
    FROM feature_registry
"""

_APR_SHARPE_DEFAULT_KEY = "alpha.feature_registry.min_ic_sharpe_default"
_APR_SHARPE_DEFAULT_FALLBACK = 0.5


class FeatureRegistryService:
    """Singleton service for feature_registry reads and lifecycle transitions.

    Load at daemon startup before running the alignment gate. Not thread-safe —
    load once per process, then treat as read-only.
    """

    def __init__(self) -> None:
        self._features: dict[str, dict[str, Any]] = {}
        self._loaded: bool = False
        self._pool: asyncpg.Pool | None = None
        self._min_ic_sharpe_default: float = _APR_SHARPE_DEFAULT_FALLBACK

    # ------------------------------------------------------------------
    # Load methods
    # ------------------------------------------------------------------

    async def load(self, pool: asyncpg.Pool) -> None:
        """Load all feature_registry rows via asyncpg pool.

        Populates the in-memory cache keyed by feature_name.
        Loads the APR global IC Sharpe floor from config_state.
        Raises RuntimeError if row count != 61.

        Row count gate checks total DB rows regardless of status. Alignment gate
        in callers must use get_all_features(), not get_active_features(), to
        match the FeatureVector dataclass regardless of lifecycle state.
        """
        self._pool = pool
        async with pool.acquire() as conn:
            rows = await conn.fetch(_LOAD_QUERY)
            sharpe_default_val = await conn.fetchval(
                "SELECT config_value FROM config_state WHERE config_key = $1",
                _APR_SHARPE_DEFAULT_KEY,
            )

        if len(rows) != _REGISTRY_ROW_COUNT:
            raise RuntimeError(
                f"feature_registry row count mismatch: expected {_REGISTRY_ROW_COUNT}, "
                f"got {len(rows)}. Run migration to sync registry with FeatureVector."
            )

        self._features = {r["feature_name"]: dict(r) for r in rows}
        if sharpe_default_val is not None:
            self._min_ic_sharpe_default = float(sharpe_default_val)
        self._loaded = True
        _logger.info(
            "feature_registry_service.loaded",
            n_features=len(self._features),
            min_ic_sharpe_default=self._min_ic_sharpe_default,
        )

    def load_sync(self, conn: Any) -> None:
        """Load all feature_registry rows via psycopg2 connection.

        Same semantics as load() but uses the cursor/fetchall psycopg2 pattern.
        Required by ic_engine.py which uses psycopg2 throughout.
        Raises RuntimeError if row count != 61.

        Row count gate checks total DB rows regardless of status. Alignment gate
        in callers must use get_all_features(), not get_active_features().
        """
        with conn.cursor() as cur:
            cur.execute(_LOAD_QUERY)
            rows = cur.fetchall()
            col_names = [desc[0] for desc in cur.description]

        with conn.cursor() as cur:
            cur.execute(
                "SELECT config_value FROM config_state WHERE config_key = %s",
                (_APR_SHARPE_DEFAULT_KEY,),
            )
            apr_row = cur.fetchone()

        if len(rows) != _REGISTRY_ROW_COUNT:
            raise RuntimeError(
                f"feature_registry row count mismatch: expected {_REGISTRY_ROW_COUNT}, "
                f"got {len(rows)}. Run migration to sync registry with FeatureVector."
            )

        self._features = {row[0]: dict(zip(col_names, row)) for row in rows}
        if apr_row is not None:
            self._min_ic_sharpe_default = float(apr_row[0])
        self._loaded = True
        _logger.info(
            "feature_registry_service.loaded_sync",
            n_features=len(self._features),
            min_ic_sharpe_default=self._min_ic_sharpe_default,
        )

    # ------------------------------------------------------------------
    # Read accessors
    # ------------------------------------------------------------------

    def get_active_features(self, tier: str | None = None) -> list[dict[str, Any]]:
        """Return all non-deprecated features, optionally filtered by tier.

        NOTE: Do NOT use this method for the startup alignment gate — it filters
        by status, which would cause the gate to fail when features are deprecated
        (correct lifecycle behavior). Use get_all_features() for the alignment gate.

        Raises RuntimeError if not loaded.
        """
        if not self._loaded:
            raise RuntimeError("FeatureRegistryService not loaded — call load() first.")
        result = [f for f in self._features.values() if f["status"] != "deprecated"]
        if tier is not None:
            result = [f for f in result if f["tier"] == tier]
        return result

    def get_all_features(self, tier: str | None = None) -> list[dict[str, Any]]:
        """Return ALL features regardless of status.

        This is the correct method for the startup alignment gate. The gate
        compares registry names to FeatureVector dataclass fields — it must pass
        even when some features have status='deprecated', because a deprecated
        feature still has a row in feature_registry AND a field in FeatureVector.

        If tier is not None, filters by tier.
        Raises RuntimeError if not loaded.
        """
        if not self._loaded:
            raise RuntimeError("FeatureRegistryService not loaded — call load() first.")
        result = list(self._features.values())
        if tier is not None:
            result = [f for f in result if f["tier"] == tier]
        return result

    def get_feature(self, feature_name: str) -> dict[str, Any] | None:
        """Return the feature dict for a given feature_name, or None if not found."""
        if not self._loaded:
            raise RuntimeError("FeatureRegistryService not loaded — call load() first.")
        return self._features.get(feature_name)

    def get_ic_sharpe_gate(self, feature_name: str) -> float:
        """Return the IC Sharpe gate for a feature.

        Returns feature['min_ic_sharpe'] if it is not None, else the global APR
        floor (alpha.feature_registry.min_ic_sharpe_default).
        """
        if not self._loaded:
            raise RuntimeError("FeatureRegistryService not loaded — call load() first.")
        feature = self._features.get(feature_name)
        if feature is None:
            return self._min_ic_sharpe_default
        per_feature = feature.get("min_ic_sharpe")
        if per_feature is not None:
            return float(per_feature)
        return self._min_ic_sharpe_default

    def get_status(self, feature_name: str) -> str | None:
        """Return the feature's current status, or None if not found."""
        if not self._loaded:
            raise RuntimeError("FeatureRegistryService not loaded — call load() first.")
        feature = self._features.get(feature_name)
        if feature is None:
            return None
        return feature["status"]

    # ------------------------------------------------------------------
    # Transition logging (fire-and-forget — ensemble_trainer only)
    # ------------------------------------------------------------------

    async def _write_transition_record(
        self,
        feature_name: str,
        from_status: str,
        to_status: str,
        reason: str,
        ic_value: float | None,
        ic_sharpe: float | None,
        ic_n: int | None,
    ) -> None:
        """Write a transition to feature_transition_log and update feature_registry.

        Inserts into feature_transition_log and updates the feature's status in
        feature_registry. Uses the asyncpg pool stored at load() time.

        Called only via asyncio.create_task() from record_transition() — never
        awaited directly by callers.
        """
        if self._pool is None:
            _logger.warning(
                "feature_registry_service.transition_skipped_no_pool",
                feature_name=feature_name,
                from_status=from_status,
                to_status=to_status,
            )
            return
        try:
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        """
                        INSERT INTO feature_transition_log
                            (feature_name, from_status, to_status, triggered_at,
                             trigger_reason, ic_value, ic_sharpe, ic_n)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                        """,
                        feature_name,
                        from_status,
                        to_status,
                        datetime.now(UTC),
                        reason,
                        ic_value,
                        ic_sharpe,
                        ic_n,
                    )
                    await conn.execute(
                        "UPDATE feature_registry SET status = $1 WHERE feature_name = $2",
                        to_status,
                        feature_name,
                    )
            # Update in-memory cache to reflect new status
            if feature_name in self._features:
                self._features[feature_name]["status"] = to_status
            _logger.info(
                "feature_registry_service.transition_recorded",
                feature_name=feature_name,
                from_status=from_status,
                to_status=to_status,
                reason=reason,
            )
        except Exception as error:
            _logger.error(
                "feature_registry_service.transition_write_error",
                feature_name=feature_name,
                error=str(error),
            )

    def record_transition(
        self,
        feature_name: str,
        from_status: str,
        to_status: str,
        reason: str,
        ic_value: float | None = None,
        ic_sharpe: float | None = None,
        ic_n: int | None = None,
    ) -> None:
        """Schedule a feature lifecycle transition as a background asyncio task.

        Synchronous wrapper that calls asyncio.create_task() to schedule the
        coroutine on the running event loop. True fire-and-forget — caller does
        not await the result.

        IMPORTANT: This is NOT async def. An async def that is not awaited creates
        a dead coroutine object. A sync def calling asyncio.create_task() correctly
        schedules the background coroutine on the running event loop.

        Expected caller: ensemble_trainer (fully async). ic_engine does NOT call
        record_transition() — it only reads registry status via get_status().

        Returns None. The caller ignores the Task object.
        """
        asyncio.create_task(
            self._write_transition_record(
                feature_name=feature_name,
                from_status=from_status,
                to_status=to_status,
                reason=reason,
                ic_value=ic_value,
                ic_sharpe=ic_sharpe,
                ic_n=ic_n,
            )
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry: FeatureRegistryService | None = None


def get_registry() -> FeatureRegistryService:
    """Return the module-level FeatureRegistryService singleton.

    Raises RuntimeError if the singleton has not been loaded (load() or
    load_sync() not yet called).
    """
    global _registry
    if _registry is None:
        raise RuntimeError(
            "FeatureRegistryService not initialized. "
            "Call load() or load_sync() before get_registry()."
        )
    if not _registry._loaded:
        raise RuntimeError(
            "FeatureRegistryService singleton exists but has not been loaded. "
            "Call load() or load_sync() first."
        )
    return _registry
