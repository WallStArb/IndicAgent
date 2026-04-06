# Signal Auditor & CIS Contract Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the signals DAG with an AuditorAgent, enforce CIS non-null at source, and retire the cron-based data_quality_check.py.

**Architecture:** Four layers — (1) one-time data cleanup, (2) source assertion + DLQ in intelligence_pipeline_agent, (3) NOT NULL DB migration, (4) new `SignalAuditorAgent` mirroring the bar_auditor_agent pattern. Signals domain achieves parity with the bars self-healing DAG.

**Tech Stack:** Python 3.11+, asyncpg, aiokafka, prometheus_client, structlog, systemd, TimescaleDB/PostgreSQL

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `src/core/stream_keys.py` | Add `topic_signal_dlq()` and `topic_signal_audit()` |
| Modify | `services/intelligence_pipeline_agent.py` | CIS assertion + DLQ publish before i7 enqueue |
| Create | `production/migrations/057_signal_ledger_cis_not_null.sql` | NOT NULL constraints on CIS columns |
| Create | `services/signal_auditor_agent.py` | SignalAuditorAgent — coverage, lag, CIS distribution |
| Create | `tests/unit/test_signal_auditor_agent.py` | Unit tests for signal_auditor_agent |
| Create | `production/systemd/indicagent-signal-auditor.service` | Systemd unit template |
| Archive | `production/scripts/data_quality_check.py` → `production/scripts/archive/` | Retire cron script |
| Archive | `tests/unit/intelligence/monitoring/test_data_quality_monitor.py` | Remove null-rate-only tests |

---

## Task 0: Data Cleanup — TRUNCATE + reset Kafka offset + restart tracker

**Files:** none (operational steps only)

> **Execute these steps manually (requires DB + systemd access). Do not skip.**

- [ ] **Step 1: Verify signal_ledger row count before cleanup**

```bash
docker exec timescaledb psql -U postgres -d indicagent -c "
SELECT COUNT(*) AS total,
       SUM(CASE WHEN cis_score IS NULL THEN 1 ELSE 0 END) AS null_cis,
       SUM(CASE WHEN cis_score IS NOT NULL THEN 1 ELSE 0 END) AS non_null_cis
FROM signal_ledger;"
```

Expected: ~661K total, ~649K null_cis, ~12K non_null_cis

- [ ] **Step 2: TRUNCATE signal_ledger (CASCADE for partition tables)**

```bash
docker exec timescaledb psql -U postgres -d indicagent -c "TRUNCATE signal_ledger CASCADE;"
```

- [ ] **Step 3: Verify table is empty**

```bash
docker exec timescaledb psql -U postgres -d indicagent -c "SELECT COUNT(*) FROM signal_ledger;"
```

Expected: 0

- [ ] **Step 4: Stop signal_tracker to clear stale in-memory state**

```bash
echo 'PASSWORD' | /usr/bin/sudo.ws -S systemctl stop indicagent-signal-tracker
```

- [ ] **Step 5: Reset signal_writer_group consumer offset to latest**

Reset the consumer group offset on `intelligence.i7.signals` to prevent signal_writer from replaying pre-Phase-57 messages that lack CIS fields:

```bash
docker exec redpanda rpk group seek signal_writer_group --to end --topics intelligence.i7.signals
```

- [ ] **Step 6: Restart signal_tracker (clean state)**

```bash
echo 'PASSWORD' | /usr/bin/sudo.ws -S systemctl start indicagent-signal-tracker
```

- [ ] **Step 7: Verify signal_tracker is active**

```bash
echo 'PASSWORD' | /usr/bin/sudo.ws -S systemctl status indicagent-signal-tracker
```

Expected: `active (running)`

---

## Task 1: Add topic functions to stream_keys.py

**Files:**
- Modify: `src/core/stream_keys.py`
- Test: `tests/unit/test_stream_keys.py` (or create `tests/unit/test_stream_keys_61.py`)

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_stream_keys_61.py`:

```python
"""Tests for Phase 61 stream key additions — signal DLQ and audit topics."""
from src.core.stream_keys import topic_signal_dlq, topic_signal_audit


def test_topic_signal_dlq_no_env():
    assert topic_signal_dlq("") == "intelligence.signal.dlq"


def test_topic_signal_dlq_with_env():
    assert topic_signal_dlq("dev") == "dev.intelligence.signal.dlq"


def test_topic_signal_audit_no_env():
    assert topic_signal_audit("") == "intelligence.signal.audit"


def test_topic_signal_audit_with_env():
    assert topic_signal_audit("dev") == "dev.intelligence.signal.audit"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/test_stream_keys_61.py -v
