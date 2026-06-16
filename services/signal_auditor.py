#!/usr/bin/env python3
"""SignalAuditor — coverage validation for signal_events.

Runs a 5-minute audit loop during market hours. Checks:
1. Signal coverage per (symbol, tf) — at least one signal fired in the last session
2. CIS score distribution (mean/stddev) per tf over a rolling 5-day window

Emits SignalCoverageGapEvent to intelligence.signal.audit on coverage gaps.
DB-aware (reads signal_events). AuditorAgent role — read-only, never writes.

Phase 130: the P50/P95 lag metrics and lag-check method are removed (schema migration
dropped the column from the old monolith). Coverage query now reads signal_events
directly (tf column, ts column).
"""

from __future__ import annotations

import asyncio
import time as _time
from datetime import UTC, date, datetime, timedelta

import _path_bootstrap  # noqa: F401 — project root on sys.path
import asyncpg
from opentelemetry import metrics as _otel_metrics

from src.config.settings import get_active_contracts
from src.core.agent.base import BaseDaemon
from src.core.database_manager import create_pool as create_db_pool
from src.core.kafka_utils import KafkaProducerClient
from src.core.stream_keys import topic_signal_audit

# Constants
_AUDIT_INTERVAL = 300  # 5 minutes between audit cycles
_RTH_BUFFER_MINUTES = 30  # run audits RTH + 30 min buffer
_COVERAGE_TFS: tuple[str, ...] = ("1m", "5m", "15m", "1h")  # Timeframes audited for signal coverage
_CIS_LOOKBACK_DAYS = 5  # Rolling window for CIS distribution check

# ---------------------------------------------------------------------------
# Module-level OTel metrics
# ---------------------------------------------------------------------------

_sa_meter = _otel_metrics.get_meter("indicagent")
_AUDITS_RUN = _sa_meter.create_counter(
    "signal_auditor_audits_run_total",
    description="Total audit cycles completed",
)
_COVERAGE_GAPS_PUBLISHED = _sa_meter.create_counter(
    "signal_auditor_coverage_gaps_published_total",
    description="SignalCoverageGapEvents published to Kafka",
)
_AUDIT_DURATION = _sa_meter.create_histogram(
    "signal_auditor_audit_duration_seconds",
    description="Wall-clock time for a full audit cycle",
)
_AUDIT_ERRORS = _sa_meter.create_counter(
    "signal_auditor_audit_errors_total",
    description="Exceptions during audit cycles",
)
_SIGNAL_COVERAGE_PCT = _sa_meter.create_up_down_counter(
    "signal_coverage_pct",
    description="1.0 if ≥1 signal fired in last session, 0.0 otherwise",
)
_CIS_MEAN = _sa_meter.create_up_down_counter(
    "signal_cis_mean",
    description="Mean cis_score per tf over rolling 5-day window",
)
_CIS_STDDEV = _sa_meter.create_up_down_counter(
    "signal_cis_stddev",
    description="Stddev of cis_score per tf over rolling 5-day window",
)


