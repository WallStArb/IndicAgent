# Fix B: signal_ledger Split — Immutable Hypertable + signal_outcomes

**Version:** 1.0
**Status:** archived
**Last Updated:** 2026-05-27
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `signal_ledger` into an INSERT-only hypertable (fire-time data, compresses cleanly) and a regular table `signal_outcomes` (lifecycle state, UUID-keyed, purpose-built for updates). Eliminates the structural conflict between TimescaleDB compression and lifecycle UPDATEs that causes recompression to fail on every run.

**Architecture:** Clean-break migration — DROP and recreate schema, no data migration (replay regenerates). A `signal_ledger_full` view joins both tables so existing SELECT consumers change only the table name. All UPDATE SQL moves from `signal_ledger` to `signal_outcomes`. signal_writer INSERTs into both tables atomically.

**Tech Stack:** Python asyncio, asyncpg, TimescaleDB hypertable, pytest + unittest.mock.

---

### Task 1: Write migration SQL

**Files:**
- Create: `production/migrations/095_signal_ledger_split.sql`

- [ ] **Step 1: Create the migration file**

```sql
-- Migration 095: split signal_ledger into immutable hypertable + signal_outcomes
-- CLEAN BREAK: drops and recreates signal_ledger. No data migration needed (replay regenerates).
-- Run ONLY after stopping all L6+ services (signal-writer, lifecycle-writer, signal-tracker,
-- signal-auditor, signal-metrics-compute, graduation-compute, swarm-ledger-writer).

BEGIN;

-- ── Drop existing table and dependent objects ─────────────────────────────────
DROP TABLE IF EXISTS signal_ledger CASCADE;
DROP TABLE IF EXISTS signal_outcomes CASCADE;
DROP VIEW IF EXISTS signal_ledger_full CASCADE;

-- ── signal_ledger: fire-time immutable data ───────────────────────────────────
CREATE TABLE signal_ledger (
    signal_id               uuid            NOT NULL,
    timestamp               timestamptz     NOT NULL,
    symbol                  text            NOT NULL,
    timeframe               text            NOT NULL,
    setup_plugin            text            NOT NULL,
    signal_type             text            NOT NULL,
    direction               integer         NOT NULL,
    was_selected            boolean         NOT NULL DEFAULT false,
    is_shadow               boolean         NOT NULL DEFAULT false,
    is_backfill             boolean         NOT NULL DEFAULT false,
    signal_schema_version   text            NOT NULL,
    signal_computed_at      timestamptz,
    feature_ts              timestamptz,
    feature_tf              text,
    hmm_regime_at_fire      integer,
    garch_sigma_at_fire     double precision,
    ttl_bars                integer,
    entry_price             numeric,
    stop_loss               numeric,
    targets                 jsonb,
    entry_zone_low          numeric,
    entry_zone_high         numeric,
    market_entry_price      double precision,
    cis_score               double precision,
    bucket_scores           jsonb,
    weights_version         integer,
    pipeline_lag_ms         double precision,
    PRIMARY KEY (signal_id, timestamp)
);

SELECT create_hypertable('signal_ledger', 'timestamp', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('signal_ledger', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_retention_policy('signal_ledger', INTERVAL '1 year', if_not_exists => TRUE);

CREATE INDEX idx_signal_ledger_symbol_tf ON signal_ledger (symbol, timeframe, timestamp DESC);
CREATE INDEX idx_signal_ledger_signal_id ON signal_ledger (signal_id);

-- ── signal_outcomes: mutable lifecycle state ──────────────────────────────────
CREATE TABLE signal_outcomes (
    signal_id                       uuid            PRIMARY KEY,
    status                          text            NOT NULL DEFAULT 'pending',
    activated_at                    timestamptz,
    activation_price                double precision,
    zone_entry_pct                  double precision,
    bars_to_activation              integer,
    exit_at                         timestamptz,
    exit_price                      double precision,
    exit_reason                     text,
    pnl_ticks                       double precision,
    pnl_r                           double precision,
    pnl_dollars                     double precision,
    signal_quality                  double precision,
    mae                             double precision,
    mfe                             double precision,
    bars_in_trade                   integer,
    outcome                         text,
    market_entry_at                 timestamptz,
    market_entry_exit_price         double precision,
    market_entry_exit_at            timestamptz,
    market_entry_outcome            text,
    market_entry_pnl_r              double precision,
    market_entry_mae                double precision,
    market_entry_mfe                double precision,
    market_entry_bars_in_trade      integer,
    market_entry_gap_bars           integer,
    trailing_stop_price             jsonb,
    trailing_stop_tightening_rate   double precision,
    staleness_score                 double precision,
    staleness_trigger_reason        text,
    chandelier_vol_source           text,
    shadow_tracking_start_ts        timestamptz,
    shadow_mae                      double precision,
    shadow_mfe                      double precision,
    shadow_outcome                  text,
    effective_ts                    timestamptz
);

CREATE INDEX idx_signal_outcomes_status ON signal_outcomes (status) WHERE exit_at IS NULL;

-- ── signal_ledger_full: read-only join view for all consumers ─────────────────
CREATE VIEW signal_ledger_full AS
SELECT
    sl.signal_id, sl.timestamp, sl.symbol, sl.timeframe,
    sl.setup_plugin, sl.signal_type, sl.direction,
    sl.was_selected, sl.is_shadow, sl.is_backfill,
    sl.signal_schema_version, sl.signal_computed_at,
    sl.feature_ts, sl.feature_tf,
    sl.hmm_regime_at_fire, sl.garch_sigma_at_fire,
    sl.ttl_bars, sl.entry_price, sl.stop_loss, sl.targets,
    sl.entry_zone_low, sl.entry_zone_high,
    sl.market_entry_price, sl.cis_score, sl.bucket_scores,
    sl.weights_version, sl.pipeline_lag_ms,
    -- lifecycle columns from signal_outcomes (NULL until lifecycle events occur)
    so.status, so.activated_at, so.activation_price,
    so.zone_entry_pct, so.bars_to_activation,
    so.exit_at, so.exit_price, so.exit_reason,
    so.pnl_ticks, so.pnl_r, so.pnl_dollars, so.signal_quality,
    so.mae, so.mfe, so.bars_in_trade, so.outcome,
    so.market_entry_at, so.market_entry_exit_price, so.market_entry_exit_at,
    so.market_entry_outcome, so.market_entry_pnl_r, so.market_entry_mae,
    so.market_entry_mfe, so.market_entry_bars_in_trade, so.market_entry_gap_bars,
    so.trailing_stop_price, so.trailing_stop_tightening_rate,
    so.staleness_score, so.staleness_trigger_reason, so.chandelier_vol_source,
    so.shadow_tracking_start_ts, so.shadow_mae, so.shadow_mfe, so.shadow_outcome,
    so.effective_ts
FROM signal_ledger sl
LEFT JOIN signal_outcomes so ON sl.signal_id = so.signal_id;

COMMIT;
```

