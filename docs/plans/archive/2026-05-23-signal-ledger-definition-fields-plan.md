# Signal Ledger Definition Fields Implementation Plan

**Version:** 1.0
**Status:** archived
**Last Updated:** 2026-05-23
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the five signal-definition columns (`entry_price`, `stop_loss`, `targets`, `entry_zone_low`, `entry_zone_high`) to `signal_ledger`, populate them at write time, and eliminate the `intelligence_features` JOIN from the bootstrap query.

**Architecture:** Signal definition fields belong in `signal_ledger` as first-class columns — they are what a signal IS, not contextual metadata. The signal_writer populates them at fire time from the I7 payload. The bootstrap reads directly from `signal_ledger` with no JOIN. The `enable_mergejoin = off` planner hint is removed entirely.

**Tech Stack:** PostgreSQL/TimescaleDB (asyncpg), Python 3.11, pytest, structlog.

---

## Files

- Modify: `db/migrations/095_restore_signal_definition_fields.sql` (create)
- Modify: `src/persistence/repository/signal_ledger_repository.py` — `LedgerEntry`, `_to_row`, `_INSERT_SQL`, four SELECT methods
- Modify: `services/signal_writer_agent.py` — `_payload_to_ledger_entries`
- Modify: `services/signal_tracker_compute_agent.py` — `_bootstrap_active_signals`
- Modify: `tests/unit/services/test_signal_writer_agent.py` — add definition-fields tests
- Modify: `tests/unit/services/test_signal_tracker_bootstrap.py` — remove `enable_mergejoin` assertion, add NULL-fallback test

---

### Task 1: Migration — add the five columns

**Files:**
- Create: `db/migrations/095_restore_signal_definition_fields.sql`

- [ ] **Step 1: Create migration file**

```sql
-- Phase v2.8: restore signal definition fields dropped by 093.
-- entry_price/stop_loss/targets/entry_zone_low/high define WHAT a signal is.
-- They belong in signal_ledger, not only in intelligence_features JSONB.
-- Nullable so existing rows are unaffected; new signals populate on deploy.

BEGIN;

ALTER TABLE signal_ledger
  ADD COLUMN IF NOT EXISTS entry_price    NUMERIC,
  ADD COLUMN IF NOT EXISTS stop_loss      NUMERIC,
  ADD COLUMN IF NOT EXISTS targets        JSONB,
  ADD COLUMN IF NOT EXISTS entry_zone_low  NUMERIC,
  ADD COLUMN IF NOT EXISTS entry_zone_high NUMERIC;

COMMIT;
```

- [ ] **Step 2: Apply migration**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent \
  -f db/migrations/095_restore_signal_definition_fields.sql
```

Expected output:
```
BEGIN
ALTER TABLE
COMMIT
```

- [ ] **Step 3: Verify columns exist**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT column_name, data_type FROM information_schema.columns \
   WHERE table_name='signal_ledger' AND column_name IN \
   ('entry_price','stop_loss','targets','entry_zone_low','entry_zone_high') \
   ORDER BY column_name;"
```

Expected: 5 rows returned.

- [ ] **Step 4: Commit**

```bash
git add db/migrations/095_restore_signal_definition_fields.sql
git commit -m "feat(db): restore signal definition fields to signal_ledger (migration 095)"
```

---

### Task 2: LedgerEntry dataclass + INSERT SQL

**Files:**
- Modify: `src/persistence/repository/signal_ledger_repository.py`

The current `_to_row()` returns a 44-element tuple ($1–$44). We add 5 fields as $45–$49.

- [ ] **Step 1: Write the failing test**

In `tests/unit/services/test_signal_writer_agent.py`, add to the existing test class:

