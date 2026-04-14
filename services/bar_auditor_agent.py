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

from src.config.settings import Settings, get_active_contracts, invalidate_active_contracts_cache
from src.core.agent.base import BaseAgent
from src.core.bar_accumulator import _TF_MINUTES
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.schemas.market_events import BarGapRequest
from src.core.stream_keys import topic_contract_updates, topic_gap_fill_dlq, topic_gap_requests
from src.observability.metrics import BAR_AUDITOR_GAP_FILL_DLQ_DEPTH, PERSISTENCE_CONSUMER_LAG
from src.observability.otel import init_tracing

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_AUDIT_INTERVAL = 300  # seconds between audits (5 minutes)
# Per-session threshold = session.max_achievable_pct() * _COMPLETENESS_GATE
_COMPLETENESS_GATE = 0.97
_DEFAULT_LOOKBACK_DAYS = 3
# Subset of _TF_MINUTES from bar_accumulator — excludes "1d" because daily bar
# completeness has different semantics (session vs calendar day).
_HTF_TIMEFRAME_MINUTES: dict[str, int] = {k: v for k, v in _TF_MINUTES.items() if k != "1d"}
# Pre-computed for SQL ANY($N) — avoids list() allocation on every audit iteration.
_HTF_TF_NAMES_LIST: list[str] = list(_HTF_TIMEFRAME_MINUTES.keys())