---

### Task 2: Write failing repository tests

**Files:**
- Modify: `tests/unit/persistence/test_signal_ledger_repository.py`

- [ ] **Step 1: Add failing tests covering new dual-insert and outcomes-targeted updates**

```python
import re
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.persistence.repository.signal_ledger_repository import (
    _INSERT_OUTCOMES_SQL,
    _INSERT_SQL,
    LedgerEntry,
    SignalLedgerRepository,
)


def _make_entry() -> LedgerEntry:
    return LedgerEntry(
        signal_id="00000000-0000-0000-0000-000000000001",
        timestamp=datetime(2026, 5, 24, 10, 0, 0, tzinfo=UTC),
        symbol="ESM6",
        timeframe="5m",
        setup_plugin="breakout_v2",
        signal_type="long",
        direction=1,
        was_selected=True,
        entry_price=5200.0,
        stop_loss=5190.0,
        targets=[5215.0, 5225.0],
        cis_score=0.78,
        bucket_scores={"trend": 0.85},
        weights_version=4,
    )


def test_insert_sql_contains_only_fire_time_columns():
    """_INSERT_SQL must NOT reference lifecycle columns (status, activated_at, exit_at, etc.)."""
    lifecycle_cols = {"status", "activated_at", "exit_at", "pnl_r", "outcome",
                      "mae", "mfe", "signal_quality", "staleness_score"}
    for col in lifecycle_cols:
        assert col not in _INSERT_SQL, f"lifecycle column '{col}' must not appear in _INSERT_SQL"


def test_insert_outcomes_sql_exists_and_has_signal_id():
    """_INSERT_OUTCOMES_SQL must exist and insert into signal_outcomes with signal_id."""
    assert "signal_outcomes" in _INSERT_OUTCOMES_SQL
    assert "signal_id" in _INSERT_OUTCOMES_SQL


def test_to_row_length_matches_insert_sql():
    """_to_row() param count must match $N placeholders in _INSERT_SQL."""
    entry = _make_entry()
    sql_param_count = len(re.findall(r"\$\d+", _INSERT_SQL))
    assert len(entry._to_row()) == sql_param_count


def test_update_methods_target_signal_outcomes():
    """All UPDATE SQL constants must reference signal_outcomes, not signal_ledger."""
    from src.persistence.repository import signal_ledger_repository as repo_mod
    import inspect
    src = inspect.getsource(repo_mod)
    # Find all UPDATE statements
    import re as _re
    updates = _re.findall(r"UPDATE\s+(\w+)", src)
    bad = [t for t in updates if t == "signal_ledger"]
    assert bad == [], f"Found UPDATE signal_ledger — must be UPDATE signal_outcomes: {bad}"


async def test_insert_writes_to_both_tables():
    """insert() must execute two INSERTs: one to signal_ledger, one to signal_outcomes."""
    repo = SignalLedgerRepository.__new__(SignalLedgerRepository)
    mock_db = MagicMock()
    calls = []

    async def fake_execute_batch(sql, params):
        calls.append(sql)

    mock_db.execute_batch = fake_execute_batch
    repo._db_manager = mock_db

    entry = _make_entry()
    await repo.insert([entry])

    assert len(calls) == 2
    assert any("signal_ledger" in c and "INSERT" in c for c in calls)
    assert any("signal_outcomes" in c for c in calls)
```