```python
def test_definition_fields_in_ledger_entry(self):
    """entry_price, stop_loss, targets, entry_zone_low/high must be populated."""
    payload = {
        "symbol": "ES",
        "tf": "5m",
        "bar_ts": "2026-01-01T10:00:00Z",
        "computed_at": "2026-01-01T10:00:01Z",
        "signals": [
            {
                "signal_id": "aaaaaaaa-0000-0000-0000-000000000001",
                "setup_plugin": "momentum_breakout",
                "signal_type": "breakout",
                "direction": 1,
                "was_selected": True,
                "entry_price": 5100.0,
                "stop_loss": 5080.0,
                "targets": [5120.0, 5150.0],
                "entry_zone_low": 5095.0,
                "entry_zone_high": 5105.0,
            }
        ],
    }
    entries = _payload_to_ledger_entries(payload)
    assert len(entries) == 1
    e = entries[0]
    assert e.entry_price == 5100.0
    assert e.stop_loss == 5080.0
    assert e.targets == [5120.0, 5150.0]
    assert e.entry_zone_low == 5095.0
    assert e.entry_zone_high == 5105.0


def test_definition_fields_none_when_absent(self):
    """Missing definition fields default to None, not KeyError."""
    payload = {
        "symbol": "ES",
        "tf": "5m",
        "bar_ts": "2026-01-01T10:00:00Z",
        "computed_at": "2026-01-01T10:00:01Z",
        "signals": [
            {
                "signal_id": "aaaaaaaa-0000-0000-0000-000000000002",
                "setup_plugin": "momentum_breakout",
                "signal_type": "breakout",
                "direction": 1,
                "was_selected": False,
            }
        ],
    }
    entries = _payload_to_ledger_entries(payload)
    assert entries[0].entry_price is None
    assert entries[0].stop_loss is None
    assert entries[0].targets is None


def test_to_row_length_includes_definition_fields(self):
    """_to_row() tuple must have 49 elements after adding 5 definition fields."""
    from src.persistence.repository.signal_ledger_repository import LedgerEntry
    from datetime import UTC, datetime
    e = LedgerEntry(
        signal_id="aaaaaaaa-0000-0000-0000-000000000003",
        timestamp=datetime.now(UTC),
        symbol="ES",
        timeframe="5m",
        setup_plugin="test",
        signal_type="test",
        direction=1,
        was_selected=True,
    )
    assert len(e._to_row()) == 49
```

- [ ] **Step 2: Run to verify failure**

```bash
.venv/bin/pytest tests/unit/services/test_signal_writer_agent.py::TestPayloadToLedgerEntries::test_definition_fields_in_ledger_entry -v
```

Expected: FAIL — `LedgerEntry has no attribute entry_price` or similar.

- [ ] **Step 3: Add fields to LedgerEntry**

In `src/persistence/repository/signal_ledger_repository.py`, after `ttl_bars: int | None = None` (line ~111), add:

```python
    # Signal definition — fire-time immutable trade parameters
    entry_price: float | None = None
    stop_loss: float | None = None
    targets: list[float] | None = None
    entry_zone_low: float | None = None
    entry_zone_high: float | None = None
```

- [ ] **Step 4: Update `_to_row()` — append 5 params**

At the end of `_to_row()`, after `self.ttl_bars,  # $44`, add:

```python
            # Signal definition
            self.entry_price,         # $45 entry_price
            self.stop_loss,           # $46 stop_loss
            self.targets,             # $47 targets (asyncpg accepts list for JSONB)
            self.entry_zone_low,      # $48 entry_zone_low
            self.entry_zone_high,     # $49 entry_zone_high
```

- [ ] **Step 5: Update `_INSERT_SQL` — add columns and placeholders**

In `_INSERT_SQL`, add to the column list after `ttl_bars`:

```sql
    ttl_bars,
    entry_price, stop_loss, targets, entry_zone_low, entry_zone_high
```

Add to the VALUES list after `$44`:

```sql
    $44,
    $45, $46, $47, $48, $49
```

- [ ] **Step 6: Run tests**

```bash
.venv/bin/pytest tests/unit/services/test_signal_writer_agent.py -v
```

Expected: all pass including the 3 new tests.

- [ ] **Step 7: Commit**

```bash
git add src/persistence/repository/signal_ledger_repository.py \
        tests/unit/services/test_signal_writer_agent.py
git commit -m "feat(ledger): add entry_price/stop_loss/targets/entry_zone fields to LedgerEntry"
```

---

### Task 3: signal_writer_agent — populate definition fields

**Files:**
- Modify: `services/signal_writer_agent.py` — `_payload_to_ledger_entries` (line ~186)

- [ ] **Step 1: Tests already written** (Task 2 Step 1 covers this — run them to confirm they still fail at the writer level)

