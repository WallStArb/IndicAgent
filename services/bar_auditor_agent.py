#!/usr/bin/env python3
"""BarAuditorAgent — self-healing gap detection for market_data_ohlcv.

Reads market_data_ohlcv on startup + every 5 minutes during market hours.
Compares actual row counts vs expected counts derived from TradingSession.
Publishes BarGapRequest events to topic_gap_requests for DataProviderAgent
to consume and fetch from IBKR.

DB-aware (reads market_data_ohlcv). Not a ComputeAgent — an AuditorAgent.
Metrics port: :9123

Golden Signals (D-14):
- Traffic: audits_run_total, gap_requests_published_total
- Latency: audit_duration_seconds
- Errors: audit_errors_total
- Saturation: canonical_completeness_pct{symbol,tf} (gauge)

Version: 1.0.0
Last Updated: 2026-03-28
Status: Phase 053.1 Plan 02
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import asyncpg
from prometheus_client import Counter, Gauge, Histogram

from src.config.settings import Settings, get_active_contracts
from src.core.agent.base import BaseAgent
from src.core.kafka_utils import KafkaProducerClient
from src.core.models import TradingSession
from src.core.schemas.market_events import BarGapRequest
from src.core.stream_keys import topic_gap_requests
from src.observability.otel import init_tracing

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_AUDIT_INTERVAL = 300  # seconds between audits (5 minutes)
_COMPLETENESS_THRESHOLD = 0.95  # flag gap if actual/expected < 95%
_DEFAULT_LOOKBACK_DAYS = 3


class BarAuditorAgent(BaseAgent):
    """AuditorAgent: detects gaps in market_data_ohlcv and publishes BarGapRequest.

    Runs gap audit on startup then every 5 minutes during market hours.
    For each active instrument, computes expected 1m bar count per day using
    TradingSession and compares to actual DB count. Publishes BarGapRequest
    to topic_gap_requests for DataProviderAgent to fulfill.

    DB-aware (reads market_data_ohlcv). Not DB-ignorant.
    Metrics port: :9123
    """

    def __init__(self) -> None:
        # config-before-super pattern (Phase 52.2 convention)
        self._settings = Settings()
        self._env_name: str = self._settings.env_name or ""
        super().__init__(name="bar_auditor_agent", metrics_port=9123)

        self._kafka_producer: KafkaProducerClient | None = None
        self._db_pool: asyncpg.Pool | None = None

        # Golden Signals — direct prometheus_client for label support
        _audits_run = Counter(
            "bar_auditor_audits_run_total",
            "Total audit cycles completed",
            ["agent"],
        )
        _gap_requests_published = Counter(
            "bar_auditor_gap_requests_published_total",
            "BarGapRequest events published to Kafka",
            ["agent"],
        )
        _audit_duration = Histogram(
            "bar_auditor_audit_duration_seconds",
            "Wall-clock time for a full audit cycle",
            ["agent"],
        )
        _audit_errors = Counter(
            "bar_auditor_audit_errors_total",
            "Exceptions during audit cycles",
            ["agent"],
        )
        _canonical_completeness = Gauge(
            "bar_auditor_canonical_completeness_pct",
            "Fraction of expected 1m bars present (0.0–1.0)",
            ["agent", "symbol", "tf"],
        )

        # Cache labeled children to avoid dict lookup per audit
        self._audits_run = _audits_run.labels(agent=self.name)
        self._gap_requests_published = _gap_requests_published.labels(agent=self.name)
        self._audit_duration = _audit_duration
        self._audit_errors = _audit_errors
        self._canonical_completeness = _canonical_completeness

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    @property
    def topics_consumed(self) -> list[str]:
        """No Kafka consumption — audit is DB-loop-driven (per D-10)."""
        return []

    @property
    def topics_produced(self) -> list[str]:
        return [topic_gap_requests(self._env_name)]

    async def _setup(self) -> None:
        """Connect asyncpg pool and Kafka producer."""
        self._db_pool = await asyncpg.create_pool(
            self._settings.database_url, min_size=1, max_size=3
        )
        self._kafka_producer = KafkaProducerClient(
            bootstrap_servers=self._settings.kafka_bootstrap_servers
        )
        await self._kafka_producer.start()
        self.logger.info(
            "bar_auditor_agent.setup_complete",
            topics_produced=self.topics_produced,
        )

    async def _teardown(self) -> None:
        """Stop producer and close DB pool."""
        if self._kafka_producer is not None:
            await self._kafka_producer.stop()
        if self._db_pool is not None:
            await self._db_pool.close()

    async def _run(self) -> None:
        """Main loop: audit on startup, then every _AUDIT_INTERVAL seconds.

        Uses _stop_event.wait(timeout=...) for interruptible sleep — SIGTERM
        wakes the wait and exits cleanly.
        """
        # Startup audit (D-12)
        await self._run_audit()

        while self.running:
            try:
                # Interruptible sleep — wakes on SIGTERM/SIGINT
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=_AUDIT_INTERVAL,
                )
                # If we reach here, stop_event was set — exit loop
                break
            except TimeoutError:
                # Normal path: interval elapsed, continue
                pass

            if not self.running:
                break

            # Only audit during market hours for at least one instrument
            if self._any_session_open():
                await self._run_audit()

    # ------------------------------------------------------------------
    # Business logic
    # ------------------------------------------------------------------

    @staticmethod
    def _expected_bars_for_date(session: TradingSession, target_date: date) -> int:
        """Expected 1m bar count for target_date given trading session rules.

        Args:
            session: TradingSession instance (open_time, close_time, timezone, trading_days)
            target_date: calendar date to evaluate

        Returns:
            int: number of expected 1m bars; 0 if non-trading day.

        Session types handled:
        - 24/7 (crypto_24_7): open_time == close_time, 7 trading days → 1440 min
        - 24/6 (fx_24_5): open_time == close_time, 6 trading days → 1440 min on trading days
        - Overnight wrap (futures_24_5): open_time > close_time → count across midnight
        - Same-day (nyse, etc.): open_time < close_time → simple window
        """
        weekday = target_date.weekday()
        if weekday not in session.trading_days:
            return 0

        # All-day session (open_time == close_time)
        if session.open_time == session.close_time:
            return 1440

        # Overnight wrap (e.g., CME futures: 18:00 CST → 17:00 CST next day = 23h = 1380m)
        if session.open_time > session.close_time:
            open_mins = session.open_time.hour * 60 + session.open_time.minute
            close_mins = session.close_time.hour * 60 + session.close_time.minute
            total_mins = (24 * 60 - open_mins) + close_mins
        else:
            # Same-day session (e.g., NYSE: 09:30-16:00 = 390m)
            open_mins = session.open_time.hour * 60 + session.open_time.minute
            close_mins = session.close_time.hour * 60 + session.close_time.minute
            total_mins = close_mins - open_mins

        # Subtract trading breaks
        for brk_start, brk_end in session.trading_breaks:
            brk_start_mins = brk_start.hour * 60 + brk_start.minute
            brk_end_mins = brk_end.hour * 60 + brk_end.minute
            total_mins -= brk_end_mins - brk_start_mins

        return max(0, total_mins)

    async def _detect_gaps(
        self, lookback_days: int = _DEFAULT_LOOKBACK_DAYS
    ) -> list[BarGapRequest]:
        """Detect missing bars across all active instruments for last N days.

        For each instrument and each of the last lookback_days calendar dates:
        - Compute expected 1m bar count from TradingSession
        - Skip non-trading days (expected == 0)
        - Query market_data_ohlcv for actual count
        - If completeness < _COMPLETENESS_THRESHOLD, create BarGapRequest

        Returns:
            list[BarGapRequest]: one request per (instrument, date) that needs gap fill
        """
        instruments = get_active_contracts(self._settings)
        today = date.today()
        gaps: list[BarGapRequest] = []

        for instrument in instruments:
            session = instrument.trading_session
            for days_back in range(1, lookback_days + 1):
                target_date = today - timedelta(days=days_back)
                expected = self._expected_bars_for_date(session, target_date)
                if expected == 0:
                    # Non-trading day — skip
                    continue

                # Date boundaries in UTC
                date_start_utc = datetime(
                    target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=UTC
                )
                date_end_utc = date_start_utc + timedelta(days=1)

                assert self._db_pool is not None
                async with self._db_pool.acquire() as conn:
                    actual = await conn.fetchval(
                        """
                        SELECT COUNT(*)
                        FROM market_data_ohlcv
                        WHERE symbol = $1
                          AND timeframe = '1m'
                          AND timestamp >= $2
                          AND timestamp < $3
                        """,
                        instrument.symbol,
                        date_start_utc,
                        date_end_utc,
                    )

                actual = actual or 0
                completeness = actual / expected

                # Update completeness gauge
                self._canonical_completeness.labels(
                    agent=self.name, symbol=instrument.symbol, tf="1m"
                ).set(completeness)

                if completeness < _COMPLETENESS_THRESHOLD:
                    self.logger.warning(
                        "bar_auditor_agent.gap_detected",
                        symbol=instrument.symbol,
                        date=str(target_date),
                        actual=actual,
                        expected=expected,
                        completeness=round(completeness, 3),
                    )
                    gaps.append(
                        BarGapRequest(
                            symbol=instrument.symbol,
                            tf="1m",
                            start_ts=date_start_utc,
                            end_ts=date_end_utc,
                        )
                    )

        return gaps

    async def _run_audit(self) -> None:
        """Run a single audit cycle: detect gaps and publish BarGapRequest events.

        Catches all exceptions to prevent audit loop from crashing on transient failures.
        """
        try:
            with self._audit_duration.labels(agent=self.name).time():
                gap_requests = await self._detect_gaps()

            for req in gap_requests:
                await self._kafka_producer.publish(
                    topic_gap_requests(self._env_name),
                    req.model_dump(mode="json"),
                    key=req.symbol,
                )
                self._gap_requests_published.inc()

            self._audits_run.inc()
            self.logger.info(
                "bar_auditor_agent.audit_complete",
                gap_requests_published=len(gap_requests),
            )

        except Exception as exc:
            self._audit_errors.labels(agent=self.name).inc()
            self.logger.error(
                "bar_auditor_agent.audit_error",
                error=str(exc),
            )
            # Do not re-raise — audit loop must continue on transient failures

    def _any_session_open(self) -> bool:
        """True if any active instrument's trading session is currently open."""
        now_utc = datetime.now(UTC)
        for instrument in get_active_contracts(self._settings):
            if instrument.trading_session.is_open(now_utc):
                return True
        return False


if __name__ == "__main__":
    init_tracing("bar_auditor_agent")
    asyncio.run(BarAuditorAgent().start())