- [ ] **Step 2: Run to confirm failures**

```bash
.venv/bin/pytest tests/unit/persistence/test_signal_ledger_repository.py -v
```

Expected: `test_insert_sql_contains_only_fire_time_columns`, `test_insert_outcomes_sql_exists_and_has_signal_id`, `test_update_methods_target_signal_outcomes`, `test_insert_writes_to_both_tables` all FAIL.

---

### Task 3: Rewrite `LedgerEntry` dataclass — fire-time columns only

**Files:**
- Modify: `src/persistence/repository/signal_ledger_repository.py`

- [ ] **Step 1: Replace LedgerEntry with fire-time-only dataclass**

Replace the entire `LedgerEntry` class (lines ~55–188) with:

```python
@dataclass
class LedgerEntry:
    """Fire-time signal record — set at emission, never updated.

    All mutable lifecycle state lives in signal_outcomes (see SignalLedgerRepository).
    """
    signal_id: str
    timestamp: datetime
    symbol: str
    timeframe: str
    setup_plugin: str
    signal_type: str
    direction: int
    was_selected: bool
    is_shadow: bool = False
    is_backfill: bool = False
    signal_schema_version: str = SIGNAL_SCHEMA_VERSION
    signal_computed_at: datetime | None = None
    feature_ts: datetime | None = None
    feature_tf: str | None = None
    hmm_regime_at_fire: int | None = None
    garch_sigma_at_fire: float | None = None
    ttl_bars: int | None = None
    entry_price: float | None = None
    stop_loss: float | None = None
    targets: list[float] | None = None
    entry_zone_low: float | None = None
    entry_zone_high: float | None = None
    market_entry_price: float | None = None
    cis_score: float | None = None
    bucket_scores: dict | None = None
    weights_version: int | None = None
    pipeline_lag_ms: float | None = None

    def _to_row(self) -> tuple:
        return (
            self.signal_id,             # $1
            self.timestamp,             # $2
            self.symbol,                # $3
            self.timeframe,             # $4
            self.setup_plugin,          # $5
            self.signal_type,           # $6
            self.direction,             # $7
            self.was_selected,          # $8
            self.is_shadow,             # $9
            self.is_backfill,           # $10
            self.signal_schema_version, # $11
            self.signal_computed_at,    # $12
            self.feature_ts,            # $13
            self.feature_tf,            # $14
            self.hmm_regime_at_fire,    # $15
            self.garch_sigma_at_fire,   # $16
            self.ttl_bars,              # $17
            self.entry_price,           # $18
            self.stop_loss,             # $19
            json.dumps(self.targets) if self.targets is not None else None,  # $20
            self.entry_zone_low,        # $21
            self.entry_zone_high,       # $22
            self.market_entry_price,    # $23
            self.cis_score,             # $24
            self.bucket_scores,         # $25 dict → asyncpg JSONB
            self.weights_version,       # $26
            self.pipeline_lag_ms,       # $27
        )
```