```

Expected: `ImportError: cannot import name 'topic_signal_dlq'`

- [ ] **Step 3: Add topic functions to stream_keys.py**

Open `src/core/stream_keys.py`. After the `topic_health_events_dlq` function (around line 235), add:

```python
def topic_signal_dlq(env_name: str) -> str:
    """DLQ for signals that fail CIS assertion before publish.

    Published by intelligence_pipeline_agent when a ranked signal has
    raw_cis_score IS None or filtered_cis_score IS None — indicates a
    regression in the CIS stamping path. Never lets null-CIS signals
    enter intelligence.i7.signals.
    """
    return f"{env_prefix(env_name)}intelligence.signal.dlq"


def topic_signal_audit(env_name: str) -> str:
    """Audit events from signal_auditor_agent.

    Receives SignalCoverageGapEvent payloads when a (symbol, tf) pair had
    zero signals in the last completed trading session. Future: intelligence
    pipeline subscribes to trigger bar replay for covered symbols.
    """
    return f"{env_prefix(env_name)}intelligence.signal.audit"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/test_stream_keys_61.py -v
```

Expected: 4 tests PASS

- [ ] **Step 5: Run full stream_keys test suite to confirm no regressions**

```bash
.venv/bin/pytest tests/unit/test_stream_keys.py tests/unit/test_stream_keys_57.py tests/unit/test_stream_keys_imports.py tests/unit/test_stream_keys_61.py -v
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/core/stream_keys.py tests/unit/test_stream_keys_61.py
git commit -m "feat(61-01): add topic_signal_dlq and topic_signal_audit to stream_keys"
```

---

## Task 2: Layer 2 — CIS assertion + DLQ publish in intelligence_pipeline_agent

**Files:**
- Modify: `services/intelligence_pipeline_agent.py`
- Test: `tests/unit/test_intelligence_pipeline_agent.py`

- [ ] **Step 1: Write the failing test**

Open `tests/unit/test_intelligence_pipeline_agent.py`. Add this test (find existing `_run_i7_pipeline` tests to place it near them):

```python
def test_cis_assertion_publishes_to_dlq_on_null_raw_cis(pipeline_agent_fixture):
    """When a ranked signal has raw_cis_score=None, the DLQ counter increments
    and no signal is published to intelligence.i7.signals."""
    import asyncio
    from unittest.mock import MagicMock, patch
    from services.intelligence_pipeline_agent import IntelligencePipelineComputeAgent

    agent = IntelligencePipelineComputeAgent.__new__(IntelligencePipelineComputeAgent)
    agent.logger = MagicMock()
    agent._output_queue = asyncio.Queue(maxsize=500)
    agent._output_buffer_drops = MagicMock()
    agent._signal_dlq_total = MagicMock()

    # Build a ranked signal dict missing raw_cis_score (simulates regression)
    bad_signal = {
        "setup_plugin": "TestPlugin",
        "direction": "long",
        "confidence": 0.8,
        "raw_cis_score": None,   # <-- the broken field
        "filtered_cis_score": 0.6,
    }
    ranked = [bad_signal]

    with patch("services.intelligence_pipeline_agent.topic_signal_dlq", return_value="intelligence.signal.dlq"):
        agent._publish_signals_or_dlq(ranked, "ES", "1m", MagicMock())

    agent._signal_dlq_total.inc.assert_called_once()
    # Queue should have DLQ payload, not i7 payload
    assert agent._output_queue.qsize() == 1
    topic, key, payload = agent._output_queue.get_nowait()
    assert topic == "intelligence.signal.dlq"
    assert payload["reason"] == "cis_score_null"
```

> **Note:** If `_publish_signals_or_dlq` doesn't exist yet (it's being extracted in this task), the test will fail with `AttributeError`. That's expected — the test drives the extraction.

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/unit/test_intelligence_pipeline_agent.py::test_cis_assertion_publishes_to_dlq_on_null_raw_cis -v
```

Expected: `AttributeError: '_publish_signals_or_dlq'` or similar

- [ ] **Step 3: Add _signal_dlq_total counter to __init__**

In `services/intelligence_pipeline_agent.py`, in `__init__` after the `_signals_selected` counter definition (~line 507), add:

```python
        self._signal_dlq_total = counter(
            "intelligence_pipeline_signal_dlq_total",
            "Signals dropped to DLQ due to CIS assertion failure",
        )
```

- [ ] **Step 4: Add topic_signal_dlq import**

In `services/intelligence_pipeline_agent.py`, in the `from src.core.stream_keys import ...` block, add `topic_signal_dlq`:

```python
from src.core.stream_keys import (
    ...
    topic_signal_dlq,
    ...
)
```

- [ ] **Step 5: Extract _publish_signals_or_dlq method**

In `services/intelligence_pipeline_agent.py`, add a new private method just before `_enqueue_intel_journal` (~line 1373). This method encapsulates the CIS assertion + conditional publish that was previously inline:

```python
def _publish_signals_or_dlq(
    self,
    ranked: list[dict],
    symbol: str,
    tf: str,
    bar: "BarMessage",
) -> bool:
    """Assert all ranked signals have non-null CIS before publishing.

    Returns True if signals were published to intelligence.i7.signals.
    Returns False and publishes to intelligence.signal.dlq if CIS assertion fails.
    This prevents null-CIS signals from entering the Kafka pipeline or signal_ledger.
    """
    # CIS assertion — every signal must have been stamped by _run_i7_pipeline
    for sig in ranked:
        if sig.get("raw_cis_score") is None or sig.get("filtered_cis_score") is None:
            self._signal_dlq_total.inc()
            self._enqueue(
                topic_signal_dlq(self._settings.env_name),
                message_key(symbol, tf),
                {
                    "symbol": symbol,
                    "tf": tf,
                    "bar_ts": bar.ts.isoformat(),
                    "reason": "cis_score_null",
                    "signal_count": len(ranked),
                    "ts": datetime.now(UTC).isoformat(),
                },
            )
            self.logger.error(
                "intelligence_pipeline_agent.cis_assertion_failed",
                symbol=symbol,
                tf=tf,
                signal_count=len(ranked),
            )
            return False

    # Assertion passed — publish all ranked signals to i7.signals
    self._enqueue(
        topic_intelligence_i7_signals(self._settings.env_name),
        message_key(symbol, tf),
        {
            "symbol": symbol,
            "tf": tf,
            "bar_ts": bar.ts.isoformat(),
            "computed_at": datetime.now(UTC).isoformat(),
            "signals": ranked,
        },
    )
    return True
```

- [ ] **Step 6: Replace inline publish block in _run_i7_pipeline**

In `services/intelligence_pipeline_agent.py`, find the block at ~line 1315–1326 that reads:

```python
        # Publish ALL ranked signals (including regime_suppressed) for SignalWriterAgent → signal_ledger
        self._enqueue(
            topic_intelligence_i7_signals(self._settings.env_name),
            message_key(symbol, tf),
            {
                "symbol": symbol,
                "tf": tf,
                "bar_ts": bar.ts.isoformat(),
                "computed_at": datetime.now(UTC).isoformat(),
                "signals": ranked,
            },
        )
```

Replace with:

```python
        # Publish ALL ranked signals — assertion + DLQ gating inside
        published = self._publish_signals_or_dlq(ranked, symbol, tf, bar)
        if not published:
            return {
                "ranked": [],
                "winner": None,
                "signals_evaluated": len(raw_signals),
                "signals_after_quality": len(quality_gated),
                "signals_after_regime": len(regime_gated),
                "signals_after_tod": len(tod_adjusted),
                "signals_after_calibration": len(calibrated),
                "i7_computed_at": i7_computed_at,
            }
```

- [ ] **Step 7: Run the new test to verify it passes**

```bash
.venv/bin/pytest tests/unit/test_intelligence_pipeline_agent.py::test_cis_assertion_publishes_to_dlq_on_null_raw_cis -v
```

Expected: PASS

- [ ] **Step 8: Run the full intelligence_pipeline_agent test suite**

```bash
.venv/bin/pytest tests/unit/test_intelligence_pipeline_agent.py -v
```

Expected: all PASS (no regressions)

- [ ] **Step 9: Lint**

```bash
.venv/bin/ruff check services/intelligence_pipeline_agent.py --fix
```

- [ ] **Step 10: Commit**

```bash
git add services/intelligence_pipeline_agent.py tests/unit/test_intelligence_pipeline_agent.py
git commit -m "feat(61-02): add CIS assertion + DLQ publish in intelligence_pipeline_agent"
```

---

## Task 3: Layer 3 — DB migration (NOT NULL constraints)

**Files:**
- Create: `production/migrations/057_signal_ledger_cis_not_null.sql`

> **Apply AFTER verifying at least one full trading session with clean CIS (no DLQ events). Task 0 must be complete first.**

- [ ] **Step 1: Write the migration file**

Create `production/migrations/057_signal_ledger_cis_not_null.sql`:

```sql
-- Migration 057: Enforce NOT NULL on CIS fields in signal_ledger
-- Phase 61 — signal auditor + CIS contract enforcement
--
-- Pre-condition: signal_ledger must be empty (TRUNCATED in Task 0) or contain
-- only rows with non-null CIS scores. Run AFTER verifying one clean trading
-- session where DLQ counter stayed at 0.
--
-- Safe to run: if any null exists, the ALTER will fail with a loud error,
-- protecting the table from silently accepting a partial migration.

BEGIN;

ALTER TABLE signal_ledger
  ALTER COLUMN cis_score            SET NOT NULL,
  ALTER COLUMN raw_cis_score        SET NOT NULL,
  ALTER COLUMN filtered_cis_score   SET NOT NULL,
  ALTER COLUMN bucket_scores        SET NOT NULL,
  ALTER COLUMN weights_version      SET NOT NULL;

COMMENT ON COLUMN signal_ledger.cis_score IS
    'Kalman-filtered CIS score at time of signal. NOT NULL enforced Phase 61. '
    'CISScorer defaults bucket inputs to 0.0 when features absent — always computable.';

COMMENT ON COLUMN signal_ledger.raw_cis_score IS
    'Raw CIS score before Kalman filter. NOT NULL enforced Phase 61.';

COMMENT ON COLUMN signal_ledger.filtered_cis_score IS
    'Kalman-filtered CIS score. NOT NULL enforced Phase 61.';

COMMIT;
```

