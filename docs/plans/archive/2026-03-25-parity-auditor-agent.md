# Parity Auditor Agent — Implementation Plan

**Last Updated:** 2026-05-02

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an automated `ParityAuditorAgent` that continuously compares `intelligence_features` (primary writer) against `feature_snapshots_shadow` (historian writer), emits per-(symbol, tf) violation metrics, and certifies parity when the match rate exceeds the threshold — enabling automated cutover without human SQL queries.

**Architecture:** The auditor runs a periodic comparison loop (every 5 minutes) independent of the Kafka pipeline. It queries both DB tables for the same time window, computes a per-(symbol, tf) match rate, logs violations to `feature_parity_violations`, and publishes structured events to `development.audit`. After `CERTIFICATION_THRESHOLD` consecutive clean cycles, it publishes `SHADOW_PARITY_CERTIFIED` to `development.system.events` — this is the automated gate for primary-write cutover. No manual SQL. No human-in-the-loop for the happy path.

**Tech Stack:** Python asyncio, asyncpg, structlog, Pydantic, TimescaleDB, Kafka (`topic_audit(env_name)` → `{env}.audit`, `topic_system_events(env_name)` → `{env}.system.events`)

---

## Renaissance Design Constraints

> *"A rule that works globally is weaker than one that works in a specific regime. Always ask: under what conditions does this hold?"*