Note: add `import json` at top of file if not already present.

---

### Task 4: Rewrite INSERT SQL constants and add `_INSERT_OUTCOMES_SQL`

**Files:**
- Modify: `src/persistence/repository/signal_ledger_repository.py`

- [ ] **Step 1: Replace `_INSERT_SQL` with fire-time-only INSERT**

```python
_INSERT_SQL = """
INSERT INTO signal_ledger (
    signal_id, timestamp, symbol, timeframe,
    setup_plugin, signal_type, direction,
    was_selected, is_shadow, is_backfill,
    signal_schema_version, signal_computed_at,
    feature_ts, feature_tf,
    hmm_regime_at_fire, garch_sigma_at_fire,
    ttl_bars,
    entry_price, stop_loss, targets, entry_zone_low, entry_zone_high,
    market_entry_price,
    cis_score, bucket_scores, weights_version,
    pipeline_lag_ms
) VALUES (
    $1::uuid, $2, $3, $4,
    $5, $6, $7,
    $8, $9, $10,
    $11, $12,
    $13, $14,
    $15, $16,
    $17,
    $18, $19, $20::jsonb, $21, $22,
    $23,
    $24, $25::jsonb, $26,
    $27
)
ON CONFLICT (signal_id, timestamp) DO NOTHING
"""

_INSERT_OUTCOMES_SQL = """
INSERT INTO signal_outcomes (signal_id, status)
VALUES ($1::uuid, 'pending')
ON CONFLICT (signal_id) DO NOTHING
"""
```

---

### Task 5: Rewrite all UPDATE SQL to target `signal_outcomes`

**Files:**
- Modify: `src/persistence/repository/signal_ledger_repository.py`

- [ ] **Step 1: Replace every `UPDATE signal_ledger` with `UPDATE signal_outcomes`**

There are ~10 UPDATE statements. Do a targeted find-and-replace:

```bash
grep -n "UPDATE signal_ledger" src/persistence/repository/signal_ledger_repository.py
```

For each UPDATE statement found, change `UPDATE signal_ledger` → `UPDATE signal_outcomes`. The WHERE clause (`WHERE signal_id = $1::uuid`) remains identical — signal_outcomes has signal_id as its PK.

Example — `_UPDATE_STATUS_SQL` becomes:
```python
_UPDATE_STATUS_SQL = """
UPDATE signal_outcomes
SET status = $2,
    activated_at = $3,
    exit_at = $4,
    exit_price = $5,
    exit_reason = $6,
    pnl_ticks = $7,
    pnl_r = $8,
    pnl_dollars = $9,
    signal_quality = $10,
    activation_price = $11,
    zone_entry_pct = $12,
    bars_to_activation = $13,
    mae = $14,
    mfe = $15,
    bars_in_trade = $16,
    outcome = $17
WHERE signal_id = $1::uuid
"""
```

Apply the same `UPDATE signal_outcomes` change to: `_RECORD_ACTIVATION_SQL`, `_RECORD_ZONE_RESOLUTION_SQL`, `_RECORD_MARKET_RESOLUTION_SQL`, `_BATCH_ACTIVATION_SQL`, `_BATCH_EXIT_SQL`, `_RECORD_ZONE_WITH_ACTIVATION_SQL`, and all inline UPDATE strings in `update_chandelier_state`, `update_chandelier_vol_source`, `update_shadow_outcome`, `set_shadow_tracking_start`, `update_mae_mfe`.

---

### Task 6: Update `insert()` method — dual INSERT in one transaction

**Files:**
- Modify: `src/persistence/repository/signal_ledger_repository.py`

- [ ] **Step 1: Rewrite the `insert()` method to write both tables**

Find the `insert()` method (around line 465) and replace its body:

```python
    async def insert(self, entries: list[LedgerEntry]) -> None:
        """Insert fire-time records into signal_ledger and seed signal_outcomes rows."""
        if not entries:
            return
        ledger_params = [e._to_row() for e in entries]
        outcomes_params = [(e.signal_id,) for e in entries]
        await self._db_manager.execute_batch(_INSERT_SQL, ledger_params)
        await self._db_manager.execute_batch(_INSERT_OUTCOMES_SQL, outcomes_params)
```