- [ ] **Step 2: Verify no null CIS rows exist (pre-condition check)**

```bash
docker exec timescaledb psql -U postgres -d indicagent -c "
SELECT COUNT(*) FROM signal_ledger WHERE cis_score IS NULL
   OR raw_cis_score IS NULL OR filtered_cis_score IS NULL
   OR bucket_scores IS NULL OR weights_version IS NULL;"
```

Expected: 0 rows. If non-zero, **stop** — the pipeline is still producing null-CIS signals. Fix DLQ first.

- [ ] **Step 3: Apply the migration**

```bash
docker exec -i timescaledb psql -U postgres -d indicagent < production/migrations/057_signal_ledger_cis_not_null.sql
```

Expected output:
```
BEGIN
ALTER TABLE
ALTER TABLE
ALTER TABLE
ALTER TABLE
ALTER TABLE
COMMENT
COMMENT
COMMENT
COMMIT
```

- [ ] **Step 4: Verify constraints are in place**

```bash
docker exec timescaledb psql -U postgres -d indicagent -c "
SELECT column_name, is_nullable
FROM information_schema.columns
WHERE table_name = 'signal_ledger'
  AND column_name IN ('cis_score','raw_cis_score','filtered_cis_score','bucket_scores','weights_version')
ORDER BY column_name;"
```

Expected: `is_nullable = NO` for all five columns.

- [ ] **Step 5: Commit**

```bash
git add production/migrations/057_signal_ledger_cis_not_null.sql
git commit -m "feat(61-03): NOT NULL constraints on signal_ledger CIS columns"
```

---

## Task 4: Build signal_auditor_agent.py

**Files:**
- Create: `services/signal_auditor_agent.py`

- [ ] **Step 1: Create the file**

Create `services/signal_auditor_agent.py` with the full implementation:

```python
#!/usr/bin/env python3
"""SignalAuditorAgent — coverage validation and lag monitoring for signal_ledger.

Runs a 5-minute audit loop during market hours. Checks:
1. Signal coverage per (symbol, tf) — at least one signal fired in the last session.
2. Pipeline lag P50/P95 from signal_ledger.pipeline_lag_ms over last 1h.
3. CIS score distribution (mean/stddev) per tf over a rolling 5-day window.

Emits SignalCoverageGapEvent to intelligence.signal.audit on coverage gaps.
DB-aware (reads signal_ledger). AuditorAgent role — read-only, never writes.
Metrics port: :9126

Golden Signals:
- Traffic: signal_auditor_audits_run_total, signal_auditor_coverage_gaps_published_total
- Latency: signal_auditor_audit_duration_seconds
- Errors: signal_auditor_audit_errors_total
- Saturation: signal_coverage_pct{symbol, tf}

Version: 1.0.0
Phase: 61
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
from src.core.stream_keys import topic_signal_audit
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
    Emits SignalCoverageGapEvent to intelligence.signal.audit for missing coverage.

    DB-aware (reads signal_ledger). Never writes. Metrics port: :9126.
    """

    def __init__(self) -> None:
        # config-before-super pattern (Phase 52.2 convention)
        self._settings = Settings()
        self._env_name: str = self._settings.env_name or ""
        super().__init__(name="signal_auditor_agent", metrics_port=9126)

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
        return [topic_signal_audit(self._env_name)]

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
        """Run a full audit cycle. Catches exceptions to keep the loop alive."""
        if instruments is None:
            instruments = get_active_contracts(self._settings)
        try:
            with self._audit_duration.time():
                gap_events = await self._check_coverage(instruments)
                await self._check_pipeline_lag(instruments)
                await self._check_cis_distribution()

            for event in gap_events:
                await self._kafka_producer.publish(
                    topic_signal_audit(self._env_name),
                    event,
                    key=f"{event['symbol']}:{event['tf']}",
                )
                self._coverage_gaps_published.inc()

            self._audits_run.inc()
            self.logger.info(
                "signal_auditor_agent.audit_complete",
                coverage_gaps_published=len(gap_events),
            )

        except Exception as exc:
            self._audit_errors.inc()
            self.logger.error(
                "signal_auditor_agent.audit_error",
                error=str(exc),
            )

    async def _check_coverage(self, instruments: list) -> list[dict]:
        """Check signal coverage for the last completed trading session.

        For each active symbol × _COVERAGE_TFS:
        - Find the last completed session window via session_window_for_date(yesterday).
        - Count signal_ledger rows in that window.
        - Set signal_coverage_pct gauge (1.0 covered, 0.0 gap).
        - Return SignalCoverageGapEvent dicts for any (symbol, tf) with 0 signals.
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
                        FROM signal_ledger
                        WHERE symbol = $1
                          AND tf = $2
                          AND feature_ts >= $3
                          AND feature_ts < $4
                        """,
                        instrument.symbol,
                        tf,
                        session_start,
                        session_end,
                    )
                    count = count or 0
                    coverage = 1.0 if count > 0 else 0.0

                    self._signal_coverage_pct.labels(
                        agent=self.name, symbol=instrument.symbol, tf=tf
                    ).set(coverage)

                    if count == 0:
                        self.logger.warning(
                            "signal_auditor_agent.coverage_gap",
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

    async def _check_pipeline_lag(self, instruments: list) -> None:
        """Observe P50/P95 pipeline_lag_ms from signal_ledger for the last 1h.

        Logs WARNING when P95 > _LAG_P95_WARN_MS. Updates Prometheus gauges.
        """
        assert self._db_pool is not None
        async with self._db_pool.acquire() as conn:
            for instrument in instruments:
                for tf in _COVERAGE_TFS:
                    row = await conn.fetchrow(
                        """
                        SELECT
                          percentile_cont(0.50) WITHIN GROUP (ORDER BY pipeline_lag_ms) AS p50,
                          percentile_cont(0.95) WITHIN GROUP (ORDER BY pipeline_lag_ms) AS p95
                        FROM signal_ledger
                        WHERE symbol = $1
                          AND tf = $2
                          AND feature_ts >= NOW() - INTERVAL '1 hour'
                          AND pipeline_lag_ms IS NOT NULL
                        """,
                        instrument.symbol,
                        tf,
                    )
                    if row is None or row["p50"] is None:
                        continue  # No data for this (symbol, tf) in the last hour

                    p50: float = row["p50"]
                    p95: float = row["p95"]

                    self._pipeline_lag_p50.labels(
                        agent=self.name, symbol=instrument.symbol, tf=tf
                    ).set(p50)
                    self._pipeline_lag_p95.labels(
                        agent=self.name, symbol=instrument.symbol, tf=tf
                    ).set(p95)

                    if p95 > _LAG_P95_WARN_MS:
                        self.logger.warning(
                            "signal_auditor_agent.lag_threshold_exceeded",
                            symbol=instrument.symbol,
                            tf=tf,
                            p95_ms=round(p95, 1),
                            threshold_ms=_LAG_P95_WARN_MS,
                        )

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
                    WHERE tf = $1
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
            # Check if we are within buffer after session close
            yesterday = date.today() - timedelta(days=1)
            window = session.session_window_for_date(yesterday)
            if window[1] is not None and now_utc <= window[1] + buffer:
                return True
        return False


if __name__ == "__main__":
    init_tracing("signal_auditor_agent")
    asyncio.run(SignalAuditorAgent().start())
```

