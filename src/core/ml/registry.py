"""ModelRegistry — thin MLflow wrapper for model lifecycle.

Hides the MLflow API from all callers. Four operations:
  register(run_id, segment, artifact_path) → model_id
  load_latest(segment)                     → model artifact
  promote(model_id)
  revert(model_id)
"""
from __future__ import annotations

from typing import Any

import asyncpg
import structlog

logger = structlog.get_logger(__name__)


class ModelRegistry:
    """DB-backed model registry. MLflow stores artifacts; this table routes inference."""

    def __init__(self, pool: asyncpg.Pool, mlflow_tracking_uri: str = "http://localhost:5000") -> None:
        self._pool = pool
        self._mlflow_uri = mlflow_tracking_uri

    async def register(
        self,
        run_id: str,
        segment: dict[str, Any],
        artifact_path: str,
        model_type: str = "lightgbm",
    ) -> str:
        """Insert model record, return model_id UUID string."""
        import json
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO ml_models (model_type, segment, mlflow_run_id, artifact_path, status)
                VALUES ($1, $2, $3, $4, 'shadow')
                RETURNING model_id::text
                """,
                model_type,
                json.dumps(segment),
                run_id,
                artifact_path,
            )
        model_id = row["model_id"]
        logger.info("model_registry.registered", model_id=model_id, segment=segment)
        return model_id

    async def load_latest(self, segment: dict[str, Any]) -> Any | None:
        """Load latest production model artifact for segment. Returns None if none promoted."""
        import json
        import mlflow
        mlflow.set_tracking_uri(self._mlflow_uri)

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT artifact_path, mlflow_run_id FROM ml_models
                WHERE status = 'production'
                  AND segment @> $1::jsonb
                ORDER BY promoted_at DESC
                LIMIT 1
                """,
                json.dumps(segment),
            )
        if row is None:
            return None
        try:
            return mlflow.pyfunc.load_model(row["artifact_path"])
        except Exception as exc:
            logger.error("model_registry.load_failed", artifact=row["artifact_path"], error=str(exc))
            return None

    async def promote(self, model_id: str) -> None:
        """Set model status to production."""
        from datetime import UTC, datetime
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE ml_models SET status='production', promoted_at=$1 WHERE model_id=$2::uuid",
                datetime.now(UTC),
                model_id,
            )
        logger.info("model_registry.promoted", model_id=model_id)

    async def revert(self, model_id: str) -> None:
        """Retire a model (does not restore previous production model)."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE ml_models SET status='retired' WHERE model_id=$1::uuid",
                model_id,
            )
        logger.info("model_registry.reverted", model_id=model_id)
