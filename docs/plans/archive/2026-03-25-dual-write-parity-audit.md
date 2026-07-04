# Dual-Write Parity Audit — Implementation Plan

**Last Updated:** 2026-05-02

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix broken topic wiring from the refactoring sprint, then deploy `FeatureSnapshotWriterAgent` as a shadow consumer writing to `feature_snapshots_shadow` — enabling automated parity validation before primary-write cutover.

**Architecture:** `SignalGeneratorAgent` already correctly publishes `BarIntelligenceRecord` to `topic_intelligence_journal`. Two independent consumer groups will read from this single topic: `feature_writer_group` (existing — writes to `intelligence_features`) and `feature_snapshot_writer_group` (new — writes to `feature_snapshots_shadow`). The auditor compares both tables row-by-row on a timer.

**Tech Stack:** Python asyncio, asyncpg, aiokafka, structlog, Pydantic, TimescaleDB/PostgreSQL

---

## Context: What the Refactoring Sprint Broke

The March 2026 agentic DAG sprint left three wiring bugs:

| Bug | Location | Impact |
|-----|----------|--------|
| `topic_feature_processed` imported but not defined in `stream_keys.py` | Both services | `ImportError` at startup |
| `feature_writer_service.py` subscribes to `topic_feature_processed` | `feature_writer_service.py:381` | Should subscribe to `topic_intelligence_journal` |
| `feature_compute_agent.py` publishes `IntelligenceJournal` (wrong schema) to undefined topic | `feature_compute_agent.py:971-986` | Dead code — remove |

The correct DAG is already in place everywhere else:
```
SignalGeneratorAgent
  └─► BarIntelligenceRecord → development.intelligence.journal
        ├─► feature_writer_group  → intelligence_features      (fix wiring)
        └─► feature_snapshot_writer_group → feature_snapshots_shadow (new, Task 3)
```

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/core/stream_keys.py` | Modify | Remove stray `topic_feature_processed`; add `topic_audit` |
| `services/feature_compute_agent.py` | Modify | Remove dead `IntelligenceJournal` publication block |
| `services/feature_writer_service.py` | Modify | Fix topic subscription to `topic_intelligence_journal` |
| `src/persistence/repository/feature_repository.py` | Modify | Accept configurable table name (DRY — reused by historian) |
| `services/feature_snapshot_writer_agent.py` | Create | Shadow writer: `intelligence.journal` → `feature_snapshots_shadow` |
| `production/migrations/051_feature_snapshots_shadow.sql` | Create | Shadow table DDL |
| `tests/unit/test_feature_snapshot_writer_agent.py` | Create | Unit tests for historian parse + write path |
| `production/systemd/indicagent-feature-snapshot-writer.service` | Create | systemd unit |

---

## Task 1: Remove `topic_feature_processed` — fix the import crash

**Files:**
- Modify: `src/core/stream_keys.py`
- Modify: `services/feature_compute_agent.py`
- Modify: `services/feature_writer_service.py`

- [ ] **Step 1: Write the failing import test**

```python
# tests/unit/test_stream_keys_imports.py
def test_topic_feature_processed_does_not_exist():
    """Verify stale topic is gone — prevents silent re-introduction."""
    import src.core.stream_keys as sk
    assert not hasattr(sk, "topic_feature_processed"), \
        "topic_feature_processed was re-added; use topic_intelligence_journal instead"

def test_topic_intelligence_journal_exists():
    from src.core.stream_keys import topic_intelligence_journal
    assert topic_intelligence_journal("development") == "development.intelligence.journal"

def test_topic_audit_exists():
    from src.core.stream_keys import topic_audit
    assert topic_audit("development") == "development.audit"
```

Run: `.venv/bin/pytest tests/unit/test_stream_keys_imports.py -v`
Expected: FAIL (first test passes, but `topic_audit` doesn't exist yet)

- [ ] **Step 2: Add `topic_audit` to `stream_keys.py`, do NOT add `topic_feature_processed`**

In `src/core/stream_keys.py`, after `topic_intelligence_journal`:

```python
def topic_audit(env_name: str) -> str:
    """Kafka topic for parity violation and audit events from ParityAuditorAgent."""
    return f"{env_prefix(env_name)}audit"
