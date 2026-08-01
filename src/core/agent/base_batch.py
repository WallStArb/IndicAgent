"""BaseBatch — abstract base class for all Phase 138+ batch compute oneshots.

Provides the shared DB pool lifecycle, D-06 job_completed_total emission,
content-addressed key generation, and error handling across all batch compute
services (regime_writer, forward_return_writer, ic_engine, and future services).

Contract:
- Subclasses must define: job_name (str class attr), compute_version (str class attr),
  execute(pool: asyncpg.Pool) -> None (async method)
- run() is the entry point: set up pool, call execute(), emit D-06 metric, tear down pool
- content_key() is a staticmethod for SHA-256 content-addressed keys (mirrors signal_schema.py)

Ring 0 restriction: no imports from src/intelligence/.
"""

from __future__ import annotations

import abc
import hashlib
import time
from collections.abc import Awaitable
from typing import Any

import asyncpg
import structlog

from src.core.database_manager import create_pool
from src.core.service_utils import setup_service_logging
from src.observability.corpus_manifest import CorpusManifest
from src.observability.metrics import (
    JOB_COMPLETED_TOTAL,
    JOB_DURATION_SECONDS,
    flush_and_shutdown_metrics,
)
from src.observability.spans import observed_span


class BaseBatch(abc.ABC):
    """Abstract base for batch compute oneshot services.

    Subclasses define:
      job_name: str         -- D-06 job label (must match systemd unit %n suffix, kebab-case)
      compute_version: str  -- version tag written to DB rows for auditability
      execute(pool) -> None -- async compute method; receives an open asyncpg Pool

    Lifecycle (run()):
      1. _setup_pool()
      2. execute(pool)  →  status = "success"
         or exception  →  status = "failure", re-raise
      3. _emit_completion(status, elapsed_s)
      4. _teardown_pool()  (always, even on failure)
    """

    job_name: str
    compute_version: str

    def __init__(self, db_dsn: str) -> None:
        self._db_dsn = db_dsn
        self._pool: asyncpg.Pool | None = None
        # Auto-derive log path from job_name (kebab → snake) if available,
        # otherwise fall back to class name.
        log_name = getattr(self, "job_name", type(self).__name__).replace("-", "_")
        setup_service_logging(f"logs/{log_name}.log")
        self.logger = structlog.get_logger(type(self).__name__)

    # -----------------------------------------------------------------------
    # Abstract interface — subclasses must implement
    # -----------------------------------------------------------------------

    @abc.abstractmethod
    async def execute(self, pool: asyncpg.Pool) -> None:
        """Run the batch computation. Called with an open asyncpg Pool.

        Subclasses own all business logic; BaseBatch owns lifecycle, metrics,
        error handling, and pool management.
        """

    def _span_attrs(self) -> dict[str, Any]:
        """Extra attributes for the auto-created execute() span. Override in subclasses."""
        return {}

    @staticmethod
    async def _run_with_manifest_capture(manifest: CorpusManifest, coro: Awaitable[None]) -> None:
        """Await `coro`, recording any exception onto `manifest` before re-raising.

        Shared by subclasses that maintain their own CorpusManifest across a run
        (alpha_publisher, ensemble_trainer): manifest.write() is best-effort — its own
        failure must not mask the original error, hence the inner try/except.
        """
        try:
            await coro
        except Exception as error:
            manifest.add_error(str(error))
            try:
                manifest.write()
            except Exception:
                pass
            raise

    # -----------------------------------------------------------------------
    # Entry point
    # -----------------------------------------------------------------------

    async def run(self) -> None:
        """Template method: pool setup → execute (spanned) → D-06 emission → teardown.

        Always emits job_completed_total (success or failure) so Grafana
        dashboards show the last run result regardless of outcome. execute()
        is wrapped in a span automatically (todo 156/157) -- every BaseBatch
        subclass gets execute()-level tracing without calling observed_span itself.
        """
        await self._setup_pool()
        t0 = time.monotonic()
        status = "success"
        try:
            # job_name is kebab-case (matches the systemd unit %n suffix, D-06 contract) --
            # span names are snake_case repo-wide, so translate rather than propagate kebab-case.
            span_name = f"{self.job_name.replace('-', '_')}.execute"
            async with observed_span(span_name, **self._span_attrs()):
                await self.execute(self._pool)
        except Exception as error:
            status = "failure"
            self.logger.error(
                "batch_computer.failed",
                job=self.job_name,
                error=str(error),
            )
            raise
        finally:
            self._emit_completion(status, time.monotonic() - t0)
            await self._teardown_pool()
            # Drain OTel exporter before process exits (D-06 contract).
            flush_and_shutdown_metrics()

    # -----------------------------------------------------------------------
    # Content-addressed key generation (mirrors make_signal_id in signal_schema.py)
    # -----------------------------------------------------------------------

    @staticmethod
    def content_key(*parts: str) -> str:
        """SHA-256 content key from arbitrary string parts.

        Returns the first 32 hex characters of SHA-256(parts joined with '|').
        Deterministic: same parts always produce the same key. Used for
        app-layer uniqueness in tables where TimescaleDB hypertable constraints
        prevent standard unique indexes.

        Example:
            BaseBatch.content_key("SPY", "5m", "1719014400000000000")
            # → 32-character hex string, e.g. "a3f4b2c1d0e5f6a7b8c9d0e1f2a3b4c5"
        """
        raw = "|".join(str(p) for p in parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    # -----------------------------------------------------------------------
    # Pool lifecycle (private)
    # -----------------------------------------------------------------------

    async def _setup_pool(self) -> None:
        """Open asyncpg connection pool with JSONB codecs and pool metrics.

        Delegates to database_manager.create_pool which registers the JSONB codec
        (encoder=json.dumps, decoder=json.loads) and emits DB_POOL_SIZE / DB_POOL_IDLE
        gauge increments atomically. Never call bare asyncpg.create_pool here — it
        skips codec registration and causes silent JSONB encode/decode failures.
        """
        self._pool = await create_pool(
            self._db_dsn,
            pool_name=self.job_name,
            min_size=1,
            max_size=10,
        )
        self.logger.info("batch_computer.pool_open", job=self.job_name, min_size=1, max_size=10)

    async def _teardown_pool(self) -> None:
        """Close asyncpg connection pool, tolerating already-closed pools."""
        if self._pool is not None:
            try:
                await self._pool.close()
            except Exception as error:
                self.logger.warning(
                    "batch_computer.pool_close_error",
                    job=self.job_name,
                    error=str(error),
                )
            finally:
                self._pool = None

    # -----------------------------------------------------------------------
    # D-06 emission
    # -----------------------------------------------------------------------

    def _emit_completion(self, status: str, elapsed_s: float) -> None:
        """Emit job_completed_total/job_duration_seconds and a structured completion log.

        D-06 contract: job label must match systemd unit %n suffix (kebab-case).
        Callers must invoke flush_and_shutdown_metrics() before process exit so
        the OTLP exporter drains.
        """
        attrs = {"job": self.job_name, "status": status}
        JOB_COMPLETED_TOTAL.add(1, attrs)
        JOB_DURATION_SECONDS.record(elapsed_s, attrs)
        self.logger.info(
            "batch_computer.completed",
            job=self.job_name,
            status=status,
            elapsed_s=round(elapsed_s, 2),
        )
