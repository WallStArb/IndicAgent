#!/usr/bin/env python3
"""SignalMetricsWriter — persists signal metrics events to DB.

Subscribes to intelligence.signal_metrics Kafka topic.
Handles three event types published by SignalMetricsAnalyzer:
  - metrics_computed -> UPSERT signal_metrics
  - ic_computed      -> UPSERT signal_metrics_ic
  - metrics_dq_failure -> INSERT signal_metrics_dq_failures

Also updates setup_performance table as a backward-compatibility shim so
intelligence_pipeline_agent can read perf_multiplier weights without changes
until Plan 60-03 updates it to read signal_metrics directly.

The shim only activates for: track='market', regime_type='all', window_days=30.


Version: 2.0.0
Last Updated: 2026-05-17
Status: Phase 085 Plan 04 — migrated to BaseWriter
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import _path_bootstrap  # noqa: F401 — project root on sys.path

from src.core.agent.base_writer import BaseWriter
from src.core.database_manager import DatabaseManager
from src.core.stream_keys import topic_signal_metrics
from src.intelligence.schemas import SignalMetricsEvent

_CONSUMER_GROUP = "signal_metrics_writer_consumer"


async def _ensure_schema(conn) -> None:
    """Idempotent startup migration: add entry_type + six distribution columns and rebuild PK.

    Each ALTER TABLE uses IF NOT EXISTS — safe to run on every startup.
    The PK rebuild is guarded by information_schema.key_column_usage check so a second
    concurrent startup is a no-op. SET LOCAL statement_timeout = '30s' is applied inside
    an explicit transaction to bound lock acquisition time (Gemini LOW concern).

    Signal_metrics is ~1.6k rows; PK rebuild is instant in practice.
    """
    # Add entry_type column (NOT NULL with DEFAULT ensures existing rows get '*')
    await conn.execute(
        "ALTER TABLE signal_metrics ADD COLUMN IF NOT EXISTS entry_type text NOT NULL DEFAULT '*'"
    )
    # Add six distribution shape columns (all nullable float)
    await conn.execute("ALTER TABLE signal_metrics ADD COLUMN IF NOT EXISTS skewness float")
    await conn.execute("ALTER TABLE signal_metrics ADD COLUMN IF NOT EXISTS kurtosis float")
    await conn.execute("ALTER TABLE signal_metrics ADD COLUMN IF NOT EXISTS min_r float")
    await conn.execute("ALTER TABLE signal_metrics ADD COLUMN IF NOT EXISTS p5_r float")
    await conn.execute("ALTER TABLE signal_metrics ADD COLUMN IF NOT EXISTS recovery_factor float")
    await conn.execute("ALTER TABLE signal_metrics ADD COLUMN IF NOT EXISTS cvar_5 float")

    # Rebuild PK to include entry_type — wrapped in explicit transaction so that
    # SET LOCAL statement_timeout bounds the lock acquisition to 30 seconds.
    async with conn.transaction():
        await conn.execute("SET LOCAL statement_timeout = '30s'")
        await conn.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM information_schema.key_column_usage
                    WHERE table_name = 'signal_metrics'
                      AND constraint_name = 'signal_metrics_pkey'
                      AND column_name = 'entry_type'
                ) THEN
                    ALTER TABLE signal_metrics DROP CONSTRAINT IF EXISTS signal_metrics_pkey;
                    ALTER TABLE signal_metrics ADD PRIMARY KEY
                        (track, setup_plugin, tf, regime_type, window_days, symbol, entry_type);
                END IF;
            END $$;
            """)


async def _handle_metrics_computed(conn, event: dict) -> None:
    """Upsert one row to signal_metrics. Also updates setup_performance shim
    for market track / 'all' regime / 30d window."""
    computed_at = datetime.fromisoformat(event["computed_at"])

    await conn.execute(
        """
        INSERT INTO signal_metrics
            (track, setup_plugin, tf, regime_type, window_days, symbol, entry_type,
             n, n_outliers, never_activated_pct,
             win_rate, avg_r, std_r, sharpe, p_value,
             avg_mae, avg_mfe,
             skewness, kurtosis, min_r, p5_r, recovery_factor, cvar_5,
             computed_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24)
        ON CONFLICT (track, setup_plugin, tf, regime_type, window_days, symbol, entry_type)
        DO UPDATE SET
            n                   = EXCLUDED.n,
            n_outliers          = EXCLUDED.n_outliers,
            never_activated_pct = EXCLUDED.never_activated_pct,
            win_rate            = EXCLUDED.win_rate,
            avg_r               = EXCLUDED.avg_r,
            std_r               = EXCLUDED.std_r,
            sharpe              = EXCLUDED.sharpe,
            p_value             = EXCLUDED.p_value,
            avg_mae             = EXCLUDED.avg_mae,
            avg_mfe             = EXCLUDED.avg_mfe,
            skewness            = EXCLUDED.skewness,
            kurtosis            = EXCLUDED.kurtosis,
            min_r               = EXCLUDED.min_r,
            p5_r                = EXCLUDED.p5_r,
            recovery_factor     = EXCLUDED.recovery_factor,
            cvar_5              = EXCLUDED.cvar_5,
            computed_at         = EXCLUDED.computed_at
        """,
        event["track"],
        event["setup_plugin"],
        event["tf"],
        event["regime_type"],
        event["window_days"],
        event.get("symbol", "*"),
        event.get("entry_type", "*"),
        event["n"],
        event["n_outliers"],
        event.get("never_activated_pct"),
        event.get("win_rate"),
        event.get("avg_r"),
        event.get("std_r"),
        event.get("sharpe"),
        event.get("p_value"),
        event.get("avg_mae"),
        event.get("avg_mfe"),
        event.get("skewness"),
        event.get("kurtosis"),
        event.get("min_r"),
        event.get("p5_r"),
        event.get("recovery_factor"),
        event.get("cvar_5"),
        computed_at,
    )

    # Backward-compat shim: keep setup_performance populated from market track
    # (regime_type='all', window_days=30) so intelligence_pipeline_agent
    # reads valid perf_multiplier data until Plan 60-03 updates it.
    if (
        event["track"] == "market"
        and event["regime_type"] == "all"
        and event["window_days"] == 30
        and event.get("avg_r") is not None
        and event.get("sharpe") is not None
        # Minimum 100 samples required; values below 200 are statistically unreliable on fat-tailed returns
        and event["n"] >= 100
    ):
        await conn.execute(
            """
            INSERT INTO setup_performance
                (setup_plugin, symbol, win_rate, avg_pnl_r, sample_size, sharpe_ratio, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, NOW())
            ON CONFLICT (setup_plugin, symbol) DO UPDATE
                SET win_rate     = EXCLUDED.win_rate,
                    avg_pnl_r   = EXCLUDED.avg_pnl_r,
                    sample_size  = EXCLUDED.sample_size,
                    sharpe_ratio = EXCLUDED.sharpe_ratio,
                    updated_at   = EXCLUDED.updated_at
            """,
            event["setup_plugin"],
            event.get("symbol", "*"),
            event.get("win_rate"),
            event.get("avg_r"),
            event["n"],
            event.get("sharpe"),
        )