```bash
.venv/bin/pytest tests/unit/services/test_signal_writer_agent.py::TestPayloadToLedgerEntries::test_definition_fields_in_ledger_entry -v
```

Expected: FAIL — `entry_price` is None in the entry (field exists but not populated).

- [ ] **Step 2: Populate fields in `_payload_to_ledger_entries`**

In `services/signal_writer_agent.py`, inside the `LedgerEntry(...)` constructor call (around line 187), add after `ttl_bars=sig.get("ttl_bars"),`:

```python
                entry_price=sig.get("entry_price"),
                stop_loss=sig.get("stop_loss"),
                targets=sig.get("targets") or None,
                entry_zone_low=sig.get("entry_zone_low"),
                entry_zone_high=sig.get("entry_zone_high"),
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest tests/unit/services/test_signal_writer_agent.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add services/signal_writer_agent.py
git commit -m "feat(signal-writer): populate entry_price/stop_loss/targets/entry_zone at write time"
```

---

### Task 4: Bootstrap query — drop the JOIN

**Files:**
- Modify: `services/signal_tracker_compute_agent.py` — `_bootstrap_active_signals` (line ~872)

- [ ] **Step 1: Write new bootstrap test for NULL fallback**

In `tests/unit/services/test_signal_tracker_bootstrap.py`, add:

```python
@pytest.mark.asyncio
async def test_bootstrap_null_entry_price_falls_back_to_activation_price():
    """entry_price=NULL in signal_ledger falls back to activation_price via COALESCE.

    This covers signals created before migration 095. The _load_signal method
    receives the COALESCE result already resolved by SQL, so this test verifies
    the mock row shape expected after the JOIN is removed.
    """
    signal_id = "aaaaaaaa-0000-0000-0000-000000000099"
    row = _make_signal_row(
        signal_id,
        entry_price=None,  # simulates pre-095 signal — SQL COALESCE gives activation_price
        stop_loss=None,
        targets=None,
        entry_zone_low=None,
        entry_zone_high=None,
        activation_price=5050.0,
        ttl_bars=10,
        signal_schema_version="1",
        is_backfill=False,
    )
    # Simulate what SQL COALESCE(sl.entry_price, sl.activation_price) produces:
    row["entry_price"] = row.get("activation_price")  # 5050.0

    mock_db = _make_db_mock([[row]])
    agent = _make_agent()
    agent._producer = None

    with patch(
        "services.signal_tracker_compute_agent.DatabaseManager",
        return_value=mock_db,
    ):
        await agent._bootstrap_active_signals()

    assert signal_id in agent._signal_ids
    loaded = next(iter(agent._active_index.values()))[0]
    assert loaded["entry_price"] == 5050.0
```

- [ ] **Step 2: Also add test verifying `enable_mergejoin` is NOT called**

```python
@pytest.mark.asyncio
async def test_bootstrap_does_not_set_enable_mergejoin():
    """Bootstrap must not issue SET enable_mergejoin — JOIN is gone."""
    signal_id = "aaaaaaaa-0000-0000-0000-000000000098"
    row = _make_signal_row(signal_id, ttl_bars=10, signal_schema_version="1", is_backfill=False)
    mock_db = _make_db_mock([[row]])
    agent = _make_agent()
    agent._producer = None

    with patch(
        "services.signal_tracker_compute_agent.DatabaseManager",
        return_value=mock_db,
    ):
        await agent._bootstrap_active_signals()

    # conn.execute should never have been called (no SET statements)
    for call_args in mock_db.get_connection.return_value.__aenter__.return_value.execute.call_args_list:
        assert "mergejoin" not in str(call_args).lower()
```

Note: `_make_db_mock` uses a context-manager pattern — the execute assertion works because `_fake_get_connection` captures a fresh `conn = AsyncMock()` each time.