1. **Segment by (symbol, tf)**: match rates are tracked per pair, not globally. A single broken symbol must not mask 100% parity on others.
2. **Instrument everything**: every comparison cycle emits structured metrics; every violation is stored in `feature_parity_violations` (never dropped — it's training data for diagnosing writer bugs).
3. **Automated certification**: the auditor self-certifies after `N` consecutive clean cycles per every active (symbol, tf). No human gate on the happy path.
4. **Field-level granularity**: violations identify *which* column diverges (i1 vs i3 vs winner_plugin), not just that a row mismatches — enabling targeted debugging.
5. **Degrade gracefully**: auditor failure never affects the primary write path. It runs in a separate process with its own DB connection.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/persistence/repository/parity_repository.py` | Create | Read-only queries for both tables; violation inserts |
| `services/parity_auditor_agent.py` | Create | Comparison engine, certification logic, Kafka publication |
| `tests/unit/test_parity_repository.py` | Create | Repository query contract tests |
| `tests/unit/test_parity_auditor_agent.py` | Create | Comparison logic, certification threshold, violation routing |
| `production/systemd/indicagent-parity-auditor.service` | Create | systemd unit |

**Prerequisite:** dual-write-parity-audit plan must be complete (shadow table + historian agent running).

---

## Task 1: `ParityRepository` — read-side queries for both tables

**Files:**
- Create: `src/persistence/repository/parity_repository.py`
- Test: `tests/unit/test_parity_repository.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_parity_repository.py
import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from src.persistence.repository.parity_repository import ParityRepository

def test_get_primary_rows_queries_intelligence_features():
    db = MagicMock()
    db.execute_query = AsyncMock(return_value=[])
    repo = ParityRepository(db)
    asyncio.run(repo.get_primary_rows("ES", "1m", lookback_secs=300))
    sql = db.execute_query.call_args[0][0]
    assert "intelligence_features" in sql
    assert "ORDER BY ts DESC" in sql

def test_get_shadow_rows_queries_feature_snapshots_shadow():
    db = MagicMock()
    db.execute_query = AsyncMock(return_value=[])
    repo = ParityRepository(db)
    asyncio.run(repo.get_shadow_rows("ES", "1m", lookback_secs=300))
    sql = db.execute_query.call_args[0][0]
    assert "feature_snapshots_shadow" in sql

def test_insert_violation_calls_execute_command():
    db = MagicMock()
    db.execute_command = AsyncMock()
    run_id = uuid.uuid4()
    repo = ParityRepository(db)
    asyncio.run(repo.insert_violation(
        ts=datetime(2026, 3, 26, 10, 0, tzinfo=UTC),
        symbol="ES", tf="1m", field="winner_plugin",
        legacy_val="TrendFollowing", shadow_val="MomentumBreakout",
        run_id=run_id,
    ))
    db.execute_command.assert_awaited_once()
    call_sql = db.execute_command.call_args[0][0]
    assert "feature_parity_violations" in call_sql

def test_returns_empty_on_query_failure():
    db = MagicMock()
    db.execute_query = AsyncMock(side_effect=Exception("timeout"))
    repo = ParityRepository(db)
    result = asyncio.run(repo.get_primary_rows("ES", "1m", lookback_secs=300))
    assert result == []
```

Run: `.venv/bin/pytest tests/unit/test_parity_repository.py -v`
Expected: FAIL

- [ ] **Step 2: Create `parity_repository.py`**

```python
"""ParityRepository — read-side queries for parity auditor.

Provides row fetches from both intelligence_features (primary) and
feature_snapshots_shadow (historian), plus violation inserts into
feature_parity_violations. All writes go to feature_parity_violations only —
this repository never modifies the tables it reads.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_COMPARE_COLUMNS = [
    "ts", "symbol", "tf", "source", "schema_version",
    "bar", "i1", "i2", "i3", "i4", "i5", "smc", "i6",
    "winner_plugin", "winner_confidence", "winner_direction",
    "signals_evaluated", "signals_after_quality", "signals_after_regime",
    "signals_after_tod", "signals_after_calibration",
    "ledger_written", "session_type",
]
# NOTE: _COMPARE_COLUMNS and _COMPARE_FIELDS must include the same set of
# non-scalar fields (excluding ts/symbol/tf/bar which are join keys or JSONB).
# "source" appears in both — divergences in source would indicate a schema
# mismatch between the two write paths and must not go undetected.

_INSERT_VIOLATION_SQL = """
INSERT INTO feature_parity_violations
    (detected_at, ts, symbol, tf, field, legacy_val, shadow_val, run_id)
VALUES (NOW(), $1, $2, $3, $4, $5, $6, $7)
"""

_FETCH_SQL = """
SELECT {cols}
FROM {table}
WHERE symbol = $1 AND tf = $2
  AND ts > NOW() - make_interval(secs => $3)
ORDER BY ts DESC
LIMIT 500
"""
# NOTE: {cols} and {table} are formatted from internal module-level constants only —
# never from user input. $3 is a parameterized query value (no SQL injection risk).


class ParityRepository:
    """Read-side repository for parity comparison queries."""

    def __init__(self, db_manager: Any) -> None:
        self._db = db_manager

    async def get_primary_rows(
        self, symbol: str, tf: str, lookback_secs: int
    ) -> list[dict[str, Any]]:
        """Fetch recent rows from intelligence_features."""
        return await self._fetch("intelligence_features", symbol, tf, lookback_secs)

    async def get_shadow_rows(
        self, symbol: str, tf: str, lookback_secs: int
    ) -> list[dict[str, Any]]:
        """Fetch recent rows from feature_snapshots_shadow."""
        return await self._fetch("feature_snapshots_shadow", symbol, tf, lookback_secs)

    async def _fetch(
        self, table: str, symbol: str, tf: str, lookback_secs: int
    ) -> list[dict[str, Any]]:
        # {cols} and {table} are hardcoded module-level constants — not user input.
        sql = _FETCH_SQL.format(cols=", ".join(_COMPARE_COLUMNS), table=table)
        try:
            return await self._db.execute_query(sql, symbol, tf, lookback_secs)
        except Exception as exc:
            logger.warning("parity_fetch_failed", table=table, symbol=symbol, tf=tf, error=str(exc))
            return []

    async def insert_violation(
        self,
        ts: datetime,
        symbol: str,
        tf: str,
        field: str,
        legacy_val: str | None,
        shadow_val: str | None,
        run_id: uuid.UUID,
    ) -> None:
        try:
            await self._db.execute_command(
                _INSERT_VIOLATION_SQL,
                ts, symbol, tf, field,
                str(legacy_val)[:500] if legacy_val is not None else None,
                str(shadow_val)[:500] if shadow_val is not None else None,
                str(run_id),
            )
        except Exception as exc:
            logger.error("violation_insert_failed", symbol=symbol, tf=tf, field=field, error=str(exc))
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest tests/unit/test_parity_repository.py -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/persistence/repository/parity_repository.py tests/unit/test_parity_repository.py
git commit -m "feat(repository): add ParityRepository for parity audit queries"
```

---

## Task 2: Comparison engine — pure functions (testable in isolation)

**Files:**
- Create: `src/persistence/logic/parity_comparator.py`
- Test: `tests/unit/test_parity_comparator.py`

The comparison logic is pure — no I/O, no async. Extract it so it can be tested without mocking DB or Kafka.

- [ ] **Step 1: Write tests**

```python
# tests/unit/test_parity_comparator.py
from datetime import UTC, datetime
from src.persistence.logic.parity_comparator import (
    build_row_index,
    compare_rows,
    ComparisonResult,
)

_TS = datetime(2026, 3, 26, 10, 0, tzinfo=UTC)

def _row(symbol="ES", tf="1m", winner="TrendFollowing", i1=None):
    return {
        "ts": _TS, "symbol": symbol, "tf": tf,
        "winner_plugin": winner,
        "i1": i1 or {"rsi": 55.0},
        "signals_evaluated": 10,
        "ledger_written": True,
    }

def test_build_row_index_keyed_by_ts():
    rows = [_row(), _row(symbol="NQ")]
    idx = build_row_index(rows)
    assert _TS in idx
    # both rows have same ts in this test — last one wins; but normally ts is unique
    assert len(idx) >= 1

def test_identical_rows_produce_no_violations():
    primary = [_row()]
    shadow = [_row()]
    result = compare_rows(primary, shadow)
    assert result.match_count == 1
    assert result.violation_count == 0
    assert len(result.violations) == 0

def test_missing_shadow_row_is_a_violation():
    primary = [_row()]
    shadow = []
    result = compare_rows(primary, shadow)
    assert result.violation_count == 1
    assert result.violations[0].field == "MISSING_IN_SHADOW"

def test_field_divergence_detected():
    primary = [_row(winner="TrendFollowing")]
    shadow = [_row(winner="MomentumBreakout")]
    result = compare_rows(primary, shadow)
    assert result.violation_count >= 1
    fields = [v.field for v in result.violations]
    assert "winner_plugin" in fields

def test_match_rate_is_1_when_identical():
    rows = [_row(winner=f"Plugin{i}") for i in range(10)]
    result = compare_rows(rows, rows)
    assert result.match_rate == 1.0

def test_match_rate_is_0_when_all_missing():
    primary = [_row()]
    result = compare_rows(primary, [])
    assert result.match_rate == 0.0
```

Run: `.venv/bin/pytest tests/unit/test_parity_comparator.py -v`
Expected: FAIL

- [ ] **Step 2: Create `parity_comparator.py`**

```python
"""ParityComparator — pure comparison logic for parity auditor.

No I/O. Accepts two lists of DB row dicts, returns a ComparisonResult.
Fields compared are the Renaissance-critical columns: all tiered feature
vectors (i1–i6), winner selection, and signal funnel counts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Columns compared — excludes ephemeral fields (computed_at, bar_close_ts)
# that are expected to differ slightly due to clock skew between writers.
# Must align with _COMPARE_COLUMNS in parity_repository.py — "source" is
# included in both so divergences between write paths are detected.
_COMPARE_FIELDS: tuple[str, ...] = (
    "source", "schema_version",
    "winner_plugin", "winner_confidence", "winner_direction",
    "signals_evaluated", "signals_after_quality", "signals_after_regime",
    "signals_after_tod", "signals_after_calibration",
    "ledger_written", "session_type",
)

# JSONB tier fields — compared as dict equality (key presence + values)
_JSONB_FIELDS: tuple[str, ...] = ("i1", "i2", "i3", "i4", "i5", "smc", "i6")


@dataclass
class Violation:
    ts: datetime
    symbol: str
    tf: str
    field: str
    legacy_val: Any
    shadow_val: Any


@dataclass
class ComparisonResult:
    symbol: str
    tf: str
    primary_count: int
    shadow_count: int
    match_count: int
    violation_count: int
    violations: list[Violation] = field(default_factory=list)

    @property
    def match_rate(self) -> float:
        if self.primary_count == 0:
            return 1.0
        return self.match_count / self.primary_count


def build_row_index(rows: list[dict[str, Any]]) -> dict[datetime, dict[str, Any]]:
    """Index rows by ts for O(1) lookup. Last row wins on ts collision."""
    return {row["ts"]: row for row in rows}


def compare_rows(
    primary: list[dict[str, Any]],
    shadow: list[dict[str, Any]],
    *,
    symbol: str = "",
    tf: str = "",
) -> ComparisonResult:
    """Compare primary and shadow rows field-by-field.

    Returns a ComparisonResult with all violations enumerated.
    Uses the ts column as the join key.

    Args:
        primary: Rows from intelligence_features.
        shadow: Rows from feature_snapshots_shadow.
        symbol: Active symbol for this comparison — used in empty-primary result
                and log messages. Pass explicitly from the calling loop context.
        tf: Active timeframe — same as symbol.
    """
    if not primary:
        return ComparisonResult(
            symbol=symbol, tf=tf, primary_count=0, shadow_count=len(shadow),
            match_count=0, violation_count=0,
        )

    # Prefer explicit params; fall back to row content if caller omits them.
    symbol = symbol or primary[0].get("symbol", "")
    tf = tf or primary[0].get("tf", "")
    shadow_index = build_row_index(shadow)

    violations: list[Violation] = []
    match_count = 0

    for p_row in primary:
        ts = p_row["ts"]
        s_row = shadow_index.get(ts)

        if s_row is None:
            violations.append(Violation(
                ts=ts, symbol=symbol, tf=tf,
                field="MISSING_IN_SHADOW", legacy_val=str(ts), shadow_val=None,
            ))
            continue

        row_clean = True
        for col in _COMPARE_FIELDS:
            p_val = p_row.get(col)
            s_val = s_row.get(col)
            if p_val != s_val:
                violations.append(Violation(
                    ts=ts, symbol=symbol, tf=tf,
                    field=col, legacy_val=p_val, shadow_val=s_val,
                ))
                row_clean = False

        for tier in _JSONB_FIELDS:
            p_tier = p_row.get(tier) or {}
            s_tier = s_row.get(tier) or {}
            if p_tier != s_tier:
                violations.append(Violation(
                    ts=ts, symbol=symbol, tf=tf,
                    field=tier,
                    legacy_val=f"keys={sorted(p_tier.keys())}",
                    shadow_val=f"keys={sorted(s_tier.keys())}",
                ))
                row_clean = False

        if row_clean:
            match_count += 1

    return ComparisonResult(
        symbol=symbol, tf=tf,
        primary_count=len(primary), shadow_count=len(shadow),
        match_count=match_count, violation_count=len(violations),
        violations=violations,
    )
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest tests/unit/test_parity_comparator.py -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/persistence/logic/parity_comparator.py tests/unit/test_parity_comparator.py
git commit -m "feat(logic): add ParityComparator pure comparison engine"
```

---

## Task 3: `ParityAuditorAgent` — orchestration + certification

**Files:**
- Create: `services/parity_auditor_agent.py`
- Test: `tests/unit/test_parity_auditor_agent.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_parity_auditor_agent.py
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from services.parity_auditor_agent import (
    ParityAuditorAgent,
    AUDIT_INTERVAL_SECS,
    CERTIFICATION_THRESHOLD,
    LOOKBACK_SECS,
)

def test_audit_interval_is_reasonable():
    assert 60 <= AUDIT_INTERVAL_SECS <= 600, \
        "Audit interval must be 1–10 minutes (Renaissance: automate, don't spam DB)"

def test_certification_threshold_is_meaningful():
    assert CERTIFICATION_THRESHOLD >= 3, \
        "At least 3 consecutive clean cycles required before certification"

def test_lookback_covers_multiple_bars():
    assert LOOKBACK_SECS >= 300, "Lookback must cover at least 5 minutes of bars"

def test_certification_counter_increments_on_clean_cycle():
    agent = ParityAuditorAgent.__new__(ParityAuditorAgent)
    agent._clean_cycles_by_pair = {}
    agent._certified_pairs = set()
    agent.logger = MagicMock()

    from src.persistence.logic.parity_comparator import ComparisonResult
    clean = ComparisonResult(
        symbol="ES", tf="1m",
        primary_count=10, shadow_count=10,
        match_count=10, violation_count=0,
    )
    agent._update_certification("ES", "1m", clean)
    assert agent._clean_cycles_by_pair[("ES", "1m")] == 1

def test_certification_resets_on_violation():
    agent = ParityAuditorAgent.__new__(ParityAuditorAgent)
    agent._clean_cycles_by_pair = {("ES", "1m"): 5}
    agent._certified_pairs = set()
    agent.logger = MagicMock()

    from src.persistence.logic.parity_comparator import ComparisonResult, Violation
    from datetime import UTC, datetime
    dirty = ComparisonResult(
        symbol="ES", tf="1m",
        primary_count=10, shadow_count=10,
        match_count=9, violation_count=1,
        violations=[Violation(
            ts=datetime(2026, 3, 26, 10, 0, tzinfo=UTC),
            symbol="ES", tf="1m",
            field="winner_plugin", legacy_val="Trend", shadow_val="Momentum",
        )],
    )
    agent._update_certification("ES", "1m", dirty)
    assert agent._clean_cycles_by_pair[("ES", "1m")] == 0

def test_pair_certified_after_threshold_consecutive_clean():
    agent = ParityAuditorAgent.__new__(ParityAuditorAgent)
    agent._clean_cycles_by_pair = {("ES", "1m"): CERTIFICATION_THRESHOLD - 1}
    agent._certified_pairs = set()
    agent.logger = MagicMock()

    from src.persistence.logic.parity_comparator import ComparisonResult
    clean = ComparisonResult(
        symbol="ES", tf="1m",
        primary_count=10, shadow_count=10,
        match_count=10, violation_count=0,
    )
    agent._update_certification("ES", "1m", clean)
    assert ("ES", "1m") in agent._certified_pairs
```

Run: `.venv/bin/pytest tests/unit/test_parity_auditor_agent.py -v`
Expected: FAIL

- [ ] **Step 2: Create `services/parity_auditor_agent.py`**

```python
#!/usr/bin/env python3
"""
ParityAuditorAgent — automated shadow parity validation.

Compares intelligence_features (primary writer) against feature_snapshots_shadow
(historian writer) on a timer. Tracks per-(symbol, tf) match rates. Stores
violations in feature_parity_violations. Publishes PARITY_VIOLATION events to
topic_audit(env_name) and SHADOW_PARITY_CERTIFIED to topic_system_events(env_name)
after CERTIFICATION_THRESHOLD consecutive clean cycles per pair.

No manual SQL. No human gate on the happy path.
"""

from __future__ import annotations

import asyncio
import json
import signal
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import structlog

from src.config.settings import Settings, get_active_symbols
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaProducerClient
from src.core.service_utils import setup_service_logging
from src.core.stream_keys import topic_audit, topic_system_events
from src.observability.metrics import counter, gauge, start_metrics_server
from src.persistence.logic.parity_comparator import ComparisonResult, compare_rows
from src.persistence.repository.parity_repository import ParityRepository

# ── Module-level constants ────────────────────────────────────────────────────

AUDIT_INTERVAL_SECS: int = 300          # 5 minutes between cycles
CERTIFICATION_THRESHOLD: int = 5        # consecutive clean cycles to certify a pair
LOOKBACK_SECS: int = 600               # 10-minute comparison window per cycle
METRICS_PORT: int = 9120
ACTIVE_TIMEFRAMES: tuple[str, ...] = ("1m", "5m", "15m", "1h")


class ParityAuditorAgent:
    """Automated parity comparison between primary and shadow feature writers."""

    def __init__(self) -> None:
        self.running = False
        self.shutdown_requested = False

        setup_service_logging("logs/parity_auditor_agent.log")
        self.logger = structlog.get_logger(__name__)

        self._settings = Settings()
        self._env_name = self._settings.env_name.strip()

        # Per-(symbol, tf) certification state
        self._clean_cycles_by_pair: dict[tuple[str, str], int] = {}
        self._certified_pairs: set[tuple[str, str]] = set()

        self._db: DatabaseManager | None = None
        self._repo: ParityRepository | None = None
        self._producer: KafkaProducerClient | None = None

        self._violations_total = counter(
            "parity_violations_total",
            "Total field-level parity violations detected",
        )
        self._audited_pairs = gauge(
            "parity_audited_pairs_total",
            "Number of (symbol, tf) pairs audited this cycle",
        )
        self._certified_count = gauge(
            "parity_certified_pairs_total",
            "Number of (symbol, tf) pairs with certified parity",
        )
        self._match_rate_gauge = gauge(
            "parity_match_rate",
            "Match rate from last audit cycle (global)",
        )

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum: int, frame: Any) -> None:
        self.logger.info("shutdown_signal_received", signal=signum)
        self.shutdown_requested = True

    def _update_certification(
        self, symbol: str, tf: str, result: ComparisonResult
    ) -> None:
        """Update certification counter for a (symbol, tf) pair.

        Increments on clean cycle; resets to 0 on any violation.
        Marks pair as certified after CERTIFICATION_THRESHOLD consecutive cleans.
        """
        key = (symbol, tf)
        if result.violation_count > 0:
            if self._clean_cycles_by_pair.get(key, 0) > 0:
                self.logger.warning(
                    "parity_clean_streak_broken",
                    symbol=symbol, tf=tf,
                    streak_broken_at=self._clean_cycles_by_pair.get(key, 0),
                )
            self._clean_cycles_by_pair[key] = 0
            self._certified_pairs.discard(key)
        else:
            self._clean_cycles_by_pair[key] = self._clean_cycles_by_pair.get(key, 0) + 1
            if self._clean_cycles_by_pair[key] >= CERTIFICATION_THRESHOLD:
                if key not in self._certified_pairs:
                    self._certified_pairs.add(key)
                    self.logger.info(
                        "parity_pair_certified",
                        symbol=symbol, tf=tf,
                        clean_cycles=self._clean_cycles_by_pair[key],
                    )

    async def _publish_violation(
        self, result: ComparisonResult, run_id: uuid.UUID
    ) -> None:
        """Publish PARITY_VIOLATION event to topic_audit(env_name)."""
        if self._producer is None or result.violation_count == 0:
            return
        event = {
            "type": "PARITY_VIOLATION",
            "run_id": str(run_id),
            "ts": datetime.now(UTC).isoformat(),
            "symbol": result.symbol,
            "tf": result.tf,
            "primary_count": result.primary_count,
            "shadow_count": result.shadow_count,
            "match_count": result.match_count,
            "match_rate": round(result.match_rate, 4),
            "violation_count": result.violation_count,
            "fields": list({v.field for v in result.violations}),
        }
        try:
            await self._producer.publish(
                topic_audit(self._env_name),
                {"event": json.dumps(event)},
                key=f"{result.symbol}:{result.tf}",
            )
        except Exception as exc:
            self.logger.error("violation_publish_failed", error=str(exc))

    async def _publish_full_certification(self) -> None:
        """Publish SHADOW_PARITY_CERTIFIED to system.events when all active pairs certified."""
        if self._producer is None:
            return
        active = get_active_symbols(self._settings)
        all_pairs = {(s, tf) for s in active for tf in ACTIVE_TIMEFRAMES}
        if not all_pairs.issubset(self._certified_pairs):
            return  # not all pairs certified yet
        event = {
            "type": "SHADOW_PARITY_CERTIFIED",
            "ts": datetime.now(UTC).isoformat(),
            "certified_pairs": [f"{s}:{tf}" for s, tf in sorted(self._certified_pairs)],
            "certification_threshold": CERTIFICATION_THRESHOLD,
        }
        self.logger.info("shadow_parity_fully_certified", pairs=len(self._certified_pairs))
        try:
            await self._producer.publish(
                topic_system_events(self._env_name),
                {"event": json.dumps(event)},
                key="parity_auditor",
            )
        except Exception as exc:
            self.logger.error("certification_publish_failed", error=str(exc))

    async def _run_cycle(self) -> None:
        """Execute one comparison cycle across all active (symbol, tf) pairs."""
        assert self._repo is not None
        run_id = uuid.uuid4()
        active = get_active_symbols(self._settings)
        total_match = 0
        total_primary = 0

        for symbol in active:
            for tf in ACTIVE_TIMEFRAMES:
                primary = await self._repo.get_primary_rows(symbol, tf, LOOKBACK_SECS)
                shadow = await self._repo.get_shadow_rows(symbol, tf, LOOKBACK_SECS)

                if not primary:
                    continue  # nothing to compare yet

                result = compare_rows(primary, shadow, symbol=symbol, tf=tf)
                total_match += result.match_count
                total_primary += result.primary_count
                self._violations_total.inc(result.violation_count)

                self.logger.info(
                    "parity_cycle_result",
                    symbol=symbol, tf=tf,
                    primary=result.primary_count, shadow=result.shadow_count,
                    match_rate=round(result.match_rate, 4),
                    violations=result.violation_count,
                    run_id=str(run_id),
                )

                # Store violations — never drop (Renaissance: data = training signal)
                for v in result.violations:
                    await self._repo.insert_violation(
                        ts=v.ts, symbol=symbol, tf=tf,
                        field=v.field,
                        legacy_val=str(v.legacy_val) if v.legacy_val is not None else None,
                        shadow_val=str(v.shadow_val) if v.shadow_val is not None else None,
                        run_id=run_id,
                    )

                await self._publish_violation(result, run_id)
                self._update_certification(symbol, tf, result)

        global_rate = total_match / total_primary if total_primary else 1.0
        self._match_rate_gauge.set(global_rate)
        self._audited_pairs.set(len(active) * len(ACTIVE_TIMEFRAMES))
        self._certified_count.set(len(self._certified_pairs))

        self.logger.info(
            "parity_cycle_complete",
            run_id=str(run_id),
            global_match_rate=round(global_rate, 4),
            certified_pairs=len(self._certified_pairs),
        )

        await self._publish_full_certification()

    async def _audit_loop(self) -> None:
        """Run comparison cycles on AUDIT_INTERVAL_SECS schedule."""
        while self.running and not self.shutdown_requested:
            try:
                await self._run_cycle()
            except Exception as exc:
                self.logger.error("audit_cycle_failed", error=str(exc))
            try:
                await asyncio.sleep(AUDIT_INTERVAL_SECS)
            except asyncio.CancelledError:
                break

    async def start(self) -> None:
        self.logger.info("ParityAuditorAgent starting")
        start_metrics_server(port=METRICS_PORT)

        self._db = DatabaseManager(self._settings.database_url)
        await self._db.initialize()
        self._repo = ParityRepository(self._db)

        self._producer = KafkaProducerClient(
            bootstrap_servers=self._settings.kafka_bootstrap_servers
        )
        await self._producer.start()

        self.running = True
        try:
            await self._audit_loop()
        finally:
            await self.stop()

    async def stop(self) -> None:
        self.logger.info("ParityAuditorAgent stopping")
        self.running = False
        self.shutdown_requested = True
        if self._producer:
            await self._producer.stop()
        if self._db:
            await self._db.close()
        self.logger.info("ParityAuditorAgent stopped")