- [ ] **Step 2: Lint the new file**

```bash
.venv/bin/ruff check services/signal_auditor_agent.py --fix
.venv/bin/black services/signal_auditor_agent.py
```

- [ ] **Step 3: Commit**

```bash
git add services/signal_auditor_agent.py
git commit -m "feat(61-04): add SignalAuditorAgent — coverage, lag, CIS distribution checks"
```

---

## Task 5: Unit tests for signal_auditor_agent

**Files:**
- Create: `tests/unit/test_signal_auditor_agent.py`

- [ ] **Step 1: Write the tests**

Create `tests/unit/test_signal_auditor_agent.py`:

```python
"""Unit tests for SignalAuditorAgent.

Tests verify:
- Signal coverage gap detection and event emission
- Coverage 1.0 when signals are present in the session window
- Pipeline lag P50/P95 metric observation
- CIS distribution mean/stddev metric observation
- _any_session_near_open gate logic
- topics_produced contains signal_audit topic
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.signal_auditor_agent import (
    _COVERAGE_TFS,
    _LAG_P95_WARN_MS,
    SignalAuditorAgent,
)
from src.core.models import AssetClass, Instrument
from src.core.stream_keys import topic_signal_audit


@pytest.fixture()
def agent():
    """Create SignalAuditorAgent without __init__ (bypasses DB/Kafka setup)."""
    a = SignalAuditorAgent.__new__(SignalAuditorAgent)
    a.name = "signal_auditor_agent"
    a.logger = MagicMock()
    a._settings = MagicMock()
    a._env_name = ""
    a._db_pool = AsyncMock()
    a._kafka_producer = AsyncMock()
    a._audits_run = MagicMock()
    a._coverage_gaps_published = MagicMock()
    a._audit_duration = MagicMock()
    a._audit_duration.__enter__ = MagicMock(return_value=None)
    a._audit_duration.__exit__ = MagicMock(return_value=False)
    a._audit_errors = MagicMock()
    a._signal_coverage_pct = MagicMock()
    a._signal_coverage_pct.labels.return_value = MagicMock()
    a._pipeline_lag_p50 = MagicMock()
    a._pipeline_lag_p50.labels.return_value = MagicMock()
    a._pipeline_lag_p95 = MagicMock()
    a._pipeline_lag_p95.labels.return_value = MagicMock()
    a._cis_mean = MagicMock()
    a._cis_mean.labels.return_value = MagicMock()
    a._cis_stddev = MagicMock()
    a._cis_stddev.labels.return_value = MagicMock()
    return a


def _make_instrument(session_id: str = "rth_equity", symbol: str = "SPY") -> Instrument:
    return Instrument(symbol=symbol, asset_class=AssetClass.EQUITIES, session_id=session_id)


def _make_conn_mock(coverage_count: int = 0, lag_row=None, cis_row=None):
    """Build an asyncpg connection mock.

    coverage_count: returned by fetchval for coverage queries.
    lag_row: dict with p50/p95 keys returned by fetchrow for lag queries.
    cis_row: dict with cis_mean/cis_stddev keys returned by fetchrow for CIS queries.
    """
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=coverage_count)

    def fetchrow_side_effect(query, *args):
        if "percentile_cont" in query:
            return AsyncMock(return_value=lag_row)()
        if "AVG(cis_score)" in query:
            return AsyncMock(return_value=cis_row)()
        return AsyncMock(return_value=None)()

    conn.fetchrow = AsyncMock(side_effect=fetchrow_side_effect)
    return conn


@pytest.mark.asyncio
async def test_coverage_gap_when_zero_signals(agent):
    """_check_coverage returns one gap event per tf when count = 0."""
    instrument = _make_instrument()
    conn = _make_conn_mock(coverage_count=0)
    agent._db_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    agent._db_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch.object(instrument.trading_session, "session_window_for_date") as mock_window:
        yesterday = date.today() - timedelta(days=1)
        session_start = datetime(2026, 4, 5, 14, 30, tzinfo=UTC)
        session_end = datetime(2026, 4, 5, 21, 0, tzinfo=UTC)
        mock_window.return_value = (session_start, session_end)

        gaps = await agent._check_coverage([instrument])

    assert len(gaps) == len(_COVERAGE_TFS)
    for gap in gaps:
        assert gap["symbol"] == "SPY"
        assert gap["signals_found"] == 0
        assert "session_date" in gap
        assert "ts" in gap

    # Gauge set to 0.0 for each tf
    assert agent._signal_coverage_pct.labels.call_count == len(_COVERAGE_TFS)


@pytest.mark.asyncio
async def test_no_gap_when_signals_present(agent):
    """_check_coverage returns no gap events when count > 0."""
    instrument = _make_instrument()
    conn = _make_conn_mock(coverage_count=42)
    agent._db_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    agent._db_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch.object(instrument.trading_session, "session_window_for_date") as mock_window:
        mock_window.return_value = (
            datetime(2026, 4, 5, 14, 30, tzinfo=UTC),
            datetime(2026, 4, 5, 21, 0, tzinfo=UTC),
        )
        gaps = await agent._check_coverage([instrument])

    assert gaps == []
    # Gauge set to 1.0 for each tf
    for call in agent._signal_coverage_pct.labels.return_value.set.call_args_list:
        assert call.args[0] == 1.0


@pytest.mark.asyncio
async def test_coverage_skips_non_trading_day(agent):
    """_check_coverage skips instruments where session_window returns (None, None)."""
    instrument = _make_instrument()
    conn = _make_conn_mock(coverage_count=0)
    agent._db_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    agent._db_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch.object(instrument.trading_session, "session_window_for_date") as mock_window:
        mock_window.return_value = (None, None)
        gaps = await agent._check_coverage([instrument])

    assert gaps == []
    conn.fetchval.assert_not_called()


@pytest.mark.asyncio
async def test_pipeline_lag_warns_when_p95_exceeds_threshold(agent):
    """_check_pipeline_lag logs WARNING when P95 > _LAG_P95_WARN_MS."""
    instrument = _make_instrument()
    lag_row = {"p50": 120.0, "p95": 650.0}  # P95 over threshold
    conn = _make_conn_mock(lag_row=lag_row)
    agent._db_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    agent._db_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    await agent._check_pipeline_lag([instrument])

    agent.logger.warning.assert_called()
    warn_call = agent.logger.warning.call_args
    assert warn_call.args[0] == "signal_auditor_agent.lag_threshold_exceeded"
    assert warn_call.kwargs["p95_ms"] == 650.0


@pytest.mark.asyncio
async def test_pipeline_lag_no_warning_within_threshold(agent):
    """_check_pipeline_lag does not log WARNING when P95 <= _LAG_P95_WARN_MS."""
    instrument = _make_instrument()
    lag_row = {"p50": 80.0, "p95": 200.0}  # Below threshold
    conn = _make_conn_mock(lag_row=lag_row)
    agent._db_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    agent._db_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    await agent._check_pipeline_lag([instrument])

    agent.logger.warning.assert_not_called()


@pytest.mark.asyncio
async def test_cis_distribution_sets_gauges(agent):
    """_check_cis_distribution sets cis_mean and cis_stddev gauges per tf."""
    cis_row = {"cis_mean": 0.52, "cis_stddev": 0.18}
    conn = _make_conn_mock(cis_row=cis_row)
    agent._db_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    agent._db_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    await agent._check_cis_distribution()

    assert agent._cis_mean.labels.call_count == len(_COVERAGE_TFS)
    agent._cis_mean.labels.return_value.set.assert_called_with(0.52)


def test_topics_produced(agent):
    """topics_produced returns the signal audit topic."""
    assert topic_signal_audit("") in agent.topics_produced


def test_topics_consumed_is_empty(agent):
    """topics_consumed is empty — AuditorAgent pulls from DB."""
    assert agent.topics_consumed == []
```