# Module-level metric objects — prevents duplicate registration if the agent class
# is imported more than once in the same process (e.g., unit tests without isolation)
_AUDITS_RUN = Counter(
    "bar_auditor_audits_run_total",
    "Total audit cycles completed",
    ["agent"],
)
_GAP_REQUESTS_PUBLISHED = Counter(
    "bar_auditor_gap_requests_published_total",
    "BarGapRequest events published to Kafka",
    ["agent"],
)
_AUDIT_DURATION = Histogram(
    "bar_auditor_audit_duration_seconds",
    "Wall-clock time for a full audit cycle",
    ["agent"],
)
_AUDIT_ERRORS = Counter(
    "bar_auditor_audit_errors_total",
    "Exceptions during audit cycles",
    ["agent"],
)
_CANONICAL_COMPLETENESS = Gauge(
    "bar_auditor_canonical_completeness_pct",
    "Fraction of expected 1m bars present (0.0–1.0)",
    ["agent", "symbol", "tf"],
)


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
        super().__init__(name="bar_auditor_agent", metrics_port=9123, max_idle_seconds=300)

        self._kafka_producer: KafkaProducerClient | None = None
        self._db_pool: asyncpg.Pool | None = None
        self._contract_consumer: KafkaConsumerClient | None = None

        # Dedup: track (symbol, date_str) pairs already requested today.
        # Prevents the infinite retry loop when IBKR can't fully cover a gap
        # (e.g. CME overnight sessions where actual/expected < 95% permanently).
        # Cleared at UTC midnight each audit cycle.
        self._requested_today: set[tuple[str, str]] = set()
        self._requested_today_date: str = ""  # YYYY-MM-DD of last clear

        # Gap request dedup: (symbol, tf, date_str) — cleared every 24h
        self._seen_gap_requests: set[tuple[str, str, str]] = set()
        self._seen_gap_requests_date: str = ""

        # Cache labeled children — avoids .labels() lookup on every audit cycle
        self._audits_run = _AUDITS_RUN.labels(agent=self.name)
        self._gap_requests_published = _GAP_REQUESTS_PUBLISHED.labels(agent=self.name)
        self._audit_duration = _AUDIT_DURATION.labels(agent=self.name)
        self._audit_errors = _AUDIT_ERRORS.labels(agent=self.name)
        # Dynamic symbol/tf labels — cannot pre-cache; call .labels() at use time
        self._canonical_completeness = _CANONICAL_COMPLETENESS

        # Module-level counter (already registered in metrics.py via Plan 1)
        self._gap_fill_dlq_depth = BAR_AUDITOR_GAP_FILL_DLQ_DEPTH

    # ------------------------------------------------------------------
    # BaseAgent interface
    # ------------------------------------------------------------------

    @property
    def topics_consumed(self) -> list[str]:
        """Subscribe to contract updates for cache invalidation."""
        return [topic_contract_updates(self._env_name)]

    @property
    def topics_produced(self) -> list[str]:
        return [topic_gap_requests(self._env_name)]

    async def _setup(self) -> None:
        """Connect asyncpg pool, Kafka producer, and contract update consumer."""
        self._db_pool = await asyncpg.create_pool(
            self._settings.database_url, min_size=1, max_size=3
        )
        self._kafka_producer = KafkaProducerClient(
            bootstrap_servers=self._settings.kafka_bootstrap_servers
        )
        await self._kafka_producer.start()
        self._contract_consumer = KafkaConsumerClient(
            topic_contract_updates(self._env_name),
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            group_id="bar_auditor_contract_updates_consumer",
            auto_offset_reset="latest",
        )
        await self._contract_consumer.start()
        self.logger.info(
            "bar_auditor_agent.setup_complete",
            topics_produced=self.topics_produced,
            topics_consumed=self.topics_consumed,
        )

    async def _report_consumer_lag(self) -> None:
        """Report consumer lag until stop event. Auditor — no buffer accumulation."""
        while not self._stop_event.is_set():
            PERSISTENCE_CONSUMER_LAG.labels(agent_id=self.name).set(0)
            await asyncio.sleep(15)

    async def _teardown(self) -> None:
        """Stop producer, contract consumer, and close DB pool."""
        if self._contract_consumer is not None:
            await self._contract_consumer.stop()
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
        await self._drain_contract_updates()
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

            await self._drain_contract_updates()
            instruments = get_active_contracts(self._settings)
            if self._any_session_open(instruments):
                await self._run_audit(instruments)

    # ------------------------------------------------------------------
    # Business logic
    # ------------------------------------------------------------------

    async def _drain_contract_updates(self) -> None:
        """Check for ContractUpdateEvent messages and invalidate contract cache.

        Non-blocking drain — uses getmany(timeout_ms=0) to return immediately
        with any buffered messages. Does NOT block if no messages are pending.
        Topic absence degrades gracefully to TTL-only cache (60s lag).
        """
        if self._contract_consumer is None:
            return
        try:
            records = await self._contract_consumer.getmany(timeout_ms=0, max_records=100)
            count = sum(len(msgs) for msgs in records.values())
            if count > 0:
                self._record_message_consumed()  # Track liveness for stall detection
                invalidate_active_contracts_cache()
                self.logger.info(
                    "bar_auditor_agent.contract_update_received",
                    count=count,
                )
        except TimeoutError:
            pass  # Expected — no messages available
        except Exception as exc:
            self.logger.debug(
                "bar_auditor_agent.contract_drain_error",
                error=str(exc),
            )

    async def _detect_gaps(
        self,
        instruments: list,
        lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    ) -> list[BarGapRequest]:
        """Detect missing bars across all active instruments for last N days.

        For each instrument and each of the last lookback_days calendar dates:
        - Compute session-aligned UTC window from session_window_for_date()
        - Skip non-trading days (window returns (None, None))
        - Query market_data_ohlcv for actual count within session window
        - Derive per-session threshold: session.max_achievable_pct() * _COMPLETENESS_GATE
        - If completeness < threshold, create BarGapRequest
        - Observe HTF completeness metrics (5m/15m/1h/4h) — log warnings, NO gap requests

        Returns:
            list[BarGapRequest]: one request per (instrument, date) that needs gap fill
        """
        today = date.today()
        gaps: list[BarGapRequest] = []

        assert self._db_pool is not None
        async with self._db_pool.acquire() as conn:
            for instrument in instruments:
                session = instrument.trading_session
                threshold = session.max_achievable_pct() * _COMPLETENESS_GATE
                for days_back in range(1, lookback_days + 1):
                    target_date = today - timedelta(days=days_back)

                    # Session-aligned UTC window — also gates non-trading days
                    window = session.session_window_for_date(target_date)
                    if window[0] is None or window[1] is None:
                        continue  # Non-trading day — skip
                    date_start_utc, date_end_utc = window

                    # Derive expected bars from the window we already have,
                    # avoiding a second session_window_for_date() call inside
                    # expected_bars_for_date().
                    total_minutes = int((date_end_utc - date_start_utc).total_seconds() / 60)
                    expected = max(0, total_minutes - session._break_minutes())
                    if expected == 0:
                        continue

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

                    self._canonical_completeness.labels(
                        agent=self.name, symbol=instrument.symbol, tf="1m"
                    ).set(completeness)

                    if completeness < threshold:
                        # UPSERT gap row to market_data_gaps table
                        await self._upsert_market_data_gap(
                            conn,
                            instrument.symbol,
                            "1m",
                            date_start_utc,
                            expected,
                            expected - actual,
                        )
                        # Dedup: skip if already requested today (prevents infinite
                        # retry loop for gaps IBKR can't fully fill, e.g. CME overnight)
                        today_str = str(today)
                        if self._requested_today_date != today_str:
                            self._requested_today.clear()
                            self._requested_today_date = today_str
                        gap_key = (instrument.symbol, str(target_date))
                        if gap_key in self._requested_today:
                            continue

                        self.logger.warning(
                            "bar_auditor_agent.gap_detected",
                            symbol=instrument.symbol,
                            date=str(target_date),
                            actual=actual,
                            expected=expected,
                            completeness=round(completeness, 3),
                            threshold=round(threshold, 3),
                        )
                        gaps.append(
                            BarGapRequest(
                                symbol=instrument.symbol,
                                tf="1m",
                                start_ts=date_start_utc,
                                end_ts=date_end_utc,
                            )
                        )
                        self._requested_today.add(gap_key)

                    # Resolve gap if completeness reached 100%
                    elif completeness >= 1.0:
                        await self._resolve_market_data_gap(
                            conn, instrument.symbol, "1m", date_start_utc
                        )

                    # HTF completeness — observe metrics, DO NOT issue gap requests.
                    # Single GROUP BY query replaces N separate COUNT(*) queries.
                    htf_rows = await conn.fetch(
                        """
                        SELECT timeframe, COUNT(*) AS cnt
                        FROM market_data_ohlcv
                        WHERE symbol = $1
                          AND timeframe = ANY($2)
                          AND timestamp >= $3
                          AND timestamp < $4
                        GROUP BY timeframe
                        """,
                        instrument.symbol,
                        _HTF_TF_NAMES_LIST,
                        date_start_utc,
                        date_end_utc,
                    )
                    htf_counts = {r["timeframe"]: r["cnt"] for r in htf_rows}

                    for tf_name, tf_minutes in _HTF_TIMEFRAME_MINUTES.items():
                        expected_htf = expected // tf_minutes
                        if expected_htf == 0:
                            continue
                        actual_htf = htf_counts.get(tf_name, 0)
                        completeness_htf = actual_htf / expected_htf
                        self._canonical_completeness.labels(
                            agent=self.name, symbol=instrument.symbol, tf=tf_name
                        ).set(completeness_htf)
                        if completeness_htf < threshold:
                            self.logger.warning(
                                "bar_auditor_agent.htf_gap_detected",
                                symbol=instrument.symbol,
                                tf=tf_name,
                                date=str(target_date),
                                actual=actual_htf,
                                expected=expected_htf,
                                completeness=round(completeness_htf, 3),
                                threshold=round(threshold, 3),
                            )

        return gaps

    async def _run_audit(self, instruments: list | None = None) -> None:
        """Run a single audit cycle: detect gaps and publish BarGapRequest events.

        Catches all exceptions to prevent audit loop from crashing on transient failures.
        """
        if instruments is None:
            instruments = get_active_contracts(self._settings)
        try:
            with self._audit_duration.time():
                gap_requests = await self._detect_gaps(instruments)

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
            self._audit_errors.inc()
            self.logger.error(
                "bar_auditor_agent.audit_error",
                error=str(exc),
            )
            # Do not re-raise — audit loop must continue on transient failures

    # -- market_data_gaps write path -------------------------------------------

    async def _upsert_market_data_gap(
        self,
        conn: asyncpg.Connection,
        symbol: str,
        tf: str,
        gap_start_ts: datetime,
        bars_expected: int,
        bars_missing: int,
    ) -> None:
        """UPSERT a gap row. Updates bars_missing if row already exists."""
        await conn.execute(
            """
            INSERT INTO market_data_gaps
                (symbol, tf, gap_start_ts, bars_expected, bars_missing, detected_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (symbol, tf, gap_start_ts)
            DO UPDATE SET
                bars_missing = EXCLUDED.bars_missing,
                detected_at  = EXCLUDED.detected_at
            """,
            symbol,
            tf,
            gap_start_ts,
            bars_expected,
            bars_missing,
            datetime.now(UTC),
        )

    async def _resolve_market_data_gap(
        self,
        conn: asyncpg.Connection,
        symbol: str,
        tf: str,
        gap_start_ts: datetime,
    ) -> None:
        """Mark an open gap as resolved (completeness reached 100%)."""
        existing_id = await conn.fetchval(
            """
            SELECT id FROM market_data_gaps
            WHERE symbol = $1 AND tf = $2 AND gap_start_ts = $3
              AND resolved_at IS NULL
            """,
            symbol,
            tf,
            gap_start_ts,
        )
        if existing_id is None:
            return
        now = datetime.now(UTC)
        await conn.execute(
            """
            UPDATE market_data_gaps
            SET resolved_at = $1, gap_end_ts = $1
            WHERE id = $2
            """,
            now,
            existing_id,
        )

    async def _publish_gap_fill_dlq(
        self,
        symbol: str,
        tf: str,
        start_ts: datetime,
        end_ts: datetime,
        retry_count: int,
        error: str,
    ) -> None:
        """Publish unresolvable gap request to DLQ after retry exhaustion."""
        payload = {
            "symbol": symbol,
            "tf": tf,
            "start_ts": start_ts.isoformat(),
            "end_ts": end_ts.isoformat(),
            "retry_count": retry_count,
            "error": error,
        }
        await self._kafka_producer.publish(
            topic_gap_fill_dlq(self._env_name),
            payload,
            key=symbol,
        )
        self._gap_fill_dlq_depth.inc()
        self.logger.warning(
            "bar_auditor_agent.gap_fill_dlq",
            symbol=symbol,
            tf=tf,
            retry_count=retry_count,
            error=error,
        )

    def _any_session_open(self, instruments: list) -> bool:
        """True if any active instrument's trading session is currently open."""
        now_utc = datetime.now(UTC)
        for instrument in instruments:
            if instrument.trading_session.is_open(now_utc):
                return True
        return False


if __name__ == "__main__":
    init_tracing("bar_auditor_agent")
    asyncio.run(BarAuditorAgent().start())