class SignalAuditor(BaseDaemon):
    """Validates signal coverage via periodic audits.

    Runs a 5-minute audit loop during market hours (plus 30-min buffer).
    Emits SignalCoverageGapEvent to intelligence.signal.audit on coverage gaps.
    Reads signal_events directly (AuditorAgent role — never writes).

    Phase 130: coverage query updated to signal_events (tf/ts columns).
    Phase 130: P50/P95 lag check removed (column dropped from schema).
    APR key feature.signal_auditor.audit_lookback_hours governs any future
    time-windowed audit query (loaded from config_service in _setup()).
    """

    def __init__(self) -> None:
        super().__init__(max_idle_seconds=600)
        self._kafka_producer: KafkaProducerClient | None = None
        self._db_pool: asyncpg.Pool | None = None
        # APR-backed audit lookback — loaded in _setup() from config_service.
        # Default matches APR seed value (migration 142).
        self._audit_lookback_hours: int = 1

        self._agent_attrs = {"agent": self.name}

    # ------------------------------------------------------------------
    # BaseDaemon interface
    # ------------------------------------------------------------------

    @property
    def topics_consumed(self) -> list[str]:
        return []  # AuditorAgent: pulls from DB, no Kafka consumption

    @property
    def topics_produced(self) -> list[str]:
        return [topic_signal_audit(self.env_name)]

    async def _setup(self) -> None:
        # Load APR-backed audit configuration (feature.signal_auditor.* namespace,
        # seeded in migration 142). get_config() reads from the OPS snapshot loaded
        # by BaseDaemon._pre_setup_config_load() before _setup() is called.
        self._audit_lookback_hours = int(
            self.get_config("feature.signal_auditor.audit_lookback_hours", default=1)
        )

        self._db_pool = await create_db_pool(self.settings.database_url, min_size=1, max_size=3)
        self._kafka_producer = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers
        )
        await self._kafka_producer.start()
        self.logger.info(
            "signal_auditor.setup_complete",
            topics_produced=self.topics_produced,
            audit_lookback_hours=self._audit_lookback_hours,
        )

    async def _teardown(self) -> None:
        if self._kafka_producer is not None:
            await self._kafka_producer.stop()
        if self._db_pool is not None:
            await self._db_pool.close()

    async def _run(self) -> None:
        """Audit on startup, then every _AUDIT_INTERVAL seconds during market hours."""
        # lag_task created by BaseDaemon.start() at line 155
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

            instruments = get_active_contracts(self.settings)
            if self._any_session_near_open(instruments):
                await self._run_audit(instruments)

    # ------------------------------------------------------------------
    # Business logic
    # ------------------------------------------------------------------

    async def _run_audit(self, instruments: list | None = None) -> None:
        """Run a full audit cycle.

        Catches exceptions to keep the loop alive even on transient failures.
        """
        if instruments is None:
            instruments = get_active_contracts(self.settings)
        try:
            _t0 = _time.monotonic()
            gap_events = await self._check_coverage(instruments)
            await self._check_cis_distribution()
            _AUDIT_DURATION.record(_time.monotonic() - _t0, self._agent_attrs)

            assert self._kafka_producer is not None
            for event in gap_events:
                await self._kafka_producer.publish(
                    topic_signal_audit(self.env_name),
                    event,
                    key=f"{event['symbol']}:{event['tf']}",
                )
                _COVERAGE_GAPS_PUBLISHED.add(1, self._agent_attrs)

            _AUDITS_RUN.add(1, self._agent_attrs)
            self.logger.info(
                "signal_auditor.audit_complete",
                coverage_gaps_published=len(gap_events),
            )

        except Exception as error:
            _AUDIT_ERRORS.add(1, self._agent_attrs)
            self.logger.error(
                "signal_auditor.audit_error",
                error=str(error),
            )

    async def _check_coverage(self, instruments: list) -> list[dict]:
        """Check signal coverage for the last completed trading session.

        For each active symbol × _COVERAGE_TFS:
        - Find the last completed session window via session_window_for_date(yesterday)
        - Count signal_events rows in that window (ts column, tf column)
        - Set signal_coverage_pct gauge (1.0 covered, 0.0 gap)
        - Return SignalCoverageGapEvent dicts for any (symbol, tf) with 0 signals

        Phase 130: reads signal_events directly (signal_ledger uses feature_ts
        which is unavailable in the 3-table schema; signal_events uses ts for fire time).

        Returns:
            List of gap event dicts for missing signal coverage.
        """
        gap_events: list[dict] = []
        yesterday = date.today() - timedelta(days=1)
        now_utc = datetime.now(UTC)

        assert self._db_pool is not None
        async with self._db_pool.acquire() as conn:
            for instrument in instruments:
                session = instrument.trading_session
                window = session.session_window_for_date(yesterday)
                if window[0] is None or window[1] is None:
                    continue  # Non-trading day

                session_start, session_end = window

                for tf in _COVERAGE_TFS:
                    count = await conn.fetchval(
                        """
                        SELECT COUNT(*)
                        FROM signal_events
                        WHERE symbol = $1
                          AND tf = $2
                          AND ts >= $3
                          AND ts < $4
                        """,
                        instrument.symbol,
                        tf,
                        session_start,
                        session_end,
                    )
                    count = count or 0
                    coverage = 1.0 if count > 0 else 0.0

                    _SIGNAL_COVERAGE_PCT.add(
                        coverage, {"agent": self.name, "symbol": instrument.symbol, "tf": tf}
                    )

                    if count == 0:
                        self.logger.warning(
                            "signal_auditor.coverage_gap",
                            symbol=instrument.symbol,
                            tf=tf,
                            session_date=str(yesterday),
                            session_start=session_start.isoformat(),
                            session_end=session_end.isoformat(),
                        )
                        gap_events.append(
                            {
                                "symbol": instrument.symbol,
                                "tf": tf,
                                "session_date": str(yesterday),
                                "signals_found": 0,
                                "expected_session_start": session_start.isoformat(),
                                "expected_session_end": session_end.isoformat(),
                                "ts": now_utc.isoformat(),
                            }
                        )

        return gap_events

    async def _check_cis_distribution(self) -> None:
        """Observe CIS score mean/stddev per tf over the last _CIS_LOOKBACK_DAYS days.

        A sudden shift in distribution (e.g., mean drops from 0.5 to 0.1) signals
        a bucket feature going missing upstream. Instrumented for Grafana — not
        threshold-alerting in v1.

        Phase 130: query updated to use signal_events (se.tf, se.ts columns) instead
        of signal_ledger (feature_ts / feature_tf columns are dropped).
        """
        assert self._db_pool is not None
        async with self._db_pool.acquire() as conn:
            for tf in _COVERAGE_TFS:
                row = await conn.fetchrow(
                    """
                    SELECT
                      AVG((tf_sig.value->>'cis_score')::float)    AS cis_mean,
                      STDDEV((tf_sig.value->>'cis_score')::float) AS cis_stddev
                    FROM signal_events se
                    JOIN intelligence_features f ON f.symbol = se.symbol AND f.ts = se.ts AND f.tf = se.tf
                    JOIN LATERAL jsonb_array_elements(f.trading_signals) AS tf_sig(value)
                        ON tf_sig.value->>'signal_id' = se.signal_id::text
                    WHERE se.tf = $1
                      AND se.ts >= NOW() - ($2 * INTERVAL '1 day')
                    """,
                    tf,
                    _CIS_LOOKBACK_DAYS,
                )
                if row is None or row["cis_mean"] is None:
                    continue

                _CIS_MEAN.add(row["cis_mean"], {"agent": self.name, "tf": tf})
                if row["cis_stddev"] is not None:
                    _CIS_STDDEV.add(row["cis_stddev"], {"agent": self.name, "tf": tf})

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
            yesterday = date.today() - timedelta(days=1)
            window = session.session_window_for_date(yesterday)
            if window[1] is not None and now_utc <= window[1] + buffer:
                return True
        return False


if __name__ == "__main__":
    asyncio.run(SignalAuditor().start())