- [ ] **Step 2: Run the tests**

```bash
.venv/bin/pytest tests/unit/test_signal_auditor_agent.py -v
```

Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_signal_auditor_agent.py
git commit -m "test(61-05): unit tests for SignalAuditorAgent"
```

---

## Task 6: Install systemd unit

**Files:**
- Create: `production/systemd/indicagent-signal-auditor.service`
- Operational: install + enable via systemd

- [ ] **Step 1: Write the service unit template**

Create `production/systemd/indicagent-signal-auditor.service`:

```ini
[Unit]
Description=IndicAgent Signal Auditor Agent — coverage validation + lag monitoring
After=network-online.target indicagent-signal-writer.service indicagent-redpanda-ready.service
Requires=indicagent-redpanda-ready.service
Wants=indicagent-signal-writer.service
StartLimitIntervalSec=300
StartLimitBurst=0

[Service]
Type=simple
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
Environment=PYTHONUNBUFFERED=1
Environment=OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/signal_auditor_agent.py
Restart=always
WatchdogSec=60
NotifyAccess=main
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=indicagent-signal-auditor
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Install the unit**

```bash
echo 'PASSWORD' | /usr/bin/sudo.ws -S cp production/systemd/indicagent-signal-auditor.service /etc/systemd/system/
echo 'PASSWORD' | /usr/bin/sudo.ws -S systemctl daemon-reload
echo 'PASSWORD' | /usr/bin/sudo.ws -S systemctl enable indicagent-signal-auditor
echo 'PASSWORD' | /usr/bin/sudo.ws -S systemctl start indicagent-signal-auditor
```

