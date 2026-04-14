#!/usr/bin/env python3
"""SignalMetricsWriterAgent — persists signal metrics events to DB.

Subscribes to intelligence.signal_metrics Kafka topic.
Handles three event types published by SignalMetricsComputeAgent:
  - metrics_computed → UPSERT signal_metrics
  - ic_computed      → UPSERT signal_metrics_ic
  - metrics_dq_failure → INSERT signal_metrics_dq_failures

Also updates setup_performance table as a backward-compatibility shim so
intelligence_pipeline_agent can read perf_multiplier weights without changes
until Plan 60-03 updates it to read signal_metrics directly.

The shim only activates for: track='market', regime_type='all', window_days=30.

Metrics port: :9127

Version: 1.0.0
Last Updated: 2026-04-05
Status: Phase 60 Plan 02
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from prometheus_client import Counter

from src.core.agent.base import BaseAgent
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient
from src.core.stream_keys import topic_signal_metrics
from src.observability.otel import init_tracing

_EVENTS_CONSUMED = Counter(
    "signal_metrics_writer_events_consumed_total",
    "Events consumed from intelligence.signal_metrics",
    ["agent", "event_type"],
)
_WRITE_ERRORS = Counter(
    "signal_metrics_writer_errors_total",
    "DB write errors by event type",
    ["agent", "event_type"],
)

_AGENT_NAME = "signal_metrics_writer"
_METRICS_PORT = 9127
_CONSUMER_GROUP = "signal_metrics_writer_consumer"


async def _handle_metrics_computed(conn, event: dict) -> None:
    """Upsert one row to signal_metrics. Also updates setup_performance shim
    for market track / 'all' regime / 30d window."""
    computed_at = datetime.fromisoformat(event["computed_at"])

    await conn.execute(
        """
        INSERT INTO signal_metrics
            (track, setup_plugin, tf, regime_type, window_days, symbol,
             n, n_outliers, never_activated_pct,
             win_rate, avg_r, std_r, sharpe, p_value,
             avg_mae, avg_mfe, computed_at)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
        ON CONFLICT (track, setup_plugin, tf, regime_type, window_days, symbol)
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
            computed_at         = EXCLUDED.computed_at
        """,
        event["track"],
        event["setup_plugin"],
        event["tf"],
        event["regime_type"],
        event["window_days"],
        event.get("symbol", "*"),
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
        and event["n"] >= 30
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
    """Insert one row to signal_metrics_dq_failures (idempotent — one row per signal+reason)."""
    await conn.execute(
        """
        INSERT INTO signal_metrics_dq_failures
            (signal_id, reason_code, entry_price, stop_loss,
             pnl_r, direction, hmm_regime, setup_plugin, created_at)
        VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, NOW())
        ON CONFLICT (signal_id, reason_code) DO NOTHING
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


class SignalMetricsWriterAgent(BaseAgent):
    """Consumes intelligence.signal_metrics and writes to DB."""

    def __init__(self) -> None:
        super().__init__(name=_AGENT_NAME, metrics_port=_METRICS_PORT)
        self._env_name: str = self.settings.env_name or ""

        self._db: DatabaseManager | None = None
        self._kafka_consumer: KafkaConsumerClient | None = None

    @property
    def topics_consumed(self) -> list[str]:
        return [topic_signal_metrics(self._env_name)]

    async def _setup(self) -> None:
        """Connect DB pool and Kafka consumer."""
        self._db = DatabaseManager(self.settings.database_url)
        await self._db.initialize()

        self._kafka_consumer = KafkaConsumerClient(
            topic_signal_metrics(self._env_name),
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id=_CONSUMER_GROUP,
            auto_offset_reset="latest",
        )
        await self._kafka_consumer.start()
        self.logger.info(
            "signal_metrics_writer.setup_complete",
            topics_consumed=self.topics_consumed,
        )


    async def _teardown(self) -> None:
        """Stop consumer and close DB pool."""
        if self._kafka_consumer is not None:
            await self._kafka_consumer.stop()
        if self._db is not None:
            await self._db.close()

    async def _run(self) -> None:
        """Consume events from intelligence.signal_metrics until stop event."""
        # lag_task created by BaseAgent.start() at line 155
        async for _topic, _key, event in self._kafka_consumer.messages():
            if self._stop_event.is_set():
                break
            event_type = event.get("event_type", "unknown")
            try:
                async with self._db.get_connection() as conn:
                    if event_type == "metrics_computed":
                        await _handle_metrics_computed(conn, event)
                    elif event_type == "ic_computed":
                        await _handle_ic_computed(conn, event)
                    elif event_type == "metrics_dq_failure":
                        await _handle_dq_failure(conn, event)
                    else:
                        self.logger.warning(
                            "signal_metrics_writer.unknown_event_type",
                            event_type=event_type,
                        )
                    _EVENTS_CONSUMED.labels(agent=_AGENT_NAME, event_type=event_type).inc()
            except Exception as exc:
                _WRITE_ERRORS.labels(agent=_AGENT_NAME, event_type=event_type).inc()
                self.logger.error(
                    "signal_metrics_writer.write_error",
                    event_type=event_type,
                    error=str(exc),
                    exc_info=True,
                )


async def _amain() -> None:
    init_tracing("signal-metrics-writer")
    agent = SignalMetricsWriterAgent()
    await agent.start()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
