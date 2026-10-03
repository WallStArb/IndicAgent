#!/usr/bin/env python3
"""BarAuditor — self-healing gap detection for market_data_ohlcv.

Reads market_data_ohlcv on startup + every 5 minutes during market hours.
Compares actual row counts vs expected counts derived from TradingSession.
Publishes BarGapRequest events to topic_gap_requests for DataProviderAgent
to consume and fetch from IBKR.

DB-aware (reads market_data_ohlcv). Not a ComputeAgent — an AuditorAgent.

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
import time as _time
from datetime import UTC, date, datetime, timedelta
from typing import Any, NamedTuple

import _path_bootstrap  # noqa: F401 — project root on sys.path
import asyncpg
from opentelemetry import metrics as _otel_metrics

from services._batch_utils import load_apr_dict_async
from src.config.settings import get_active_contracts, invalidate_active_contracts_cache
from src.core.agent.base import BaseDaemon
from src.core.bar_accumulator import _TF_MINUTES
from src.core.database_manager import create_pool as create_db_pool
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.schemas.market_events import BarGapRequest
from src.core.service_utils import format_iso_ts
from src.core.stream_keys import (
    topic_contract_updates,
    topic_gap_fill_dlq,
    topic_gap_requests,
)
from src.intelligence.bars.gap_plan import (
    ANSWERED_OUTCOMES,
    COVERAGE_ROUTE,
    COVERAGE_WHAT_TO_SHOW,
    AnsweredWindows,
    expected_grid_slots,
    fresh_empty_span,
    plan_gaps,
)
from src.observability.metrics import BAR_AUDITOR_GAP_FILL_DLQ_DEPTH
from src.observability.spans import observed_span

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
# All timeframes queried in the bulk audit — 1m for gap detection + HTF for metrics.
_ALL_AUDIT_TFS: list[str] = ["1m"] + _HTF_TF_NAMES_LIST

# Plan 185-18 task 1a: these HTF timeframes' gap alarms come from the shared
# planner (src/intelligence/bars/gap_plan.py) -- the same plan the fetch
# pipeline computes over its psycopg readers, so the auditor's count IS the
# planner's count for the same record. 4h stays on the count-only warning
# until its own migration.
_HTF_PLAN_TFS = ("5m", "15m", "1h")
# Where each planner tf's stored observations live (mirrors _d1_gaps'
# _SERIES_TABLE: the archive for the archive-bound 15m/1h, the grid for 5m).
_HTF_STORED_TABLES = {
    "5m": "market_data_ohlcv",
    "15m": "ohlcv_intraday_raw_archive",
    "1h": "ohlcv_intraday_raw_archive",
}
_SELECT_HTF_STORED_SQL = """
SELECT timestamp FROM {table}
WHERE symbol = $1 AND timeframe = $2 AND timestamp >= $3 AND timestamp <= $4
"""
_SELECT_HTF_ANSWERED_SQL = """
SELECT r.window_start, r.window_end
FROM ohlcv_request r
WHERE r.symbol = $1 AND r.timeframe = $2 AND r.route = $3 AND r.what_to_show = $4
  AND r.outcome = ANY($5::text[]) AND r.window_start IS NOT NULL
  AND (
    r.outcome = 'no_data'
    OR EXISTS (
      SELECT 1 FROM {table} m
      WHERE m.symbol = r.symbol AND m.timeframe = r.timeframe
        AND m.timestamp >= r.window_start AND m.timestamp < r.window_end
    )
  )