async def main() -> None:
    agent = ParityAuditorAgent()
    await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest tests/unit/test_parity_auditor_agent.py -v
```

Expected: PASS

- [ ] **Step 4: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -q --ignore=tests/unit/service_tests 2>&1 | tail -5
```

Expected: same baseline pass count + new tests.

- [ ] **Step 5: Commit**

```bash
git add services/parity_auditor_agent.py tests/unit/test_parity_auditor_agent.py
git commit -m "feat(service): add ParityAuditorAgent with automated per-pair certification"
```

---

## Task 4: systemd unit

**Files:**
- Create: `production/systemd/indicagent-parity-auditor.service`

- [ ] **Step 1: Create unit**

```ini
[Unit]
Description=IndicAgent Parity Auditor Agent
After=network.target
Wants=network.target

[Service]
Type=simple
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/parity_auditor_agent.py
Restart=on-failure
RestartSec=10
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Install and start**

```bash
sudo cp production/systemd/indicagent-parity-auditor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable indicagent-parity-auditor
sudo systemctl start indicagent-parity-auditor
sudo systemctl status indicagent-parity-auditor
```

- [ ] **Step 3: Verify first audit cycle**

```bash
tail -f logs/parity_auditor_agent.log | grep "parity_cycle_complete"
```

Expected after ~5 minutes:
```
parity_cycle_complete global_match_rate=1.0 certified_pairs=0
```

Match rate = 1.0 from first cycle is the target. `certified_pairs` climbs to full set after `CERTIFICATION_THRESHOLD` cycles.

- [ ] **Step 4: Check for violations**

```bash
docker exec timescaledb psql -U postgres -d indicagent \
  -c "SELECT symbol, tf, field, COUNT(*) FROM feature_parity_violations GROUP BY 1,2,3 ORDER BY 4 DESC;"