async def _handle_ic_computed(conn, event: dict) -> None:
    """Upsert one row to signal_metrics_ic."""
    computed_at = datetime.fromisoformat(event["computed_at"])
    await conn.execute(
        """
        INSERT INTO signal_metrics_ic
            (setup_plugin, tf, regime_type, window_days, symbol,
             n, ic, p_value, is_significant, computed_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        ON CONFLICT (setup_plugin, tf, regime_type, window_days, symbol)
        DO UPDATE SET
            n              = EXCLUDED.n,
            ic             = EXCLUDED.ic,
            p_value        = EXCLUDED.p_value,
            is_significant = EXCLUDED.is_significant,
            computed_at    = EXCLUDED.computed_at
        """,
        event["setup_plugin"],
        event["tf"],
        event["regime_type"],
        event["window_days"],
        event.get("symbol", "*"),
        event["n"],
        event.get("ic"),
        event.get("p_value"),
        event.get("is_significant", False),
        computed_at,
    )


async def _handle_dq_failure(conn, event: dict) -> None:
    """Insert one row to signal_metrics_dq_failures."""
    await conn.execute(
        """
        INSERT INTO signal_metrics_dq_failures
            (signal_id, reason_code, entry_price, stop_loss,
             pnl_r, direction, hmm_regime, setup_plugin, created_at)
        VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, NOW())
        """,
        event["signal_id"],
        event["reason_code"],
        event.get("entry_price"),
        event.get("stop_loss"),
        event.get("pnl_r"),
        event.get("direction"),
        event.get("hmm_regime"),
        event.get("setup_plugin"),
    )


class SignalMetricsWriter(BaseWriter):
    """Consumes intelligence.signal_metrics and writes to DB via BaseWriter."""

    BATCH_SIZE = 50
    FLUSH_INTERVAL_SECS = 5.0
    payload_model = SignalMetricsEvent

    def __init__(self) -> None:
        super().__init__()
        self._db: DatabaseManager | None = None

    def _topic_name(self) -> str:
        return topic_signal_metrics(self.env_name)

    @property
    def _consumer_group(self) -> str:
        return _CONSUMER_GROUP

    def _dlq_topic(self) -> str | None:
        return topic_signal_metrics(self.env_name) + ".dlq"

    def _parse_payload(self, payload: SignalMetricsEvent) -> tuple[list, list]:
        """Receive already-validated SignalMetricsEvent; dispatching done in _flush_batch."""
        return [payload], []

    async def _flush_batch(self, batch: list[SignalMetricsEvent]) -> None:
        """Dispatch each event to the appropriate SQL helper by event_type."""
        if not batch:
            return
        assert self._db is not None
        async with self._db.get_connection() as conn:
            for event in batch:
                event_dict = event.model_dump()
                if event.event_type == "metrics_computed":
                    await _handle_metrics_computed(conn, event_dict)
                elif event.event_type == "ic_computed":
                    await _handle_ic_computed(conn, event_dict)
                elif event.event_type == "metrics_dq_failure":
                    await _handle_dq_failure(conn, event_dict)
                else:
                    # Discriminated union blocks unknown types at parse time;
                    # this branch is a safety net only.
                    self.logger.warning(
                        "signal_metrics_writer.unknown_event_type",
                        event_type=event.event_type,
                    )

    async def _setup(self) -> None:
        """Connect DB pool, run schema migration, then start Kafka consumer."""
        self._db = DatabaseManager(self.settings.database_url)
        await self._db.initialize()

        async with self._db.get_connection() as conn:
            await _ensure_schema(conn)

        self._create_consumer()
        await self._consumer.start()
        self._last_flush = 0.0
        self.logger.info(
            "signal_metrics_writer.setup_complete",
            topic=self._topic_name(),
        )

    async def _teardown(self) -> None:
        """Final flush, stop consumer and close DB pool."""
        await super()._teardown()
        if self._consumer:
            await self._consumer.stop()
        if self._db is not None:
            await self._db.close()


async def _amain() -> None:
    agent = SignalMetricsWriter()
    await agent.start()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