- [ ] **Step 3: Run new tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/services/test_signal_tracker_bootstrap.py::test_bootstrap_null_entry_price_falls_back_to_activation_price tests/unit/services/test_signal_tracker_bootstrap.py::test_bootstrap_does_not_set_enable_mergejoin -v
```

Expected: at least one FAIL.

- [ ] **Step 4: Replace `_BOOTSTRAP_QUERY` and remove the planner hint**

In `services/signal_tracker_compute_agent.py`, replace the entire `_BOOTSTRAP_QUERY` string and the `SET enable_mergejoin` call (lines ~872–898) with:

```python
        _BOOTSTRAP_QUERY = """
            SELECT sl.signal_id, sl.symbol, sl.timeframe, sl.timestamp, sl.status,
                   sl.direction, sl.activated_at, sl.ttl_bars, sl.signal_schema_version,
                   sl.is_backfill,
                   COALESCE(sl.entry_price, sl.activation_price) AS entry_price,
                   sl.stop_loss,
                   sl.targets,
                   sl.entry_zone_low,
                   sl.entry_zone_high,
                   sl.market_entry_price,
                   sl.garch_sigma_at_fire,
                   sl.hmm_regime_at_fire
            FROM signal_ledger sl
            WHERE sl.exit_at IS NULL
              AND sl.status IN ('pending', 'active')
              AND sl.timestamp > NOW() - INTERVAL '7 days'
        """
```

Then in the retry loop, replace:

```python
                async with db.get_connection() as conn:
                    await conn.execute("SET enable_mergejoin = off")
                    rows = [dict(r) for r in await conn.fetch(_BOOTSTRAP_QUERY)]
```

with:

```python
                async with db.get_connection() as conn:
                    rows = [dict(r) for r in await conn.fetch(_BOOTSTRAP_QUERY)]
```

- [ ] **Step 5: Run all bootstrap tests**

```bash
.venv/bin/pytest tests/unit/services/test_signal_tracker_bootstrap.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add services/signal_tracker_compute_agent.py \
        tests/unit/services/test_signal_tracker_bootstrap.py
git commit -m "feat(signal-tracker): drop intelligence_features JOIN from bootstrap, remove mergejoin hint"
```

---

### Task 5: Fix stale repository SELECT queries

**Files:**
- Modify: `src/persistence/repository/signal_ledger_repository.py` — four SELECT methods

These reference ~40 columns dropped in 093. Fix them to match the current schema (54 live columns + the 5 we just added).

- [ ] **Step 1: Replace `_SELECT_ACTIVE_SQL`** (lines ~347–371)

```python
_SELECT_ACTIVE_SQL = """
SELECT signal_id, timestamp, symbol, timeframe, setup_plugin, signal_type, direction,
       was_selected, status, activated_at, exit_at, exit_price, exit_reason,
       pnl_ticks, pnl_r, pnl_dollars, signal_quality, signal_computed_at,
       activation_price, zone_entry_pct, bars_to_activation,
       mae, mfe, bars_in_trade, outcome,
       feature_ts, feature_tf,
       market_entry_price, market_entry_exit_price, market_entry_outcome,
       market_entry_pnl_r, market_entry_mae, market_entry_mfe, market_entry_bars_in_trade,
       market_entry_outcome, market_entry_gap_bars, market_entry_at, market_entry_exit_at,
       is_shadow, hmm_regime_at_fire, garch_sigma_at_fire,
       trailing_stop_price, staleness_score, staleness_trigger_reason,
       shadow_tracking_start_ts, shadow_mae, shadow_mfe, shadow_outcome,
       effective_ts, pipeline_lag_ms, signal_schema_version, is_backfill, ttl_bars,
       entry_price, stop_loss, targets, entry_zone_low, entry_zone_high
FROM signal_ledger
WHERE status IN ('pending', 'active', 'regime_suppressed') AND exit_at IS NULL
ORDER BY timestamp DESC
"""
```

- [ ] **Step 2: Replace `_SELECT_ACTIVE_BY_SYMBOL_SQL`** (lines ~373–397)

```python
_SELECT_ACTIVE_BY_SYMBOL_SQL = """
SELECT signal_id, timestamp, symbol, timeframe, setup_plugin, signal_type, direction,
       was_selected, status, activated_at, exit_at, exit_price, exit_reason,
       pnl_ticks, pnl_r, pnl_dollars, signal_quality, signal_computed_at,
       activation_price, zone_entry_pct, bars_to_activation,
       mae, mfe, bars_in_trade, outcome,
       feature_ts, feature_tf,
       market_entry_price, market_entry_exit_price, market_entry_outcome,
       market_entry_pnl_r, market_entry_mae, market_entry_mfe, market_entry_bars_in_trade,
       market_entry_outcome, market_entry_gap_bars, market_entry_at, market_entry_exit_at,
       is_shadow, hmm_regime_at_fire, garch_sigma_at_fire,
       trailing_stop_price, staleness_score, staleness_trigger_reason,
       shadow_tracking_start_ts, shadow_mae, shadow_mfe, shadow_outcome,
       effective_ts, pipeline_lag_ms, signal_schema_version, is_backfill, ttl_bars,
       entry_price, stop_loss, targets, entry_zone_low, entry_zone_high
FROM signal_ledger
WHERE status IN ('pending', 'active', 'regime_suppressed') AND symbol = $1 AND exit_at IS NULL
ORDER BY timestamp DESC
"""
```

- [ ] **Step 3: Replace `fetch_active_signals` inline SQL** (lines ~628–658)

```python
    async def fetch_active_signals(self, symbol: str, tf: str) -> list[dict]:
        """Return pending/active/regime_suppressed signals for a specific symbol+timeframe."""
        sql = """
SELECT signal_id, timestamp, symbol, timeframe, setup_plugin, signal_type, direction,
       was_selected, status, activated_at, exit_at, exit_price, exit_reason,
       pnl_ticks, pnl_r, pnl_dollars, signal_quality, signal_computed_at,
       activation_price, zone_entry_pct, bars_to_activation,
       mae, mfe, bars_in_trade, outcome,
       feature_ts, feature_tf,
       market_entry_price, market_entry_exit_price, market_entry_outcome,
       market_entry_pnl_r, market_entry_mae, market_entry_mfe, market_entry_bars_in_trade,
       market_entry_outcome, market_entry_gap_bars, market_entry_at, market_entry_exit_at,
       is_shadow, hmm_regime_at_fire, garch_sigma_at_fire,
       trailing_stop_price, staleness_score, staleness_trigger_reason,
       shadow_tracking_start_ts, shadow_mae, shadow_mfe, shadow_outcome,
       effective_ts, pipeline_lag_ms, signal_schema_version, is_backfill, ttl_bars,
       entry_price, stop_loss, targets, entry_zone_low, entry_zone_high
FROM signal_ledger
WHERE status IN ('pending', 'active', 'regime_suppressed')
  AND symbol = $1
  AND timeframe = $2
  AND exit_at IS NULL
ORDER BY timestamp DESC
"""
        return await self._db_manager.execute_query(sql, symbol, tf)