---

### Task 7: Update SELECT queries to use `signal_ledger_full`

**Files:**
- Modify: `src/persistence/repository/signal_ledger_repository.py`

- [ ] **Step 1: Replace `FROM signal_ledger` with `FROM signal_ledger_full` in all SELECT queries**

The SELECTs are in: `_SELECT_ACTIVE_SQL`, `_SELECT_ACTIVE_BY_SYMBOL_SQL`, `fetch_active_signals`, `fetch_pending_signals`, and any other `SELECT ... FROM signal_ledger` that reads lifecycle columns.

```bash
grep -n "FROM signal_ledger" src/persistence/repository/signal_ledger_repository.py
```

Change each `FROM signal_ledger` → `FROM signal_ledger_full` for queries that need lifecycle columns (status, exit_at, activated_at, outcome, etc.).

The swarm_ledger existence check (`SELECT 1 FROM signal_ledger WHERE signal_id = $1`) stays on `signal_ledger` — it is checking the fire-time row exists, not reading lifecycle data.

---

### Task 8: Update the 11 consumer services — view swap

**Files:**
- Modify: `services/signal_tracker_compute_agent.py`
- Modify: `services/signal_auditor_agent.py`
- Modify: `services/shadow_auditor_agent.py`
- Modify: `services/signal_metrics_compute_agent.py`
- Modify: `services/graduation_compute_agent.py`
- Modify: `services/alpha_swarm_agent.py`
- Modify: `services/ml_discovery_agent.py`
- Modify: `services/ml_data_quality_agent.py`
- Modify: `services/signal_replay_auditor_agent.py`
- Modify: `src/api/routes/signals.py`
- Modify: `src/api/routes/narrative.py`

- [ ] **Step 1: In each file, replace `FROM signal_ledger` → `FROM signal_ledger_full` for any query reading lifecycle columns**

Run this to find all affected lines:
```bash
grep -n "FROM signal_ledger" services/signal_tracker_compute_agent.py services/signal_auditor_agent.py services/shadow_auditor_agent.py services/signal_metrics_compute_agent.py services/graduation_compute_agent.py services/alpha_swarm_agent.py services/ml_discovery_agent.py services/ml_data_quality_agent.py services/signal_replay_auditor_agent.py src/api/routes/signals.py src/api/routes/narrative.py
```

For each match: change `FROM signal_ledger` → `FROM signal_ledger_full`. Also change `JOIN signal_ledger` → `JOIN signal_ledger_full` where the JOIN pulls lifecycle columns.

**Exception:** `services/swarm_ledger_writer_agent.py` line ~214: `SELECT 1 FROM signal_ledger WHERE signal_id = $1` — keep as `signal_ledger` (checking fire-time existence only).

- [ ] **Step 2: `ml_data_quality_agent.py` — outcome coverage query needs special treatment**

The query at line ~124 queries `FROM signal_ledger` for outcome coverage. Change to `FROM signal_ledger_full` so it can see the `outcome` column from signal_outcomes:

```python
# Before
FROM signal_ledger
# After
FROM signal_ledger_full
```

---

### Task 9: Update replay scripts

**Files:**
- Modify: `production/scripts/lifecycle_replay.py`
- Modify: `production/scripts/compute_ic.py`
- Modify: `production/scripts/check_validate_alpha_eligibility.py`

- [ ] **Step 1: Run grep to find all direct signal_ledger references in scripts**

```bash
grep -n "signal_ledger" production/scripts/lifecycle_replay.py production/scripts/compute_ic.py production/scripts/check_validate_alpha_eligibility.py
```

- [ ] **Step 2: In `lifecycle_replay.py` — update any UPDATE SQL to target `signal_outcomes`**

Any `UPDATE signal_ledger SET ...` in the replay script must change to `UPDATE signal_outcomes SET ...`. The WHERE clause stays identical.

- [ ] **Step 3: In `compute_ic.py` and `check_validate_alpha_eligibility.py` — view swap**

Any `FROM signal_ledger` that reads lifecycle columns (outcome, pnl_r, status, etc.) → `FROM signal_ledger_full`.