```

Run: `.venv/bin/pytest tests/unit/test_stream_keys_imports.py -v`
Expected: PASS all 3

- [ ] **Step 3: Remove dead `IntelligenceJournal` publication from `feature_compute_agent.py`**

Remove lines 970–988 in `services/feature_compute_agent.py` (the entire `try:` block that builds `feature_journal` and publishes to `topic_feature_processed`). Also remove the imports:

```python
# Remove these from the import block:
from src.core.schemas.intelligence_journal import IntelligenceJournal, ProvenanceChain
# Remove from stream_keys imports:
topic_feature_processed,
```

Verify the agent still imports cleanly:
```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, '.')
# Patch the missing indicator_service import (pre-existing issue)
import types; sys.modules['services.indicator_service'] = types.ModuleType('services.indicator_service')
from services import feature_compute_agent
print('OK')
"
```

- [ ] **Step 4: Fix `feature_writer_service.py` topic subscription**

Change the topic subscription in `services/feature_writer_service.py`:

```python
# Remove this import:
from src.core.stream_keys import (
    topic_cross_asset,
    topic_feature_processed,   # <-- remove
    topic_system_events,
)

# Add this import:
from src.core.stream_keys import (
    topic_cross_asset,
    topic_intelligence_journal,  # <-- add
    topic_system_events,
)
```

In `_start_consumer()`, change:
```python
# Before:
topics = [
    topic_feature_processed(self._env_name),
    ...
]

# After:
topics = [
    topic_intelligence_journal(self._env_name),
    ...
]
```

Update the docstring comment from "intelligence.record" to "intelligence.journal".

**Also fix two additional broken references in `_process_loop()` — the import fix above does not cover these:**

- **Line ~640**: `topic_intelligence_record(self._env_name)` — this function does not exist in `stream_keys.py`. Replace with `topic_intelligence_journal(self._env_name)` and ensure `topic_intelligence_journal` is assigned to a local variable before use.
- **Line ~671**: `feature_processed_topic` — referenced in a routing condition but never assigned in this scope → `NameError` at runtime. Update the condition to match against `topic_intelligence_journal(self._env_name)`.

Verify the service imports cleanly after all four changes:
```bash
.venv/bin/python -c "import sys; sys.path.insert(0, '.'); from services import feature_writer_service; print('OK')"
```

- [ ] **Step 5: Run unit tests — verify no regressions**

```bash
.venv/bin/pytest tests/unit/ -q --ignore=tests/unit/service_tests 2>&1 | tail -5
```

Expected: same pass/fail counts as before (no new failures).

- [ ] **Step 6: Commit the wiring fixes**

```bash
git add src/core/stream_keys.py services/feature_compute_agent.py services/feature_writer_service.py tests/unit/test_stream_keys_imports.py
git commit -m "fix(wiring): remove undefined topic_feature_processed, fix feature_writer to consume intelligence.journal"
```

---

## Task 2: Shadow table migration

**Files:**
- Create: `production/migrations/051_feature_snapshots_shadow.sql`

- [ ] **Step 1: Write the migration**

```sql
-- production/migrations/051_feature_snapshots_shadow.sql
-- Shadow table for parity validation — mirrors intelligence_features.
-- Written by FeatureSnapshotWriterAgent (consumer group: feature_snapshot_writer_group).
-- Compared against intelligence_features by ParityAuditorAgent on 5-minute schedule.
-- DROP after parity certification and primary-write cutover.

-- IMPORTANT: Use INCLUDING DEFAULTS INCLUDING CONSTRAINTS only — NOT INCLUDING ALL.
-- INCLUDING ALL copies indexes and partitioning constraints from the source
-- hypertable, which causes TimescaleDB to reject the subsequent create_hypertable
-- call ("table already has a partitioning structure"). TimescaleDB recreates
-- indexes itself after create_hypertable — do not pre-copy them.
CREATE TABLE IF NOT EXISTS feature_snapshots_shadow (
    LIKE intelligence_features INCLUDING DEFAULTS INCLUDING CONSTRAINTS
);