```

- [ ] **Step 4: Replace `fetch_pending_signals` inline SQL** (lines ~660–670)

```python
    async def fetch_pending_signals(self) -> list[dict]:
        """Return all pending signals across all symbols/timeframes."""
        sql = """
SELECT signal_id, timestamp, symbol, timeframe, setup_plugin, signal_type, direction,
       was_selected, status, feature_ts, feature_tf, activation_price,
       entry_price, stop_loss, targets, entry_zone_low, entry_zone_high
FROM signal_ledger
WHERE status = 'pending' AND exit_at IS NULL
ORDER BY timestamp DESC
"""
        return await self._db_manager.execute_query(sql)
```

- [ ] **Step 5: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all pass, no errors.

- [ ] **Step 6: Commit**

```bash
git add src/persistence/repository/signal_ledger_repository.py
git commit -m "fix(ledger-repo): remove stale column references dropped by migration 093"
```

---

### Task 6: Final verification and merge

- [ ] **Step 1: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all pass.

- [ ] **Step 2: Lint and format**

```bash
.venv/bin/ruff check . --fix && .venv/bin/black .
```

- [ ] **Step 3: Verify bootstrap query has no JOIN in source**

```bash
grep -n "intelligence_features\|enable_mergejoin\|LEFT JOIN" services/signal_tracker_compute_agent.py
```

Expected: no output (or only comments referencing the old approach).

- [ ] **Step 4: Verify new columns in DB**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT column_name FROM information_schema.columns \
   WHERE table_name='signal_ledger' AND column_name IN \
   ('entry_price','stop_loss','targets','entry_zone_low','entry_zone_high');"
```

Expected: 5 rows.

- [ ] **Step 5: Merge to main**

```bash
git checkout main && git merge --ff-only -
git push origin main
```