---

### Task 10: Run tests

- [ ] **Step 1: Run repository tests**

```bash
.venv/bin/pytest tests/unit/persistence/test_signal_ledger_repository.py -v
```

Expected: all PASSED

- [ ] **Step 2: Run full services test suite**

```bash
.venv/bin/pytest tests/unit/services/ -q
```

Expected: pre-existing failures only — none introduced by this change. Any new failures indicate a missed `FROM signal_ledger` → `FROM signal_ledger_full` substitution or a test fixture still constructing a LedgerEntry with lifecycle fields.

- [ ] **Step 3: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: same pre-existing failure set as before this change.

---

### Task 11: Apply migration and verify

- [ ] **Step 1: Stop all L6+ services**

```bash
sudo systemctl stop indicagent-signal-writer indicagent-lifecycle-writer indicagent-signal-tracker-compute indicagent-signal-auditor indicagent-signal-metrics-compute indicagent-graduation-compute indicagent-swarm-ledger-writer indicagent-alpha-swarm
```

- [ ] **Step 2: Apply migration**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/095_signal_ledger_split.sql
```

Expected: no errors. `CREATE TABLE`, `CREATE INDEX`, `CREATE VIEW` output.

- [ ] **Step 3: Verify schema**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "\d signal_ledger" -c "\d signal_outcomes" -c "\d signal_ledger_full"
```

Expected: signal_ledger has 27 columns (fire-time only), signal_outcomes has 36 columns, signal_ledger_full view visible.

- [ ] **Step 4: Verify compression policy**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT j.application_name, j.config, js.last_run_status
FROM timescaledb_information.jobs j
LEFT JOIN timescaledb_information.job_stats js ON j.job_id = js.job_id
WHERE j.proc_name = 'policy_compression'
  AND (j.config->>'hypertable_id')::int = (SELECT id FROM _timescaledb_catalog.hypertable WHERE table_name = 'signal_ledger');"
```

Expected: compression policy present.

- [ ] **Step 5: Restart services**

```bash
sudo systemctl start indicagent-signal-writer indicagent-lifecycle-writer indicagent-signal-tracker-compute indicagent-signal-auditor indicagent-signal-metrics-compute indicagent-graduation-compute indicagent-swarm-ledger-writer indicagent-alpha-swarm
```

- [ ] **Step 6: Verify signal_writer is inserting to both tables**

Wait 2 minutes for signals to emit, then:

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT COUNT(*) as ledger_rows FROM signal_ledger;
SELECT COUNT(*) as outcomes_rows FROM signal_outcomes;
SELECT COUNT(*) as full_rows FROM signal_ledger_full;"
```

Expected: ledger_rows == outcomes_rows == full_rows (every signal has a corresponding outcomes row).

---

### Task 12: Commit

- [ ] **Step 1: Stage and commit**

```bash
git add production/migrations/095_signal_ledger_split.sql \
        src/persistence/repository/signal_ledger_repository.py \
        services/signal_writer_agent.py \
        services/lifecycle_writer_agent.py \
        services/signal_tracker_compute_agent.py \
        services/signal_auditor_agent.py \
        services/shadow_auditor_agent.py \
        services/signal_metrics_compute_agent.py \
        services/graduation_compute_agent.py \
        services/alpha_swarm_agent.py \
        services/ml_discovery_agent.py \
        services/ml_data_quality_agent.py \
        services/signal_replay_auditor_agent.py \
        src/api/routes/signals.py \
        src/api/routes/narrative.py \
        production/scripts/lifecycle_replay.py \
        production/scripts/compute_ic.py \
        production/scripts/check_validate_alpha_eligibility.py \
        tests/unit/persistence/test_signal_ledger_repository.py

git commit -m "$(cat <<'EOF'
feat(storage): split signal_ledger into immutable hypertable + signal_outcomes

Separates fire-time data (INSERT-only, 27 cols) from lifecycle state (mutable,
signal_outcomes regular table, 36 cols). Eliminates the structural conflict
between TimescaleDB compression and lifecycle UPDATEs that caused 59/198
recompression failures and left a 23 GB chunk permanently bloated.

signal_ledger_full view provides backward-compatible SELECT access.
All UPDATE SQL retargeted to signal_outcomes. Dual INSERT in repository.insert().
Clean-break migration — replay regenerates historical data.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```
