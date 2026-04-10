#!/usr/bin/env python3
"""SignalAuditorAgent — coverage validation and lag monitoring for signal_ledger.

Runs a 5-minute audit loop during market hours. Checks:
1. Signal coverage per (symbol, tf) — at least one signal fired in the last session.
2. Pipeline lag P50/P95 from signal_ledger.pipeline_lag_ms over last 1h.
3. CIS score distribution (mean/stddev) per tf over a rolling 5-day window.

Batch efficiency: replaces 472 per-cycle DB round-trips with 1 via batch_signal_coverage().
Emits SignalCoverageGapEvent to intelligence.signal.audit on coverage gaps.
Emits SignalReplayRequest to market.events.signal_replay_requests for zero-signal sessions.
DB-aware (reads signal_ledger). AuditorAgent role — read-only, never writes.
Metrics port: :9128

Golden Signals:
- Traffic: signal_auditor_audits_run_total, signal_auditor_coverage_gaps_published_total
- Latency: signal_auditor_audit_duration_seconds
- Errors: signal_auditor_audit_errors_total
- Saturation: signal_coverage_pct{symbol, tf}

Version: 2.0.0
Phase: 63.6
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from datetime import date as date_type
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import asyncpg
from prometheus_client import Counter, Gauge, Histogram

from src.config.settings import Settings, get_active_contracts
from src.core.agent.base import BaseAgent
from src.core.audit_utils import SignalCoverageResult, batch_signal_coverage
from src.core.kafka_utils import KafkaProducerClient
from src.core.schemas.market_events import SignalReplayRequest
from src.core.stream_keys import topic_signal_audit, topic_signal_replay_requests
from src.observability.otel import init_tracing

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_AUDIT_INTERVAL = 300  # 5 minutes between audit cycles
_RTH_BUFFER_MINUTES = 30  # run audits RTH + 30 min buffer
# Timeframes audited for signal coverage
_COVERAGE_TFS: tuple[str, ...] = ("1m", "5m", "15m", "1h")
# Pipeline lag threshold for WARNING log (not CRIT — lag is operational)
_LAG_P95_WARN_MS = 500.0
# Rolling window for CIS distribution check (5 trading days ≈ 5 calendar days)
_CIS_LOOKBACK_DAYS = 5

# ---------------------------------------------------------------------------
# Module-level metrics (prevents duplicate registration on re-import)
# ---------------------------------------------------------------------------

_AUDITS_RUN = Counter(
    "signal_auditor_audits_run_total",
    "Total audit cycles completed",
    ["agent"],
)
_COVERAGE_GAPS_PUBLISHED = Counter(
    "signal_auditor_coverage_gaps_published_total",
    "SignalCoverageGapEvents published to Kafka",
    ["agent"],
)
_AUDIT_DURATION = Histogram(
    "signal_auditor_audit_duration_seconds",
    "Wall-clock time for a full audit cycle",
    ["agent"],
)
_AUDIT_ERRORS = Counter(
    "signal_auditor_audit_errors_total",
    "Exceptions during audit cycles",
    ["agent"],
)
_SIGNAL_COVERAGE_PCT = Gauge(
    "signal_coverage_pct",
    "1.0 if ≥1 signal fired in last session, 0.0 otherwise",
    ["agent", "symbol", "tf"],
)
_PIPELINE_LAG_P50 = Gauge(
    "signal_pipeline_lag_p50_ms",
    "P50 pipeline_lag_ms from signal_ledger over last 1h per (symbol, tf)",
    ["agent", "symbol", "tf"],
)
_PIPELINE_LAG_P95 = Gauge(
    "signal_pipeline_lag_p95_ms",
    "P95 pipeline_lag_ms from signal_ledger over last 1h per (symbol, tf)",
    ["agent", "symbol", "tf"],
)
_CIS_MEAN = Gauge(
    "signal_cis_mean",
    "Mean cis_score per tf over rolling 5-day window",
    ["agent", "tf"],
)
_CIS_STDDEV = Gauge(
    "signal_cis_stddev",
    "Stddev of cis_score per tf over rolling 5-day window",
    ["agent", "tf"],
)


class SignalAuditorAgent(BaseAgent):
    """AuditorAgent: validates signal coverage and pipeline health.

    Reads signal_ledger every 5 minutes during market hours.
    Uses batch_signal_coverage() — 1 DB round-trip per cycle (was 472).
    Emits SignalCoverageGapEvent to intelligence.signal.audit for missing coverage.
    Emits SignalReplayRequest to market.events.signal_replay_requests for zero-signal
    sessions so BarReplayAgent can trigger signal recomputation.

    DB-aware (reads signal_ledger). Never writes. Metrics port: :9128.
    """

    def __init__(self) -> None:
        # config-before-super pattern (Phase 52.2 convention)
        self._settings = Settings()
        self._env_name: str = self._settings.env_name or ""
        super().__init__(name="signal_auditor_agent", metrics_port=9128)

        self._kafka_producer: KafkaProducerClient | None = None
        self._db_pool: asyncpg.Pool | None = None

        # Cache labeled children to avoid .labels() on every cycle
        self._audits_run = _AUDITS_RUN.labels(agent=self.name)
        self._coverage_gaps_published = _COVERAGE_GAPS_PUBLISHED.labels(agent=self.name)
        self._audit_duration = _AUDIT_DURATION.labels(agent=self.name)
        self._audit_errors = _AUDIT_ERRORS.labels(agent=self.name)
        # Dynamic symbol/tf labels — call .labels() at use time
        self._signal_coverage_pct = _SIGNAL_COVERAGE_PCT
        self._pipeline_lag_p50 = _PIPELINE_LAG_P50
        self._pipeline_lag_p95 = _PIPELINE_LAG_P95
        self._cis_mean = _CIS_MEAN
        self._cis_stddev = _CIS_STDDEV

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    @property
    def topics_consumed(self) -> list[str]:
        return []  # AuditorAgent: pulls from DB, no Kafka consumption

    @property
    def topics_produced(self) -> list[str]:
        return [
            topic_signal_audit(self._env_name),
            topic_signal_replay_requests(self._env_name),
        ]

    async def _setup(self) -> None:
        self._db_pool = await asyncpg.create_pool(
            self._settings.database_url, min_size=1, max_size=3
        )
        self._kafka_producer = KafkaProducerClient(
            bootstrap_servers=self._settings.kafka_bootstrap_servers
        )
        await self._kafka_producer.start()
        self.logger.info(
            "signal_auditor_agent.setup_complete",
            topics_produced=self.topics_produced,
        )

    async def _teardown(self) -> None:
        if self._kafka_producer is not None:
            await self._kafka_producer.stop()
        if self._db_pool is not None:
            await self._db_pool.close()

    async def _run(self) -> None:
        """Audit on startup, then every _AUDIT_INTERVAL seconds during market hours."""
        await self._run_audit()

        while self.running:
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=_AUDIT_INTERVAL,
                )
                break
            except TimeoutError:
                pass

            if not self.running:
                break

            instruments = get_active_contracts(self._settings)
            if self._any_session_near_open(instruments):
                await self._run_audit(instruments)

    # ------------------------------------------------------------------
    # Business logic
    # ------------------------------------------------------------------

    async def _run_audit(self, instruments: list | None = None) -> None:
        """Run a full audit cycle using batch_signal_coverage (1 DB round-trip).

        Replaces the old _check_coverage + _check_pipeline_lag two-method pattern
        with a single batch call. Also publishes SignalReplayRequest for sessions
        with zero signals. Catches exceptions to keep the loop alive.
        """
        if instruments is None:
            instruments = get_active_contracts(self._settings)
        try:
            with self._audit_duration.time():
                results: list[SignalCoverageResult] = await batch_signal_coverage(
                    self._db_pool, instruments, list(_COVERAGE_TFS)
                )
                gap_events, replay_requests = self._process_coverage_results(results)
                await self._check_cis_distribution()

            assert self._kafka_producer is not None

            for event in gap_events:
                await self._kafka_producer.publish(
                    topic_signal_audit(self._env_name),
                    event,
                    key=f"{event['symbol']}:{event['tf']}",
                )
                self._coverage_gaps_published.inc()

            for req in replay_requests:
                await self._kafka_producer.publish(
                    topic_signal_replay_requests(self._env_name),
                    req.model_dump(mode="json"),
                    key=f"{req.symbol}:{req.tf}",
                )

            self._audits_run.inc()
            self.logger.info(
                "signal_auditor_agent.audit_complete",
                coverage_gaps_published=len(gap_events),
                replay_requests_published=len(replay_requests),
            )

        except Exception as exc:
            self._audit_errors.inc()
            self.logger.error(
                "signal_auditor_agent.audit_error",
                error=str(exc),
            )

    def _process_coverage_results(
        self,
        results: list[SignalCoverageResult],
    ) -> tuple[list[dict], list[SignalReplayRequest]]:
        """Process batch coverage results: update gauges, build gap events and replay requests.

        Returns:
            gap_events: list of SignalCoverageGapEvent dicts to publish to topic_signal_audit
            replay_requests: list of SignalReplayRequest to publish to topic_signal_replay_requests
        """
        now_utc = datetime.now(UTC)
        gap_events: list[dict] = []
        replay_requests: list[SignalReplayRequest] = []

        for result in results:
            coverage = 1.0 if result.signal_count > 0 else 0.0
            self._signal_coverage_pct.labels(
                agent=self.name, symbol=result.symbol, tf=result.tf
            ).set(coverage)

            if result.p50_lag_ms is not None:
                self._pipeline_lag_p50.labels(
                    agent=self.name, symbol=result.symbol, tf=result.tf
                ).set(result.p50_lag_ms)
            if result.p95_lag_ms is not None:
                self._pipeline_lag_p95.labels(
                    agent=self.name, symbol=result.symbol, tf=result.tf
                ).set(result.p95_lag_ms)
                if result.p95_lag_ms > _LAG_P95_WARN_MS:
                    self.logger.warning(
                        "signal_auditor_agent.lag_threshold_exceeded",
                        symbol=result.symbol,
                        tf=result.tf,
                        p95_ms=round(result.p95_lag_ms, 1),
                        threshold_ms=_LAG_P95_WARN_MS,
                    )

            if result.signal_count == 0:
                date_str = result.session_start.date().isoformat()
                self.logger.warning(
                    "signal_auditor_agent.coverage_gap",
                    symbol=result.symbol,
                    tf=result.tf,
                    session_date=date_str,
                    session_start=result.session_start.isoformat(),
                    session_end=result.session_end.isoformat(),
                )
                gap_events.append(
                    {
                        "symbol": result.symbol,
                        "tf": result.tf,
                        "session_date": date_str,
                        "signals_found": 0,
                        "expected_session_start": result.session_start.isoformat(),
                        "expected_session_end": result.session_end.isoformat(),
                        "ts": now_utc.isoformat(),
                    }
                )
                replay_requests.append(
                    SignalReplayRequest(
                        symbol=result.symbol,
                        tf=result.tf,
                        session_start=result.session_start,
                        session_end=result.session_end,
                    )
                )

        return gap_events, replay_requests

    async def _check_cis_distribution(self) -> None:
        """Observe CIS score mean/stddev per tf over the last _CIS_LOOKBACK_DAYS days.

        A sudden shift in distribution (e.g., mean drops from 0.5 to 0.1) signals
        a bucket feature going missing upstream. Instrumented for Grafana — not
        threshold-alerting in v1.
        """
        assert self._db_pool is not None
        async with self._db_pool.acquire() as conn:
            for tf in _COVERAGE_TFS:
                row = await conn.fetchrow(
                    """
                    SELECT
                      AVG(cis_score)    AS cis_mean,
                      STDDEV(cis_score) AS cis_stddev
                    FROM signal_ledger
                    WHERE timeframe = $1
                      AND feature_ts >= NOW() - ($2 * INTERVAL '1 day')
                    """,
                    tf,
                    _CIS_LOOKBACK_DAYS,
                )
                if row is None or row["cis_mean"] is None:
                    continue

                self._cis_mean.labels(agent=self.name, tf=tf).set(row["cis_mean"])
                if row["cis_stddev"] is not None:
                    self._cis_stddev.labels(agent=self.name, tf=tf).set(row["cis_stddev"])

    def _any_session_near_open(self, instruments: list) -> bool:
        """True if any instrument's session is open or within _RTH_BUFFER_MINUTES."""
        now_utc = datetime.now(UTC)
        buffer = timedelta(minutes=_RTH_BUFFER_MINUTES)
        for instrument in instruments:
            session = instrument.trading_session
            if session.is_open(now_utc):
                return True
            # Check within post-close buffer — yesterday's session_end is the reference
            # because is_open() already returned False (session has ended for today's date)
            yesterday = date_type.today() - timedelta(days=1)
            window = session.session_window_for_date(yesterday)
            if window[1] is not None and now_utc <= window[1] + buffer:
                return True
        return False


if __name__ == "__main__":
    init_tracing("signal_auditor_agent")
    asyncio.run(SignalAuditorAgent().start())