ORDER BY r.window_start
"""
_SELECT_HTF_EMPTY_SPAN_SQL = """
SELECT empty_from, empty_through, verified_at, n_confirming_chunks
FROM ohlcv_empty_history
WHERE symbol = $1 AND timeframe = $2 AND provider = 'ibkr'
"""
# The two APR keys the planner's span gate reads -- the same keys the
# pipeline's loaders overlay (empty-history reverify age; the provider's own
# no-data confirmation threshold).
_HTF_SPAN_APR_KEYS = [
    "infra.backfill.empty_history_reverify_days",
    "infra.ibkr.no_data_confirmation_chunks",
]

# Retry schedule: after N-th attempt, wait this many seconds before re-emitting.
# Index 0 = after 1st attempt (5 min), index 1 = after 2nd attempt (30 min).
_RETRY_BACKOFFS_SECS: tuple[int, ...] = (300, 1800)
MAX_GAP_RETRIES: int = 3
_POST_ROLL_SUPPRESS_SECS: int = 7200  # 2 hours


class _AuditWindow(NamedTuple):
    instrument: object
    target_date: date
    date_start_utc: datetime
    date_end_utc: datetime
    expected: int


# Module-level OTel metrics
_ba_meter = _otel_metrics.get_meter("indicagent")
_AUDITS_RUN = _ba_meter.create_counter(
    "bar_auditor_audits_run_total",
    description="Total audit cycles completed",
)
_GAP_REQUESTS_PUBLISHED = _ba_meter.create_counter(
    "bar_auditor_gap_requests_published_total",
    description="BarGapRequest events published to Kafka",
)
_AUDIT_DURATION = _ba_meter.create_histogram(
    "bar_auditor_audit_duration_seconds",
    description="Wall-clock time for a full audit cycle",
)
_AUDIT_ERRORS = _ba_meter.create_counter(
    "bar_auditor_audit_errors_total",
    description="Exceptions during audit cycles",
)
_CANONICAL_COMPLETENESS = _ba_meter.create_up_down_counter(
    "bar_auditor_canonical_completeness_pct",
    description="Fraction of expected 1m bars present (0.0–1.0)",
)


class BarAuditor(BaseDaemon):
    """AuditorAgent: detects gaps in market_data_ohlcv and publishes BarGapRequest.

    Runs gap audit on startup then every 5 minutes during market hours.
    For each active instrument, computes expected 1m bar count per day using
    TradingSession and compares to actual DB count. Publishes BarGapRequest
    to topic_gap_requests for DataProviderAgent to fulfill.

    DB-aware (reads market_data_ohlcv). Not DB-ignorant.
    """

    def __init__(self) -> None:
        super().__init__(max_idle_seconds=300)
        self._kafka_producer: KafkaProducerClient | None = None
        self._db_pool: asyncpg.Pool | None = None
        self._contract_consumer: KafkaConsumerClient | None = None
        # old_contract -> roll_detection_ts: suppress gap requests for 2h post-roll
        self._post_roll_suppression: dict[str, datetime] = {}

        self._agent_attrs = {"agent": self.name}
        # Module-level counter (already registered in metrics.py via Plan 1)
        self._gap_fill_dlq_depth = BAR_AUDITOR_GAP_FILL_DLQ_DEPTH

    # ------------------------------------------------------------------
    # BaseDaemon interface
    # ------------------------------------------------------------------

    @property
    def topics_consumed(self) -> list[str]:
        return [
            topic_contract_updates(self.env_name),
        ]

    @property
    def topics_produced(self) -> list[str]:
        return [topic_gap_requests(self.env_name)]

    async def _setup(self) -> None:
        """Connect asyncpg pool, Kafka producer, and contract update consumer."""
        self._db_pool = await create_db_pool(self.settings.database_url, min_size=1, max_size=3)
        self._kafka_producer = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers
        )
        await self._kafka_producer.start()
        self._contract_consumer = KafkaConsumerClient(
            topic_contract_updates(self.env_name),
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id="bar_auditor_contract_updates_consumer",
            auto_offset_reset="latest",
        )
        await self._contract_consumer.start()
        self.logger.info(
            "bar_auditor.setup_complete",
            topics_produced=self.topics_produced,
            topics_consumed=self.topics_consumed,
        )

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
            instruments = get_active_contracts(self.settings, dimension="live")
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
            count = len(records)
            if count > 0:
                self._record_message_consumed()  # Track liveness for stall detection
                invalidate_active_contracts_cache()
                self.logger.info(
                    "bar_auditor.contract_update_received",
                    count=count,
                )
        except TimeoutError:
            pass  # Expected — no messages available
        except Exception as error:
            self.logger.debug(
                "bar_auditor.contract_drain_error",
                error=str(error),
            )

    async def _plan_htf_gaps(
        self,
        conn: asyncpg.Connection,
        instrument: Any,
        tf: str,
        win_start: datetime,
        win_end: datetime,
        *,
        now: datetime,
        reverify_days: int,
        min_confirmations: int,
    ) -> list[tuple[datetime, datetime]]:
        """The shared planner's gap plan for (symbol, tf) over one audit window.

        Plan 185-18 task 1a: the auditor's HTF alarm count IS plan_gaps' output
        for the same inputs the fetch pipeline reads -- expected slots minus
        stored observations minus recorded coverage, the provider-verified
        empty span folded in under its freshness gate. Same rule as the
        pipeline's _d1_gaps wrapper; these asyncpg readers are local because
        services/ does not import from scripts/.
        """
        table = _HTF_STORED_TABLES[tf]
        stored_rows = await conn.fetch(
            _SELECT_HTF_STORED_SQL.format(table=table),
            instrument.symbol,
            tf,
            win_start,
            win_end,
        )
        stored = [r[0] for r in stored_rows]
        answered_rows = await conn.fetch(
            _SELECT_HTF_ANSWERED_SQL.format(table=table),
            instrument.symbol,
            tf,
            COVERAGE_ROUTE,
            COVERAGE_WHAT_TO_SHOW,
            list(ANSWERED_OUTCOMES),
        )
        answered = AnsweredWindows.from_rows([(r[0], r[1]) for r in answered_rows])
        spans: list[tuple[datetime, datetime]] = []
        empty_rows = await conn.fetch(_SELECT_HTF_EMPTY_SPAN_SQL, instrument.symbol, tf)
        if empty_rows:
            empty_from, empty_through, verified_at, n_confirming = empty_rows[0]
            span = fresh_empty_span(
                empty_from,
                empty_through,
                verified_at,
                n_confirming,
                now=now,
                reverify_days=reverify_days,
                min_confirmations=min_confirmations,
            )
            if span is not None:
                spans = [span]
        slots = expected_grid_slots(
            instrument.session_id, instrument.exchange, tf, win_start, win_end
        )
        return plan_gaps(
            slots,
            stored,
            answered,
            timedelta(minutes=_TF_MINUTES[tf]),
            run_end=win_end,
            empty_ranges=spans,
        )

    async def _detect_gaps(
        self,
        instruments: list,
        lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    ) -> list[BarGapRequest]:
        """Detect missing bars across all active instruments for last N days.

        Builds all session windows in Python first, then issues a single bulk
        UNNEST query to fetch bar counts for every (symbol, window, timeframe)
        in one round trip — replacing the previous N×M per-window query loop.

        Returns:
            list[BarGapRequest]: one request per (instrument, session) that needs gap fill
        """
        today = date.today()

        windows: list[_AuditWindow] = []
        for instrument in instruments:
            session = instrument.trading_session
            for days_back in range(1, lookback_days + 1):
                target_date = today - timedelta(days=days_back)
                window = session.session_window_for_date(target_date)
                if window[0] is None or window[1] is None:
                    continue  # Non-trading day
                date_start_utc, date_end_utc = window
                total_minutes = int((date_end_utc - date_start_utc).total_seconds() / 60)
                expected = max(0, total_minutes - session._break_minutes())
                if expected == 0:
                    continue
                windows.append(
                    _AuditWindow(instrument, target_date, date_start_utc, date_end_utc, expected)
                )

        if not windows:
            return []

        # Single bulk query — all windows × all timeframes in one round trip.
        # UNNEST expands the parallel arrays into a derived table of (sym, win_start, win_end).
        # TimescaleDB prunes chunks by the min/max of all win_start/win_end values.
        syms = [w.instrument.symbol for w in windows]
        starts = [w.date_start_utc for w in windows]
        ends = [w.date_end_utc for w in windows]

        assert self._db_pool is not None, "DB pool not initialized — call _setup()"
        async with self._db_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT s.sym, s.win_start, ohlcv.timeframe, COUNT(*) AS cnt
                FROM UNNEST($1::text[], $2::timestamptz[], $3::timestamptz[])
                     AS s(sym, win_start, win_end)
                JOIN market_data_ohlcv ohlcv
                  ON ohlcv.symbol    = s.sym
                 AND ohlcv.timestamp >= s.win_start
                 AND ohlcv.timestamp <  s.win_end
                 AND ohlcv.timeframe  = ANY($4)
                GROUP BY s.sym, s.win_start, ohlcv.timeframe
                """,
                syms,
                starts,
                ends,
                _ALL_AUDIT_TFS,
            )

            counts: dict[tuple[str, datetime, str], int] = {
                (r["sym"], r["win_start"], r["timeframe"]): r["cnt"] for r in rows
            }

            # Plan 185-18: the shared planner's span gate reads the same two APR
            # keys the pipeline's loaders overlay. A read failure degrades to
            # (0, 0) -- nothing is ever suppressed, so the worst case is a false
            # alarm, never a silent miss.
            now_utc = datetime.now(UTC)
            try:
                apr = await load_apr_dict_async(conn, list(_HTF_SPAN_APR_KEYS))
                span_reverify_days = int(apr[_HTF_SPAN_APR_KEYS[0]])
                span_min_confirmations = int(apr[_HTF_SPAN_APR_KEYS[1]])
            except Exception as error:
                span_reverify_days = 0
                span_min_confirmations = 0
                self.logger.warning(
                    "bar_auditor.htf_span_apr_unavailable",
                    error=str(error),
                    reverify_days=span_reverify_days,
                    min_confirmations=span_min_confirmations,
                )

            gaps: list[BarGapRequest] = []
            for w in windows:
                sym = w.instrument.symbol
                if self._is_roll_suppressed(sym):
                    self.logger.debug(
                        "bar_auditor.gap_suppressed_post_roll",
                        symbol=sym,
                        date=str(w.target_date),
                    )
                    continue
                session = w.instrument.trading_session
                threshold = session.max_achievable_pct() * _COMPLETENESS_GATE

                actual = counts.get((sym, w.date_start_utc, "1m"), 0)
                completeness = actual / w.expected

                _CANONICAL_COMPLETENESS.add(
                    completeness, {"agent": self.name, "symbol": sym, "tf": "1m"}
                )

                if completeness < threshold:
                    await self._upsert_market_data_gap(
                        conn,
                        sym,
                        "1m",
                        w.date_start_utc,
                        w.expected,
                        w.expected - actual,
                    )
                    req = BarGapRequest(
                        symbol=sym,
                        tf="1m",
                        start_ts=w.date_start_utc,
                        end_ts=w.date_end_utc,
                    )
                    should_emit = await self._check_gap_retry(
                        conn, sym, "1m", w.date_start_utc, w.date_end_utc
                    )
                    if should_emit:
                        self.logger.warning(
                            "bar_auditor.gap_detected",
                            symbol=sym,
                            date=str(w.target_date),
                            actual=actual,
                            expected=w.expected,
                            completeness=round(completeness, 3),
                            threshold=round(threshold, 3),
                        )
                        gaps.append(req)
                        await self._record_gap_request_sent(
                            conn, sym, "1m", w.date_start_utc, req.request_id
                        )

                elif completeness >= 1.0:
                    await self._resolve_market_data_gap(conn, sym, "1m", w.date_start_utc)

                # HTF completeness metrics — log warnings only, no gap requests
                for tf_name, tf_minutes in _HTF_TIMEFRAME_MINUTES.items():
                    expected_htf = w.expected // tf_minutes
                    if expected_htf == 0:
                        continue
                    actual_htf = counts.get((sym, w.date_start_utc, tf_name), 0)
                    completeness_htf = actual_htf / expected_htf
                    _CANONICAL_COMPLETENESS.add(
                        completeness_htf, {"agent": self.name, "symbol": sym, "tf": tf_name}
                    )
                    if completeness_htf < threshold:
                        if tf_name in _HTF_PLAN_TFS:
                            # Plan 185-18: the alarm comes from the shared
                            # planner -- n_gaps IS len(plan_gaps(...)) for the
                            # same record the fetch pipeline reads, so a
                            # covered hole (answered window, verified empty
                            # span) is not an alarm.
                            plan = await self._plan_htf_gaps(
                                conn,
                                w.instrument,
                                tf_name,
                                w.date_start_utc,
                                w.date_end_utc,
                                now=now_utc,
                                reverify_days=span_reverify_days,
                                min_confirmations=span_min_confirmations,
                            )
                            if plan:
                                self.logger.warning(
                                    "bar_auditor.htf_gap_plan",
                                    symbol=sym,
                                    tf=tf_name,
                                    date=str(w.target_date),
                                    n_gaps=len(plan),
                                    first_gap=format_iso_ts(plan[0][0]),
                                    last_gap_end=format_iso_ts(plan[-1][1]),
                                    completeness=round(completeness_htf, 3),
                                    threshold=round(threshold, 3),
                                )
                            else:
                                self.logger.info(
                                    "bar_auditor.htf_gaps_all_covered",
                                    symbol=sym,
                                    tf=tf_name,
                                    date=str(w.target_date),
                                )
                        else:
                            self.logger.warning(
                                "bar_auditor.htf_gap_detected",
                                symbol=sym,
                                tf=tf_name,
                                date=str(w.target_date),
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
            instruments = get_active_contracts(self.settings, dimension="live")
        try:
            # observed_span must wrap the fallible body, not sit outside a try that
            # swallows everything -- observed_span only records ERROR on an exception
            # that actually propagates out of its `with` body (src/observability/
            # spans.py). It re-raises after tagging the span, so this outer except
            # still gets it and the "audit loop must continue" contract is unchanged.
            async with observed_span("bar_auditor.run_audit", tracer=self.tracer):
                _ad_t0 = _time.monotonic()
                gap_requests = await self._detect_gaps(instruments)
                _AUDIT_DURATION.record(_time.monotonic() - _ad_t0, self._agent_attrs)

                for req in gap_requests:
                    await self._kafka_producer.publish(
                        topic_gap_requests(self.env_name),
                        req.model_dump(mode="json"),
                        key=req.symbol,
                    )
                    _GAP_REQUESTS_PUBLISHED.add(1, self._agent_attrs)

                _AUDITS_RUN.add(1, self._agent_attrs)
                self.logger.info(
                    "bar_auditor.audit_complete",
                    gap_requests_published=len(gap_requests),
                )

        except Exception as error:
            _AUDIT_ERRORS.add(1, self._agent_attrs)
            self.logger.error(
                "bar_auditor.audit_error",
                error=str(error),
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

    def _should_emit_gap_request(self, row: dict) -> bool:
        """True if a new BarGapRequest should be emitted for this gap row.

        Enforces exponential-backoff retry schedule defined by _RETRY_BACKOFFS_SECS.
        Returns False (suppress) when MAX_GAP_RETRIES is reached — caller handles DLQ.
        """
        sent = row.get("gap_requests_sent", 0)
        if sent >= MAX_GAP_RETRIES:
            return False
        last_sent_at = row.get("last_request_sent_at")
        if last_sent_at is None:
            return True  # never sent — always emit
        backoff_idx = max(0, sent - 1)
        backoff_secs = _RETRY_BACKOFFS_SECS[min(backoff_idx, len(_RETRY_BACKOFFS_SECS) - 1)]
        elapsed = (datetime.now(UTC) - last_sent_at).total_seconds()
        return elapsed >= backoff_secs

    async def _check_gap_retry(
        self,
        conn: asyncpg.Connection,
        symbol: str,
        tf: str,
        start_ts: datetime,
        end_ts: datetime,
    ) -> bool:
        """Check DB retry state for a gap. Returns True if a new request should be emitted.

        Fetches current retry state from market_data_gaps. If MAX_GAP_RETRIES reached,
        publishes to DLQ instead of emitting. Caller is responsible for updating
        gap_requests_sent + last_request_sent_at via _record_gap_request_sent().
        """
        row = await conn.fetchrow(
            """
            SELECT gap_requests_sent, last_request_sent_at, last_request_id, resolved_at
            FROM market_data_gaps
            WHERE symbol = $1 AND tf = $2 AND gap_start_ts = $3
            """,
            symbol,
            tf,
            start_ts,
        )
        if row is None:
            return True  # gap row not yet written — will be upserted, then emit

        if row["resolved_at"] is not None:
            return False  # already resolved

        if not self._should_emit_gap_request(dict(row)):
            if row["gap_requests_sent"] >= MAX_GAP_RETRIES:
                await self._publish_gap_fill_dlq(
                    symbol=symbol,
                    tf=tf,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    retry_count=row["gap_requests_sent"],
                    error="max_retries_exceeded",
                )
            return False

        return True

    async def _record_gap_request_sent(
        self,
        conn: asyncpg.Connection,
        symbol: str,
        tf: str,
        start_ts: datetime,
        request_id: str,
    ) -> None:
        """Increment gap_requests_sent and update last_request_sent_at on the gap row."""
        await conn.execute(
            """
            UPDATE market_data_gaps
            SET gap_requests_sent    = gap_requests_sent + 1,
                last_request_sent_at = $4,
                last_request_id      = $5
            WHERE symbol = $1 AND tf = $2 AND gap_start_ts = $3
            """,
            symbol,
            tf,
            start_ts,
            datetime.now(UTC),
            request_id,
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
            "start_ts": format_iso_ts(start_ts),
            "end_ts": format_iso_ts(end_ts),
            "retry_count": retry_count,
            "error": error,
        }
        await self._kafka_producer.publish(
            topic_gap_fill_dlq(self.env_name),
            payload,
            key=symbol,
        )
        self._gap_fill_dlq_depth.add(1)
        self.logger.warning(
            "bar_auditor.gap_fill_dlq",
            symbol=symbol,
            tf=tf,
            retry_count=retry_count,
            error=error,
        )

    def _is_roll_suppressed(self, old_contract: str) -> bool:
        """True if old_contract is within 2h post-roll suppression window."""
        roll_time = self._post_roll_suppression.get(old_contract)
        if roll_time is None:
            return False
        return (datetime.now(UTC) - roll_time).total_seconds() < _POST_ROLL_SUPPRESS_SECS

    def _cleanup_roll_suppression(self) -> None:
        """Remove stale suppression entries (> 2h old) to prevent unbounded growth."""
        cutoff = datetime.now(UTC) - timedelta(seconds=_POST_ROLL_SUPPRESS_SECS)
        stale = [k for k, v in self._post_roll_suppression.items() if v < cutoff]
        for k in stale:
            del self._post_roll_suppression[k]

    def _any_session_open(self, instruments: list) -> bool:
        """True if any active instrument's trading session is currently open."""
        now_utc = datetime.now(UTC)
        for instrument in instruments:
            if instrument.trading_session.is_open(now_utc):
                return True
        return False


if __name__ == "__main__":
    asyncio.run(BarAuditor().start())