-- TimescaleDB hypertable — same chunk interval as source.
-- Skip if already created (idempotent).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM timescaledb_information.hypertables
        WHERE hypertable_name = 'feature_snapshots_shadow'
    ) THEN
        PERFORM create_hypertable(
            'feature_snapshots_shadow', 'ts',
            chunk_time_interval => INTERVAL '1 day',
            if_not_exists => TRUE
        );
    END IF;
END $$;

-- Parity audit log: row-level divergences between the two tables.
CREATE TABLE IF NOT EXISTS feature_parity_violations (
    id          BIGSERIAL PRIMARY KEY,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ts          TIMESTAMPTZ NOT NULL,
    symbol      TEXT        NOT NULL,
    tf          TEXT        NOT NULL,
    field       TEXT        NOT NULL,  -- which column diverged
    legacy_val  TEXT,                  -- from intelligence_features
    shadow_val  TEXT,                  -- from feature_snapshots_shadow
    run_id      UUID        NOT NULL   -- links rows from same audit cycle
);

CREATE INDEX ON feature_parity_violations (detected_at DESC);
CREATE INDEX ON feature_parity_violations (symbol, tf, detected_at DESC);
```

- [ ] **Step 2: Apply migration**

```bash
docker exec timescaledb psql -U postgres -d indicagent \
  -f /path/to/production/migrations/051_feature_snapshots_shadow.sql
```

Verify:
```bash
docker exec timescaledb psql -U postgres -d indicagent \
  -c "\d feature_snapshots_shadow" -c "\d feature_parity_violations"
```

Expected: both tables listed with correct columns.

- [ ] **Step 3: Commit**

```bash
git add production/migrations/051_feature_snapshots_shadow.sql
git commit -m "feat(db): add feature_snapshots_shadow and feature_parity_violations tables"
```

---

## Task 3: Extend `FeatureRepository` with configurable table name

**Files:**
- Modify: `src/persistence/repository/feature_repository.py`
- Test: `tests/unit/test_feature_repository.py`

The `FeatureSnapshotWriterAgent` will write to `feature_snapshots_shadow` using exactly the same SQL as `FeatureWriterService`. Rather than duplicating the 31-column INSERT, make `FeatureRepository` accept a `table_name` parameter. One SQL template, two instantiations.

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_feature_repository.py
import asyncio
from unittest.mock import AsyncMock, MagicMock
from src.persistence.repository.feature_repository import FeatureRepository

def test_feature_repository_uses_default_table():
    db = MagicMock()
    db.execute_command = AsyncMock()
    repo = FeatureRepository(db)
    assert "intelligence_features" in repo._insert_sql

def test_feature_repository_accepts_shadow_table():
    db = MagicMock()
    db.execute_command = AsyncMock()
    repo = FeatureRepository(db, table_name="feature_snapshots_shadow")
    assert "feature_snapshots_shadow" in repo._insert_sql
    assert "intelligence_features" not in repo._insert_sql

def test_insert_shadow_calls_correct_sql():
    db = MagicMock()
    db.execute_command = AsyncMock()
    repo = FeatureRepository(db, table_name="feature_snapshots_shadow")
    params = tuple(range(31))
    assert len(params) == 31  # guard: catches silent field count regressions
    asyncio.run(repo.insert(params))
    db.execute_command.assert_awaited_once()
    call_sql = db.execute_command.call_args[0][0]
    assert "feature_snapshots_shadow" in call_sql
```

Run: `.venv/bin/pytest tests/unit/test_feature_repository.py -v`
Expected: FAIL

- [ ] **Step 2: Refactor `FeatureRepository`**

Replace `src/persistence/repository/feature_repository.py` with:

```python
"""FeatureRepository — write-side persistence for intelligence feature vectors.

Accepts a configurable table_name so the same SQL template is reused by both
FeatureWriterService (→ intelligence_features) and FeatureSnapshotWriterAgent
(→ feature_snapshots_shadow). Never duplicate the 31-column INSERT.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_INSERT_SQL_TEMPLATE = """
INSERT INTO {table} (
    ts, symbol, tf, platform, source, schema_version,
    bar, i1, i2, i3, i4, i5, smc, i6, i7,
    bar_close_ts, i1_computed_at, computed_at,
    winner_plugin, winner_confidence, winner_direction,
    signals_evaluated, signals_after_quality, signals_after_regime,
    signals_after_tod, signals_after_calibration,
    ledger_written, pipeline_latency_ms,
    i7_computed_at, session_type, days_to_expiry
)
VALUES (
    $1, $2, $3, $4, $5, $6,
    $7::jsonb, $8::jsonb, $9::jsonb, $10::jsonb, $11::jsonb,
    $12::jsonb, $13::jsonb, $14::jsonb, $15::jsonb,
    $16, $17, $18,
    $19, $20, $21,
    $22, $23, $24,
    $25, $26,
    $27, $28,
    $29, $30, $31
)
ON CONFLICT (ts, symbol, tf) DO NOTHING
"""


class FeatureRepository:
    """Write-side repository for intelligence_features (or shadow table).

    Args:
        db_manager: Open DatabaseManager instance.
        table_name: Target table. Defaults to 'intelligence_features'.
                    Pass 'feature_snapshots_shadow' for historian shadow writes.
    """

    def __init__(self, db_manager: Any, table_name: str = "intelligence_features") -> None:
        self._db_manager = db_manager
        self._table_name = table_name
        self._insert_sql = _INSERT_SQL_TEMPLATE.format(table=table_name)

    async def insert(self, params: tuple) -> None:
        """Insert one 31-element params tuple. Skips on conflict (ts, symbol, tf)."""
        await self._db_manager.execute_command(self._insert_sql, *params)
        logger.debug("feature_row_written", table=self._table_name)

    # Legacy compat — callers passing a dict get a clear error instead of a silent noop.
    async def insertBatch(self, feature_data: Any) -> None:
        raise TypeError(
            "FeatureRepository.insertBatch() removed — use insert(params_tuple). "
            "Build params via feature_writer_service._record_to_insert_params()."
        )
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest tests/unit/test_feature_repository.py -v
```

Expected: PASS

- [ ] **Step 4: Verify no remaining `insertBatch` callers**

`insertBatch()` is replaced with a `TypeError` raiser. Confirm zero callers exist before committing — a missed caller will crash at runtime, not at import time.

```bash
grep -r "insertBatch" src/ services/ --include="*.py"
# Expected: no output
```

- [ ] **Step 5: Commit**

```bash
git add src/persistence/repository/feature_repository.py tests/unit/test_feature_repository.py
git commit -m "refactor(repository): FeatureRepository accepts table_name for shadow writes"
```

---

## Task 4: Create `FeatureSnapshotWriterAgent`

**Files:**
- Create: `services/feature_snapshot_writer_agent.py`
- Create: `tests/unit/test_feature_snapshot_writer_agent.py`

The historian is a thin consumer. It reads `BarIntelligenceRecord` from `intelligence.journal` (same topic as `FeatureWriterService`, different consumer group), converts to insert params using the already-tested `_record_to_insert_params()` from `feature_writer_service.py`, and writes to `feature_snapshots_shadow` via `FeatureRepository`.

No `StreamMerger`, no `DataWriterAgent` — `BarIntelligenceRecord` is already a complete atomic record.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_feature_snapshot_writer_agent.py
import asyncio
from collections import defaultdict
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from services.feature_snapshot_writer_agent import FeatureSnapshotWriterAgent

def _make_settings():
    s = MagicMock()
    s.env_name = "development"
    s.kafka_bootstrap_servers = "localhost:9092"
    s.database_url = "postgresql://localhost/test"
    return s

def test_historian_consumer_group_is_distinct():
    """Historian must use a different consumer group than feature_writer_service.

    NOTE: This test imports from feature_writer_service at module level. That import
    will crash with ImportError until Task 1 (wiring fix) is fully applied — including
    the fixes for lines ~640 and ~671 in feature_writer_service.py, not just line 35/381.
    Run Task 1 completely before running this test file.
    """
    from services.feature_snapshot_writer_agent import CONSUMER_GROUP
    assert CONSUMER_GROUP == "feature_snapshot_writer_group"
    # Sanity: not the same as the primary writer
    from services.feature_writer_service import CONSUMER_GROUP as PRIMARY_GROUP
    assert CONSUMER_GROUP != PRIMARY_GROUP