- [ ] **Step 3: Verify service is running**

```bash
echo 'PASSWORD' | /usr/bin/sudo.ws -S systemctl status indicagent-signal-auditor
```

Expected: `active (running)`

- [ ] **Step 4: Verify metrics endpoint is reachable**

```bash
curl -s http://localhost:9126/metrics | grep "signal_auditor_audits_run_total"
```

Expected: line with `signal_auditor_audits_run_total{agent="signal_auditor_agent"} 1.0` (after first audit cycle completes)

- [ ] **Step 5: Check logs for first audit cycle**

```bash
journalctl -u indicagent-signal-auditor --since "5 minutes ago" | grep "audit_complete\|audit_error"
```

Expected: `signal_auditor_agent.audit_complete` with `coverage_gaps_published=N`

- [ ] **Step 6: Commit**

```bash
git add production/systemd/indicagent-signal-auditor.service
git commit -m "feat(61-06): add indicagent-signal-auditor.service systemd unit"
```

---

## Task 7: Archive data_quality_check.py and retire systemd units

**Files:**
- Archive: `production/scripts/data_quality_check.py` → `production/scripts/archive/`
- Archive: `tests/unit/intelligence/monitoring/test_data_quality_monitor.py`
- Delete: `DQ_NULL_CIS_RATE` and `DQ_NULL_CONFIDENCE_RATE` from `src/observability/data_quality_metrics.py`
- Operational: disable + remove `indicagent-data-quality.service` and `.timer`

- [ ] **Step 1: Disable and remove systemd units**

```bash
echo 'PASSWORD' | /usr/bin/sudo.ws -S systemctl disable --now indicagent-data-quality.timer
echo 'PASSWORD' | /usr/bin/sudo.ws -S systemctl disable --now indicagent-data-quality.service
echo 'PASSWORD' | /usr/bin/sudo.ws -S rm /etc/systemd/system/indicagent-data-quality.service
echo 'PASSWORD' | /usr/bin/sudo.ws -S rm /etc/systemd/system/indicagent-data-quality.timer
echo 'PASSWORD' | /usr/bin/sudo.ws -S systemctl daemon-reload
```

- [ ] **Step 2: Verify units are gone**

```bash
echo 'PASSWORD' | /usr/bin/sudo.ws -S systemctl list-units --all | grep "data-quality"
```

Expected: no output

- [ ] **Step 3: Archive the cron script**

```bash
mkdir -p production/scripts/archive
```

Add deprecation header and move:

```bash
# Write temp file with header
cat > /tmp/dq_archive_header.py << 'EOF'
"""DEPRECATED: data_quality_check.py 2026-04-06 — Phase 61.
Retired: replaced by SignalAuditorAgent (services/signal_auditor_agent.py).
Cron-based null rate checking superseded by DB NOT NULL constraint (migration 057)
and continuous 5-min audit loop. Disabled: indicagent-data-quality.{service,timer}.
"""
# --- ARCHIVED BELOW ---
EOF
cat /tmp/dq_archive_header.py production/scripts/data_quality_check.py > production/scripts/archive/data_quality_check.py
```

- [ ] **Step 4: Archive the test file**

```bash
cp tests/unit/intelligence/monitoring/test_data_quality_monitor.py \
   tests/unit/intelligence/monitoring/_archived_test_data_quality_monitor.py
```

Add deprecation comment to the top of the archived file:

Open `tests/unit/intelligence/monitoring/_archived_test_data_quality_monitor.py` and prepend:

```python
"""ARCHIVED: 2026-04-06 Phase 61 — DataQualityMonitor null-rate tests.
DataQualityMonitor itself still exists (src/intelligence/monitoring/data_quality_monitor.py)
but the null-rate checks it was testing are now enforced by DB constraint (migration 057).
These tests tested the monitoring of a broken invariant, not a feature. Archived.
"""
# --- ARCHIVED BELOW ---
```

- [ ] **Step 5: Remove the original test file**

```bash
rm tests/unit/intelligence/monitoring/test_data_quality_monitor.py
```

- [ ] **Step 6: Delete null-rate metrics from data_quality_metrics.py**

Open `src/observability/data_quality_metrics.py`. Remove these two metric definitions:

```python
DQ_NULL_CIS_RATE = Gauge(
    "dq_null_cis_rate",
    "Fraction of signal_ledger rows with NULL cis_score (recoverable nulls only)",
    ["symbol"],
)

DQ_NULL_CONFIDENCE_RATE = Gauge(
    "dq_null_confidence_rate",
    "Fraction of signal_ledger rows with NULL confidence",
    ["symbol"],
)
```

Also remove the `# --- NULL RATE METRICS ---` section header comment.

- [ ] **Step 7: Verify no imports of removed metrics remain**

```bash
grep -rn "DQ_NULL_CIS_RATE\|DQ_NULL_CONFIDENCE_RATE" . --include="*.py"
```

Expected: no output

- [ ] **Step 8: Run full unit test suite**

```bash
.venv/bin/pytest tests/unit/ -v --tb=short 2>&1 | tail -20
```

Expected: all PASS

- [ ] **Step 9: Lint**

```bash
.venv/bin/ruff check . --fix
```

- [ ] **Step 10: Commit**

```bash
git add production/scripts/archive/data_quality_check.py \
        tests/unit/intelligence/monitoring/_archived_test_data_quality_monitor.py \
        src/observability/data_quality_metrics.py
git rm production/scripts/data_quality_check.py \
       tests/unit/intelligence/monitoring/test_data_quality_monitor.py 2>/dev/null || true
git commit -m "feat(61-07): retire data_quality_check.py + remove null-rate metrics"
```

---

## Final Verification

- [ ] **Verify all services healthy**

```bash
echo 'PASSWORD' | /usr/bin/sudo.ws -S systemctl list-units --all | grep indicagent | grep -v "dead\|inactive" | sort
```

Expected: `indicagent-signal-auditor.service` shows `active (running)`

- [ ] **Verify DLQ counter stays at 0 after one trading session**

```bash
curl -s http://localhost:9125/metrics | grep "intelligence_pipeline_signal_dlq_total"
```

Expected: `intelligence_pipeline_signal_dlq_total 0.0`

- [ ] **Verify signal_coverage_pct metrics appear in Prometheus**

```bash
curl -s http://localhost:9126/metrics | grep "signal_coverage_pct"
```

Expected: one line per `{symbol, tf}` combination from active contracts

- [ ] **Run roadmap consistency check**

```bash
node gsd-tools.cjs roadmap analyze
```

---

## Threat Model

| Risk | Mitigation |
|------|-----------|
| TRUNCATE deletes future-valuable data | All 661K rows are pre-production dev data (design doc rationale). Verified by pre-condition count check in Task 0 Step 1. |
| Kafka offset reset replays wrong messages | `rpk group seek --to latest` skips to latest — only future messages are consumed. |
| NOT NULL migration fails if stale null rows exist | Step 2 in Task 3 explicitly checks for nulls before applying. Fail-loud by design. |
| signal_auditor DLQ false positives on weekends | `_any_session_near_open` and `session_window_for_date` gate on trading days only. Non-trading days return `(None, None)` and are skipped. |
| `DQ_NULL_CIS_RATE` removal breaks existing Grafana panels | Panels referencing `dq_null_cis_rate` will go no-data. The constraint makes the metric permanently 0 — remove or replace panels with `signal_coverage_pct`. |