```

Expected: 0 rows (clean parity).

- [ ] **Step 5: Commit**

```bash
git add production/systemd/indicagent-parity-auditor.service
git commit -m "feat(ops): add indicagent-parity-auditor systemd unit"
```

---

## Verification Checklist

- [ ] `parity_auditor_agent.py` starts without error
- [ ] First cycle log shows `global_match_rate=1.0`
- [ ] No rows in `feature_parity_violations` after 1 hour
- [ ] After 5 × `AUDIT_INTERVAL_SECS` minutes: `certified_pairs` count = active symbols × 4 timeframes
- [ ] `SHADOW_PARITY_CERTIFIED` event appears on `topic_system_events(env_name)` (e.g. `development.system.events`):
  ```bash
  docker exec redpanda rpk topic consume $(python -c "from src.core.stream_keys import topic_system_events; from src.config.settings import Settings; print(topic_system_events(Settings().env_name))") --from-end | grep SHADOW_PARITY_CERTIFIED
  ```
- [ ] Prometheus metrics visible at `:9120`:
  ```bash
  curl -s localhost:9120/metrics | grep parity_
  ```
- [ ] All unit tests pass

---

## Post-Certification: Primary-Write Cutover

After `SHADOW_PARITY_CERTIFIED` is emitted:

1. Stop `FeatureWriterService`: `sudo systemctl stop indicagent-feature-writer`
2. **Copy committed Kafka offsets** before renaming the consumer group:
   ```bash
   # Record the current committed offset of feature_snapshot_writer_group so the renamed
   # group starts from the same position — not from the beginning of the topic.
   docker exec redpanda rpk group describe feature_snapshot_writer_group
   # Note the committed offset per partition.
   # After renaming to feature_writer_group, set offsets to match:
   # Topic resolves via topic_intelligence_journal(settings.env_name) — default: development.intelligence.journal
   docker exec redpanda rpk group seek feature_writer_group \
     --topic development.intelligence.journal --to <committed_offset>
   ```
   **This step is mandatory.** Skipping it causes the renamed group to replay the
   entire topic history into `intelligence_features`, creating duplicate inserts for
   all historical journal records.
3. Promote `FeatureSnapshotWriterAgent` to write to `intelligence_features`:
   - Change `SHADOW_TABLE = "intelligence_features"` in `feature_snapshot_writer_agent.py`
   - Change `CONSUMER_GROUP = "feature_writer_group"` in `feature_snapshot_writer_agent.py`
4. Restart historian: `sudo systemctl restart indicagent-feature-snapshot-writer`
5. Verify `intelligence_features` continues receiving rows:
   ```bash
   docker exec timescaledb psql -U postgres -d indicagent \
     -c "SELECT COUNT(*) FROM intelligence_features WHERE ts > NOW() - INTERVAL '5 minutes';"
   ```
6. Drop `feature_snapshots_shadow` table: `DROP TABLE feature_snapshots_shadow;`
7. Decommission `FeatureWriterService` and `ParityAuditorAgent` units