def test_historian_subscribes_to_intelligence_journal():
    """Historian must consume from the same topic as FeatureWriterService."""
    from services.feature_snapshot_writer_agent import CONSUMER_TOPIC_FN
    from src.core.stream_keys import topic_intelligence_journal
    assert CONSUMER_TOPIC_FN("development") == topic_intelligence_journal("development")

def test_historian_writes_to_shadow_table():
    """FeatureRepository must be instantiated with feature_snapshots_shadow."""
    from services.feature_snapshot_writer_agent import SHADOW_TABLE
    assert SHADOW_TABLE == "feature_snapshots_shadow"

def test_parse_valid_bar_intelligence_record():
    from services.feature_snapshot_writer_agent import FeatureSnapshotWriterAgent
    agent = FeatureSnapshotWriterAgent.__new__(FeatureSnapshotWriterAgent)
    agent.logger = MagicMock()
    agent._parse_errors = MagicMock()
    agent._parse_errors.inc = MagicMock()
    agent._expiry_map = {}  # required by _record_to_insert_params in consume path tests

    # Minimal valid BarIntelligenceRecord JSON — use model to generate
    from src.intelligence.schemas import BarIntelligenceRecord, IntelligenceEvent, OHLCVBar
    from src.intelligence.schemas import I1Indicators, I2Events, I3Structure, I4Context
    from src.intelligence.schemas import I5Patterns, I6Confluence, SMCContext
    event = IntelligenceEvent(
        ts=datetime(2026, 3, 26, 10, 0, tzinfo=UTC),
        symbol="ES", tf="1m", source="live",
        bar=OHLCVBar(o=5100, h=5110, l=5095, c=5105, v=1000),
        i1=I1Indicators(), i2=I2Events(), i3=I3Structure(),
        i4=I4Context(), i5=I5Patterns(), smc=SMCContext(), i6=I6Confluence(),
    )
    record = BarIntelligenceRecord(
        intelligence=event, ranked_signals=[],
        winner_plugin=None, winner_confidence=None, winner_direction=None,
        signals_evaluated=0, signals_after_quality=0, signals_after_regime=0,
        signals_after_tod=0, signals_after_calibration=0,
        ledger_written=False, session_type="rth",
        i7_computed_at=datetime(2026, 3, 26, 10, 0, tzinfo=UTC),
        pipeline_latency_ms=12.5,
    )
    raw = record.model_dump_json()
    result = agent._parse_record(raw)
    assert result is not None
    assert result.intelligence.symbol == "ES"

def test_parse_invalid_json_returns_none():
    agent = FeatureSnapshotWriterAgent.__new__(FeatureSnapshotWriterAgent)
    agent.logger = MagicMock()
    agent._parse_errors = MagicMock()
    agent._parse_errors.inc = MagicMock()
    result = agent._parse_record(b"not_json")
    assert result is None
    agent._parse_errors.inc.assert_called_once()
