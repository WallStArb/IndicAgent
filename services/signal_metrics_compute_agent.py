#!/usr/bin/env python3
"""SignalMetricsComputeAgent — timer-triggered signal performance metrics computation.

Runs every 15 minutes. Queries signal_ledger for resolved signals in a 90-day
window, validates each row through DataQualityValidator, computes per-segment
metrics for zone and market tracks, and publishes events to
intelligence.signal_metrics topic for SignalMetricsWriterAgent to persist.

DB-aware (reads signal_ledger) but publishes DB-ignorant events.
Metrics port: :9126

Golden Signals:
- Traffic: compute_cycles_total
- Latency: compute_cycle_duration_seconds
- Errors: compute_cycle_errors_total
- Saturation: rows_processed_per_cycle (gauge)

Version: 1.0.0
Last Updated: 2026-04-05
Status: Phase 60 Plan 02
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from prometheus_client import Counter, Gauge, Histogram

from src.config.settings import Settings
from src.core.agent.base import BaseAgent
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaProducerClient
from src.core.service_utils import setup_service_logging
from src.core.stream_keys import topic_signal_metrics
from src.intelligence.metrics.compute import (
    WINDOWS,
    compute_ic_metrics,
    compute_signal_metrics,
)
from src.intelligence.metrics.validator import validate_signal_row
from src.observability.metrics import PERSISTENCE_CONSUMER_LAG
from src.observability.otel import init_tracing

_COMPUTE_CYCLES = Counter(
    "signal_metrics_compute_cycles_total",
    "Total compute cycles completed",
    ["agent"],
)
_COMPUTE_ERRORS = Counter(
    "signal_metrics_compute_cycle_errors_total",
    "Exceptions during compute cycles",
    ["agent"],
)
_COMPUTE_DURATION = Histogram(
    "signal_metrics_compute_cycle_duration_seconds",
    "Wall-clock time for a full compute cycle",
    ["agent"],
)
_ROWS_PROCESSED = Gauge(
    "signal_metrics_rows_processed_per_cycle",
    "Rows fetched from signal_ledger in last cycle",
    ["agent"],
)
_DQ_FAILURES = Counter(
    "signal_metrics_dq_failures_total",
    "Data quality gate failures by reason",
    ["agent", "reason_code"],
)

_AGENT_NAME = "signal_metrics_compute"
_INTERVAL_SECONDS = 900  # 15 minutes
_LOOKBACK_DAYS = 90  # max window — query covers full 90d
_METRICS_PORT = 9126

_QUERY = """
    SELECT
        signal_id::text,
        setup_plugin,
        timeframe              AS tf,
        symbol,
        hmm_regime_at_fire,
        direction,
        entry_price,
        stop_loss,
        pnl_r,
        mae,
        mfe,
        outcome,
        confidence,
        exit_at,
        market_entry_pnl_r,
        market_entry_mae,
        market_entry_mfe,
        market_entry_outcome
    FROM signal_ledger
    WHERE outcome IS NOT NULL
      AND exit_at > NOW() - INTERVAL '90 days'
      AND setup_plugin IS NOT NULL
      AND was_selected = true
    ORDER BY exit_at