```

Run: `.venv/bin/pytest tests/unit/test_feature_snapshot_writer_agent.py -v`
Expected: FAIL (module doesn't exist yet)

- [ ] **Step 2: Create `services/feature_snapshot_writer_agent.py`**

```python
#!/usr/bin/env python3
"""
FeatureSnapshotWriterAgent — shadow persistence for parity validation.

Consumes BarIntelligenceRecord from intelligence.journal under consumer group
'feature_snapshot_writer_group' (separate from 'feature_writer_group') and writes to
feature_snapshots_shadow. ParityAuditorAgent compares the two tables to certify
that FeatureRepository produces identical results to FeatureWriterService before
primary-write cutover.

Design invariant: this agent is intentionally thin — no business logic.
All parsing is delegated to _record_to_insert_params() from feature_writer_service.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import structlog
from pydantic import ValidationError

from services.feature_writer_service import _build_expiry_map, _record_to_insert_params
from src.config.settings import Settings
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient
from src.core.service_utils import setup_service_logging
from src.core.stream_keys import topic_intelligence_journal, topic_system_events
from src.intelligence.schemas import BarIntelligenceRecord
from src.observability.metrics import counter, gauge, start_metrics_server
from src.persistence.repository.feature_repository import FeatureRepository

# ── Module-level constants ────────────────────────────────────────────────────

CONSUMER_GROUP: str = "feature_snapshot_writer_group"
CONSUMER_TOPIC_FN = topic_intelligence_journal
SHADOW_TABLE: str = "feature_snapshots_shadow"
BATCH_SIZE: int = 50
FLUSH_INTERVAL_SECS: float = 5.0
METRICS_PORT: int = 9119


class FeatureSnapshotWriterAgent:
    """Shadow writer: intelligence.journal → feature_snapshots_shadow."""

    def __init__(self) -> None:
        self.running = False
        self.shutdown_requested = False
        self.start_time = datetime.now(UTC)

        setup_service_logging("logs/feature_snapshot_writer_agent.log")
        self.logger = structlog.get_logger(__name__)

        self._settings = Settings()
        self._env_name = self._settings.env_name.strip()
        self._kafka_bootstrap = self._settings.kafka_bootstrap_servers

        self._expiry_map: dict = {}
        self._buffer: list[tuple] = []
        self._last_flush = datetime.now(UTC)

        self._db: DatabaseManager | None = None
        self._repo: FeatureRepository | None = None
        self._consumer: KafkaConsumerClient | None = None

        self._events_consumed = counter(
            "feature_snapshot_writer_events_consumed_total",
            "BarIntelligenceRecords consumed by FeatureSnapshotWriterAgent",
        )
        self._shadow_writes = counter(
            "feature_snapshot_writer_shadow_writes_total",
            "Rows written to feature_snapshots_shadow",
        )
        self._parse_errors = counter(
            "feature_snapshot_writer_parse_errors_total",
            "BarIntelligenceRecord parse failures",
        )
        self._write_errors = counter(
            "feature_snapshot_writer_write_errors_total",
            "Shadow write failures",
        )
        self._consumer_lag = gauge(
            "persistence_consumer_lag",
            "Estimated Kafka consumer lag (buffer size proxy)",
        )

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum: int, frame: Any) -> None:
        self.logger.info("shutdown_signal_received", signal=signum)
        self.shutdown_requested = True

    def _parse_record(self, raw: bytes | str) -> BarIntelligenceRecord | None:
        try:
            return BarIntelligenceRecord.model_validate_json(raw)
        except (ValidationError, ValueError) as exc:
            self.logger.warning("snapshot_writer_parse_failed", error=str(exc))
            self._parse_errors.inc()
            return None

    async def _flush(self) -> None:
        if not self._buffer or self._repo is None:
            return
        batch = self._buffer[:]
        self._buffer.clear()
        for params in batch:
            try:
                await self._repo.insert(params)
                self._shadow_writes.inc()
            except Exception as exc:
                self.logger.error("shadow_write_failed", error=str(exc))
                self._write_errors.inc()
        self._last_flush = datetime.now(UTC)
        self._consumer_lag.set(len(self._buffer))

    async def _consume_loop(self) -> None:
        assert self._consumer is not None
        _journal_topic = topic_intelligence_journal(self._env_name)

        async for topic, key, payload in self._consumer.messages():
            if self.shutdown_requested:
                break
            try:
                if topic != _journal_topic:
                    continue  # skip system.events on this consumer

                raw = payload if isinstance(payload, (bytes, str)) else str(payload)
                record = self._parse_record(raw)
                if record is None:
                    continue

                params = _record_to_insert_params(record, self._expiry_map)
                self._buffer.append(params)
                self._events_consumed.inc()

                now = datetime.now(UTC)
                if (
                    len(self._buffer) >= BATCH_SIZE
                    or (now - self._last_flush).total_seconds() >= FLUSH_INTERVAL_SECS
                ):
                    await self._flush()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.logger.error("consume_loop_error", error=str(exc))

    async def start(self) -> None:
        self.logger.info("FeatureSnapshotWriterAgent starting", shadow_table=SHADOW_TABLE)
        start_metrics_server(port=METRICS_PORT)

        # Build expiry map (same as FeatureWriterService)
        try:
            self._expiry_map = _build_expiry_map(self._settings)
            self.logger.info("expiry_map_built", contracts=len(self._expiry_map))
        except Exception as exc:
            self.logger.warning("expiry_map_failed", error=str(exc))

        # DB connection → shadow repository
        self._db = DatabaseManager(self._settings.database_url)
        await self._db.initialize()
        self._repo = FeatureRepository(self._db, table_name=SHADOW_TABLE)

        # Kafka consumer — distinct group so offsets are tracked independently
        self._consumer = KafkaConsumerClient(
            topic_intelligence_journal(self._env_name),
            topic_system_events(self._env_name),
            bootstrap_servers=self._kafka_bootstrap,
            group_id=CONSUMER_GROUP,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
        )
        await self._consumer.start()
        self.logger.info(
            "snapshot_writer_consumer_started",
            topic=topic_intelligence_journal(self._env_name),
            group=CONSUMER_GROUP,
        )

        self.running = True
        try:
            await self._consume_loop()
        finally:
            await self.stop()

    async def stop(self) -> None:
        self.logger.info("FeatureSnapshotWriterAgent stopping")
        self.running = False
        self.shutdown_requested = True
        await self._flush()  # drain buffer before exit
        if self._consumer:
            await self._consumer.stop()
        if self._db:
            await self._db.close()
        self.logger.info("FeatureSnapshotWriterAgent stopped")


async def main() -> None:
    agent = FeatureSnapshotWriterAgent()
    await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest tests/unit/test_feature_snapshot_writer_agent.py -v
```

Expected: PASS all tests

- [ ] **Step 4: Run full unit suite (no new failures)**

```bash
.venv/bin/pytest tests/unit/ -q --ignore=tests/unit/service_tests 2>&1 | tail -5
```

- [ ] **Step 5: Commit**

```bash
git add services/feature_snapshot_writer_agent.py tests/unit/test_feature_snapshot_writer_agent.py
git commit -m "feat(service): add FeatureSnapshotWriterAgent shadow writer for parity validation"
```

---

## Task 5: systemd unit for `FeatureSnapshotWriterAgent`

**Files:**
- Create: `production/systemd/indicagent-feature-snapshot-writer.service`

- [ ] **Step 1: Create unit file**

```ini
# production/systemd/indicagent-feature-snapshot-writer.service
[Unit]
Description=IndicAgent Feature Snapshot Writer Agent (Shadow Writer)
After=network.target
Wants=network.target

[Service]
Type=simple
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/feature_snapshot_writer_agent.py
Restart=on-failure
RestartSec=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Install and enable**

```bash
sudo cp production/systemd/indicagent-feature-snapshot-writer.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable indicagent-feature-snapshot-writer
sudo systemctl start indicagent-feature-snapshot-writer
sudo systemctl status indicagent-feature-snapshot-writer
```

Expected: `active (running)`

- [ ] **Step 3: Verify shadow rows appear**

After 1 minute:
```bash
docker exec timescaledb psql -U postgres -d indicagent \
  -c "SELECT COUNT(*), MIN(ts), MAX(ts) FROM feature_snapshots_shadow WHERE ts > NOW() - INTERVAL '5 minutes';"
```

Expected: row count > 0, timestamps recent.

- [ ] **Step 4: Commit**

```bash
git add production/systemd/indicagent-feature-snapshot-writer.service
git commit -m "feat(ops): add indicagent-feature-snapshot-writer systemd unit"
```

---

## Verification Checklist

- [ ] `topic_feature_processed` no longer referenced anywhere in `services/` or `src/`
- [ ] `feature_writer_service.py` subscribes to `topic_intelligence_journal`
- [ ] `feature_compute_agent.py` no longer publishes `IntelligenceJournal`
- [ ] `feature_snapshots_shadow` table exists in TimescaleDB
- [ ] `feature_parity_violations` table exists in TimescaleDB
- [ ] `FeatureSnapshotWriterAgent` writes to shadow table (confirm with row count query above)
- [ ] `FeatureRepository.insert()` works for both tables (unit tests pass)
- [ ] All unit tests pass with no new failures
- [ ] Both `feature_writer_group` and `feature_snapshot_writer_group` consumer groups visible in Redpanda:
  ```bash
  docker exec redpanda rpk group list
  ```