"""


class SignalMetricsComputeAgent(BaseAgent):
    """Timer-triggered agent that computes signal performance metrics.

    Publishes three event types to intelligence.signal_metrics:
      - metrics_computed: one per (track, setup, tf, regime, window) group
      - ic_computed:      one per (setup, tf, regime, window) group
      - metrics_dq_failure: one per invalid pnl_r row (new failures only)
    """

    def __init__(self) -> None:
        # config-before-super pattern (Phase 52.2 convention)
        self._env_name: str = self.settings.env_name or ""
        super().__init__(name=_AGENT_NAME, metrics_port=_METRICS_PORT)

        self._db: DatabaseManager | None = None
        self._producer: KafkaProducerClient | None = None
        self._interval_seconds = _INTERVAL_SECONDS
        self._tick_sizes: dict[str, float] = {}
        self._published_dq_keys: set[str] = set()
        self._cycle_count: int = 0

    async def _load_tick_sizes(self) -> None:
        """Load per-instrument tick sizes from instruments table."""
        rows = await self._db.execute_query(
            "SELECT symbol, (contract_details->>'tick_size')::float as tick_size "
            "FROM instruments WHERE is_active = true AND contract_details->>'tick_size' IS NOT NULL"
        )
        self._tick_sizes = {r["symbol"]: r["tick_size"] for r in rows if r.get("tick_size")}
        self.logger.info(
            "signal_metrics_compute.tick_sizes_loaded",
            instruments=len(self._tick_sizes),
        )

    async def _load_published_dq_keys(self) -> None:
        """Populate in-memory dedup set from DB on startup.

        Prevents re-publishing DQ failures that were already recorded in a
        previous process lifetime. Without this, every restart re-publishes
        all failures from the 90-day window, flooding signal_metrics_dq_failures.
        """
        rows = await self._db.execute_query(
            "SELECT signal_id::text || ':' || reason_code AS dq_key "
            "FROM signal_metrics_dq_failures "
            "WHERE created_at > NOW() - INTERVAL '90 days'"
        )
        self._published_dq_keys = {r["dq_key"] for r in rows}
        self.logger.info(
            "signal_metrics_compute.dq_keys_loaded",
            existing_dq_keys=len(self._published_dq_keys),
        )

    async def _setup(self) -> None:
        """Connect DB pool and Kafka producer."""
        self._db = DatabaseManager(self.settings.database_url)
        await self._db.initialize()

        self._producer = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
        )
        await self._producer.start()

        await asyncio.gather(self._load_tick_sizes(), self._load_published_dq_keys())

        self.logger.info(
            "signal_metrics_compute.setup_complete",
            interval_seconds=self._interval_seconds,
            tick_sizes=len(self._tick_sizes),
        )

    async def _report_consumer_lag(self) -> None:
        """Report consumer lag until stop event. Timer-triggered compute — no buffer accumulation."""
        while not self._stop_event.is_set():
            PERSISTENCE_CONSUMER_LAG.labels(agent_id=self.name).set(0)
            await asyncio.sleep(15)

    async def _teardown(self) -> None:
        """Stop producer and close DB pool."""
        if self._producer is not None:
            await self._producer.stop()
        if self._db is not None:
            await self._db.close()

    async def _run(self) -> None:
        """Timer loop: run compute cycle every 15 minutes until stop event."""
        # lag_task created by BaseAgent.start() at line 155
        while not self._stop_event.is_set():
            with _COMPUTE_DURATION.labels(agent=_AGENT_NAME).time():
                try:
                    await self._run_compute_cycle()
                    _COMPUTE_CYCLES.labels(agent=_AGENT_NAME).inc()
                except Exception as exc:
                    _COMPUTE_ERRORS.labels(agent=_AGENT_NAME).inc()
                    self.logger.error(
                        "signal_metrics_compute.cycle_failed",
                        error=str(exc),
                        exc_info=True,
                    )
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                pass  # normal — time to run next cycle

    async def _run_compute_cycle(self) -> None:
        """Fetch rows, validate, compute metrics, publish events."""
        self._cycle_count += 1
        # Refresh tick sizes every 24h (96 cycles) — tick sizes are static per instrument
        if self._cycle_count % 96 == 1:
            await self._load_tick_sizes()

        rows = await self._db.execute_query(_QUERY)
        if not rows:
            self.logger.info("signal_metrics_compute.cycle rows=0 nothing_to_compute")
            return

        _ROWS_PROCESSED.labels(agent=_AGENT_NAME).set(len(rows))
        self.logger.info("signal_metrics_compute.cycle rows=%d", len(rows))

        topic = topic_signal_metrics(self.settings.env_name)
        now_iso = datetime.now(UTC).isoformat()

        # Publish DQ failures for NEW invalid rows only (dedup by signal_id + reason_code)
        new_dq_count = 0
        for row in rows:
            pnl_r = row.get("pnl_r")
            if pnl_r is None:
                continue  # never activated — valid; counted separately
            vr = validate_signal_row(
                direction=row.get("direction"),
                entry_price=row.get("entry_price"),
                stop_loss=row.get("stop_loss"),
                pnl_r=pnl_r,
                hmm_regime_at_fire=row.get("hmm_regime_at_fire"),
                symbol=row.get("symbol"),
                tick_sizes=self._tick_sizes,
            )
            if not vr.is_valid:
                dq_key = f"{row.get('signal_id')}:{vr.reason_code}"
                if dq_key in self._published_dq_keys:
                    continue  # already published in a previous cycle
                self._published_dq_keys.add(dq_key)
                new_dq_count += 1
                _DQ_FAILURES.labels(agent=_AGENT_NAME, reason_code=vr.reason_code).inc()
                await self._producer.publish(
                    topic,
                    msg={
                        "event_type": "metrics_dq_failure",
                        "signal_id": row.get("signal_id"),
                        "reason_code": vr.reason_code,
                        "entry_price": row.get("entry_price"),
                        "stop_loss": row.get("stop_loss"),
                        "pnl_r": pnl_r,
                        "direction": row.get("direction"),
                        "hmm_regime": row.get("hmm_regime_at_fire"),
                        "setup_plugin": row.get("setup_plugin"),
                        "created_at": now_iso,
                    },
                    key=f"dq_failure:{row.get('signal_id')}",
                )

        # Compute and publish metrics for each window and track
        now = datetime.now(UTC)
        for window_days in WINDOWS:
            # Filter rows to the actual window — compute_signal_metrics labels but doesn't filter
            cutoff = now - timedelta(days=window_days)
            window_rows = [
                r
                for r in rows
                if r.get("exit_at")
                and (
                    r["exit_at"]
                    if isinstance(r["exit_at"], datetime)
                    else datetime.fromisoformat(str(r["exit_at"]).replace("Z", "+00:00"))
                )
                >= cutoff
            ]
            for track in ("zone", "market"):
                metric_rows = compute_signal_metrics(
                    window_rows,
                    track=track,
                    window_days=window_days,
                    tick_sizes=self._tick_sizes,
                )
                for mr in metric_rows:
                    await self._producer.publish(
                        topic,
                        msg={
                            "event_type": "metrics_computed",
                            "track": mr.track,
                            "setup_plugin": mr.setup_plugin,
                            "tf": mr.tf,
                            "regime_type": mr.regime_type,
                            "window_days": mr.window_days,
                            "symbol": mr.symbol,
                            "n": mr.n,
                            "n_outliers": mr.n_outliers,
                            "never_activated_pct": mr.never_activated_pct,
                            "win_rate": mr.win_rate,
                            "avg_r": mr.avg_r,
                            "std_r": mr.std_r,
                            "sharpe": mr.sharpe,
                            "p_value": mr.p_value,
                            "avg_mae": mr.avg_mae,
                            "avg_mfe": mr.avg_mfe,
                            "computed_at": mr.computed_at.isoformat(),
                        },
                        key=f"metrics:{track}:{mr.setup_plugin}:{mr.tf}:{mr.regime_type}:{window_days}:{mr.symbol}",
                    )

            # IC metrics (measures confidence predictive power; not track-split)
            ic_rows = compute_ic_metrics(window_rows, window_days=window_days)
            for ir in ic_rows:
                await self._producer.publish(
                    topic,
                    msg={
                        "event_type": "ic_computed",
                        "setup_plugin": ir.setup_plugin,
                        "tf": ir.tf,
                        "regime_type": ir.regime_type,
                        "window_days": ir.window_days,
                        "n": ir.n,
                        "ic": ir.ic,
                        "p_value": ir.p_value,
                        "is_significant": ir.is_significant,
                        "computed_at": ir.computed_at.isoformat(),
                    },
                    key=f"ic:{ir.setup_plugin}:{ir.tf}:{ir.regime_type}:{window_days}",
                )

        self.logger.info(
            "signal_metrics_compute.cycle_complete",
            windows=list(WINDOWS),
            tracks="zone,market",
            new_dq_failures=new_dq_count,
            total_dq_keys_tracked=len(self._published_dq_keys),
        )

        # Prune DQ keys for signals no longer in the 90-day window.
        # Use str() — asyncpg returns UUID objects; k.split(":")[0] is a string.
        active_signal_ids = {str(r.get("signal_id")) for r in rows}
        self._published_dq_keys = {
            k for k in self._published_dq_keys if k.split(":")[0] in active_signal_ids
        }


async def _amain() -> None:
    init_tracing("signal-metrics-compute")
    agent = SignalMetricsComputeAgent()
    await agent.start()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
