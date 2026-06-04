# Delete signal_schema_version Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove `signal_schema_version` entirely — it is a proxy for field-presence invariants that are already enforced by `REQUIRED_SIGNAL_FIELDS` and DB column nullability; keeping it creates hidden training-data cliffs on every future schema bump.

**Architecture:** Make the DB column nullable first (migration), then strip the field from application code in layers (schema → pipeline → services → persistence → scripts), then update tests. All DB version filters are replaced with `entry_zone_low IS NOT NULL` — the actual structural invariant. Consumer version gates (alpha_swarm, narrative_swarm) are deleted entirely: `REQUIRED_SIGNAL_FIELDS` already guarantees zone presence at the production boundary.

**Tech Stack:** Python 3.11, asyncpg, PostgreSQL/TimescaleDB, pytest

---

## DB state at time of writing
- `v1` rows: 2,968,526 — 602,361 with NULL `entry_zone_low` (pre-zone rows), 2,366,165 valid
- `v2` rows: 81,866 — all have `entry_zone_low`
- `signal_ledger.signal_schema_version` is `text NOT NULL` — must make nullable before removing from INSERT

---

## Task 1: DB Migration — make signal_schema_version nullable

**Files:**
- Create: `production/migrations/117_drop_signal_schema_version_constraint.sql`

- [ ] **Step 1: Write migration**

```sql
-- Remove NOT NULL constraint. Application code stops writing this field.
-- The column stays for historical rows; DROP COLUMN in a future cleanup migration
-- once all v1/v2 rows have aged out of query windows.
ALTER TABLE signal_ledger
    ALTER COLUMN signal_schema_version DROP NOT NULL;

ALTER TABLE signal_ledger
    ALTER COLUMN signal_schema_version SET DEFAULT NULL;
```

- [ ] **Step 2: Apply migration**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent \
  -f production/migrations/117_drop_signal_schema_version_constraint.sql
```

Expected: `ALTER TABLE` twice, no errors.

- [ ] **Step 3: Verify**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT column_name, is_nullable, column_default FROM information_schema.columns \
   WHERE table_name='signal_ledger' AND column_name='signal_schema_version';"
```

Expected: `is_nullable = YES`, `column_default = NULL` (or empty).

---

## Task 2: Core schema — strip from signal_schema.py

**Files:**
- Modify: `src/intelligence/trading/signal_schema.py`

- [ ] **Step 1: Remove constant and all uses in this file**

In `signal_schema.py`:
1. Delete line: `SIGNAL_SCHEMA_VERSION = "v2"` (and the comment block above it)
2. Remove `"signal_schema_version"` from `REQUIRED_SIGNAL_FIELDS` frozenset
3. Remove line in `make_signal_from_frame()`: `sig["signal_schema_version"] = SIGNAL_SCHEMA_VERSION`

The `TYPE_CHECKING` import block is unrelated — leave it.

After: the file exports no `SIGNAL_SCHEMA_VERSION`, `REQUIRED_SIGNAL_FIELDS` has 16 fields instead of 17.

- [ ] **Step 2: Verify no remaining references in this file**

```bash
grep "signal_schema_version\|SIGNAL_SCHEMA_VERSION" src/intelligence/trading/signal_schema.py
```

Expected: no output.

---

## Task 3: Pipeline — remove from signal_processor.py

**Files:**
- Modify: `src/intelligence/pipeline/signal_processor.py`

- [ ] **Step 1: Remove import and setdefault call**

1. Remove `SIGNAL_SCHEMA_VERSION` from the import line at ~line 37 (update the import to not include it)
2. Delete line: `sig.setdefault("signal_schema_version", SIGNAL_SCHEMA_VERSION)` (~line 556)

- [ ] **Step 2: Verify**

```bash
grep "signal_schema_version\|SIGNAL_SCHEMA_VERSION" src/intelligence/pipeline/signal_processor.py
```

Expected: no output.

---

## Task 4: Services — remove consumer version gates

**Files:**
- Modify: `services/alpha_swarm.py`
- Modify: `services/narrative_swarm.py`

### alpha_swarm.py

- [ ] **Step 1: Remove import and gate**

1. Remove `SIGNAL_SCHEMA_VERSION` from the import at ~line 56
2. Delete these lines (~lines 446-448):
   ```python
   # Schema version gate — v0 signals have contaminated entry/zone data, skip entirely
   if raw_signal.get("signal_schema_version") != SIGNAL_SCHEMA_VERSION:
       return
   ```
   The defense is at the production boundary (`REQUIRED_SIGNAL_FIELDS` in `prepare_signals_or_dlq`). Any signal reaching this consumer passed schema validation with `zone_low` present.

### narrative_swarm.py

- [ ] **Step 2: Remove import and gate**

1. Remove `SIGNAL_SCHEMA_VERSION` from the import at ~line 32
2. Delete these lines (~lines 89-90):
   ```python
   if raw_signal.get("signal_schema_version") != SIGNAL_SCHEMA_VERSION:
       return
   ```

- [ ] **Step 3: Verify both files**

```bash
grep "signal_schema_version\|SIGNAL_SCHEMA_VERSION" services/alpha_swarm.py services/narrative_swarm.py
```

Expected: no output.

---

## Task 5: Services — replace DB version filters

**Files:**
- Modify: `services/signal_metrics_analyzer.py`
- Modify: `services/signal_replay_auditor.py`

### signal_metrics_analyzer.py

- [ ] **Step 1: Replace hardcoded version filter**

At ~line 101, replace:
```python
      AND signal_schema_version = 'v2'
```
with:
```python
      AND entry_zone_low IS NOT NULL
```

Also remove `SIGNAL_SCHEMA_VERSION` import if present (it's not — this file has a hardcoded string, not an import).

### signal_replay_auditor.py

The auditor has two queries that filter `signal_schema_version = $1` and pass `SIGNAL_SCHEMA_VERSION` as the parameter.

- [ ] **Step 2: Remove import**

Remove: `from src.intelligence.trading.signal_schema import SIGNAL_SCHEMA_VERSION` (~line 42)

- [ ] **Step 3: Fix `_fetch_unresolved` query**

Replace:
```python
              AND sl.signal_schema_version = $1
            ORDER BY sl.expires_at DESC
            LIMIT $2
        """
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            return await conn.fetch(query, SIGNAL_SCHEMA_VERSION, self.settings.replay_batch_size)
```
with:
```python
              AND sl.entry_zone_low IS NOT NULL
            ORDER BY sl.expires_at DESC
            LIMIT $1
        """
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            return await conn.fetch(query, self.settings.replay_batch_size)
```

- [ ] **Step 4: Fix `_count_unresolved` query**

Replace:
```python
                  AND signal_schema_version = $1
                """,
                SIGNAL_SCHEMA_VERSION,
```
with:
```python
                  AND entry_zone_low IS NOT NULL
                """,
```
(Remove `SIGNAL_SCHEMA_VERSION` argument entirely.)

- [ ] **Step 5: Verify**

```bash
grep "signal_schema_version\|SIGNAL_SCHEMA_VERSION" services/signal_metrics_analyzer.py services/signal_replay_auditor.py
```

Expected: no output.

---

## Task 6: Persistence — strip from repository, writer, tracker

**Files:**
- Modify: `src/persistence/repository/signal_ledger_repository.py`
- Modify: `services/signal_writer.py`
- Modify: `services/signal_tracker.py`

### signal_ledger_repository.py

- [ ] **Step 1: Remove import**

Delete: `SIGNAL_SCHEMA_VERSION,  # Ring 1 constant...` from the import block.

- [ ] **Step 2: Remove from SignalLedgerEntry dataclass**

Delete line: `signal_schema_version: str = SIGNAL_SCHEMA_VERSION`

- [ ] **Step 3: Remove from `_to_row()` and renumber**

Remove `self.signal_schema_version,  # $11` from the tuple.
Renumber all subsequent `# $N` comments: `$12`→`$11`, `$13`→`$12`, ..., `$29`→`$28`.

- [ ] **Step 4: Update `_INSERT_SQL`**

Remove `signal_schema_version,` from the column list (after `is_backfill,`).
Remove `$11,` from the values (the `$11, $12,` line becomes `$11,`).
Renumber all subsequent values: `$12`→`$11`, `$13`→`$12`, ..., `$29`→`$28`.

The updated VALUES block should be:
```sql
) VALUES (
    $1::uuid, $2, $3, $4,
    $5, $6, $7,
    $8, $9, $10,
    $11,
    $12, $13,
    $14, $15,
    $16,
    $17, $18, $19::jsonb, $20, $21,
    $22,
    $23, $24::jsonb, $25,
    $26, $27,
    $28
)
```

### signal_writer.py

- [ ] **Step 5: Remove from repository call**

Remove: `signal_schema_version=sig.get("signal_schema_version", SIGNAL_SCHEMA_VERSION),`
Remove the `SIGNAL_SCHEMA_VERSION` part of the import (keep `validate_signal`).

### signal_tracker.py

- [ ] **Step 6: Remove from in-memory signal dict**

Remove line: `"signal_schema_version": raw.get("signal_schema_version", SIGNAL_SCHEMA_VERSION),`

- [ ] **Step 7: Remove from bootstrap SELECT**

In `_BOOTSTRAP_QUERY` (~line 1120), remove `sl.signal_schema_version,` from the SELECT list.

- [ ] **Step 8: Remove import**

Remove `SIGNAL_SCHEMA_VERSION` from the import.

- [ ] **Step 9: Verify**

```bash
grep "signal_schema_version\|SIGNAL_SCHEMA_VERSION" \
  src/persistence/repository/signal_ledger_repository.py \
  services/signal_writer.py \
  services/signal_tracker.py
```

Expected: no output.

---

## Task 7: ML layer — strip from feature_builder and materializer

**Files:**
- Modify: `src/intelligence/ml/feature_builder.py`
- Modify: `src/intelligence/services/ml_signal_training_materializer.py`

### feature_builder.py

- [ ] **Step 1: Remove import and filter**

1. Remove: `from src.intelligence.trading.signal_schema import SIGNAL_SCHEMA_VERSION`
2. In `_TRAINING_SQL`, delete line: `  AND sl.signal_schema_version = $1`
3. Update `conn.fetch(_TRAINING_SQL, SIGNAL_SCHEMA_VERSION)` → `conn.fetch(_TRAINING_SQL)` (no parameter)
4. Update warning log: `logger.warning("feature_builder.no_rows")` (remove `schema_version=` kwarg)

### ml_signal_training_materializer.py

This file inserts `signal_schema_version` as a stamped value (not a filter). Remove it from both INSERT queries.

- [ ] **Step 2: Remove import**

Remove: `from src.intelligence.trading.signal_schema import SIGNAL_SCHEMA_VERSION`

- [ ] **Step 3: Remove from Phase A INSERT (upsert query ~lines 138, 172-183)**

In the first `INSERT INTO ml_signal_training (...)` block:
- Remove `signal_schema_version` from the column list
- Remove `$1::text` from the SELECT values list
- Change `conn.execute(sql, SIGNAL_SCHEMA_VERSION)` → `conn.execute(sql)` (no parameter)

- [ ] **Step 4: Remove from Phase B INSERT (~lines 216, 268)**

Same changes for the second INSERT query.

- [ ] **Step 5: Verify**

```bash
grep "signal_schema_version\|SIGNAL_SCHEMA_VERSION" \
  src/intelligence/ml/feature_builder.py \
  src/intelligence/services/ml_signal_training_materializer.py
```

Expected: no output.

---

## Task 8: Scripts — remove from lifecycle_replay and historical_backfill

**Files:**
- Modify: `production/scripts/lifecycle_replay.py`
- Modify: `production/scripts/historical_backfill.py`

### lifecycle_replay.py

- [ ] **Step 1: Remove from SELECT**

At ~line 395, remove `sl.signal_schema_version,` from the SELECT column list.
(The field is selected but never accessed by key — verified by grep.)

### historical_backfill.py

- [ ] **Step 2: Remove from INSERT**

In `_INSERT_SYNC_SQL` (~line 731):
- Remove `signal_schema_version` from the column list
- Remove `'v1'` from the VALUES (the `TRUE, 'v1'` line becomes `TRUE`)

- [ ] **Step 3: Verify**

```bash
grep "signal_schema_version\|SIGNAL_SCHEMA_VERSION" \
  production/scripts/lifecycle_replay.py \
  production/scripts/historical_backfill.py
```

Expected: no output.

---

## Task 9: Unit tests

**Files:**
- Modify: `tests/unit/intelligence/test_signal_schema.py`
- Modify: `tests/unit/pipeline/test_signal_processor.py`
- Modify: `tests/unit/services/test_alpha_swarm.py`
- Modify: `tests/unit/services/test_signal_replay_auditor.py`
- Modify: `tests/unit/services/test_signal_tracker_load_signal.py`
- Modify: `tests/unit/services/test_signal_tracker_backfill_fast_path.py`
- Modify: `tests/unit/services/test_signal_tracker_bootstrap.py`
- Modify: `tests/unit/services/test_signal_tracker_immutability.py`
- Modify: `tests/unit/services/test_intelligence_pipeline_publisher_normalization.py`

- [ ] **Step 1: test_signal_schema.py**

1. Remove `SIGNAL_SCHEMA_VERSION` from imports
2. Remove `"signal_schema_version": "v2"` from fixture dict
3. Delete assertion: `assert sig["signal_schema_version"] == SIGNAL_SCHEMA_VERSION`

- [ ] **Step 2: test_signal_processor.py**

1. Remove `SIGNAL_SCHEMA_VERSION` from imports
2. Delete entire test `test_prepare_signals_or_dlq_stamps_signal_schema_version` (the behavior no longer exists)

- [ ] **Step 3: test_alpha_swarm.py**

1. Remove `"signal_schema_version": "v1"` / `"v0"` / `_SSV` from all signal fixtures (lines 664, 688, 749)
2. Delete entire test `test_schema_gate_skips_v0_signals` (the gate no longer exists)

- [ ] **Step 4: test_signal_replay_auditor.py**

Delete the test at ~line 382 that verifies `signal_schema_version = $1`. Replace with a test that verifies `entry_zone_low IS NOT NULL` in the SQL:

```python
def test_fetch_unresolved_filters_on_zone_low() -> None:
    """_fetch_unresolved SQL must filter on entry_zone_low IS NOT NULL."""
    import inspect
    from services.signal_replay_auditor import SignalReplayAuditor
    src = inspect.getsource(SignalReplayAuditor._fetch_unresolved)
    assert "entry_zone_low IS NOT NULL" in src, (
        "_fetch_unresolved must filter entry_zone_low IS NOT NULL instead of schema version"
    )
```

- [ ] **Step 5: test_signal_tracker_*.py**

For each of the four tracker test files, remove `"signal_schema_version": ...` from all signal fixture dicts. Also remove any assertion that checks `isinstance(result["signal_schema_version"], str)` or `result["signal_schema_version"] == "v1"` (found in test_signal_tracker_load_signal.py ~lines 106, 116).

In `test_signal_tracker_bootstrap.py` ~line 225: remove `signal_schema_version="1"` kwarg from any repository/dataclass construction.

- [ ] **Step 6: test_intelligence_pipeline_publisher_normalization.py**

Remove `"signal_schema_version"` from any expected-fields lists or fixture dicts.

- [ ] **Step 7: Run unit tests**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all green.

---

## Task 10: Integration tests

**Files:**
- Modify: `tests/integration/test_pipeline_flow.py`
- Modify: `tests/integration/test_is_backfill_roundtrip.py`
- Modify: `tests/integration/test_lifecycle_writer_idempotency.py`
- Modify: `tests/integration/test_market_entry_completeness.py`
- Modify: `tests/integration/test_all_signals_resolved.py`

- [ ] **Step 1: test_pipeline_flow.py**

At ~line 128, remove `'signal_schema_version'` from the expected-fields list/assertion.

- [ ] **Step 2: test_is_backfill_roundtrip.py**

Remove `"signal_schema_version": "v1"` from the signal fixture at ~line 67.

- [ ] **Step 3: test_lifecycle_writer_idempotency.py**

Remove `signal_schema_version` from the SQL SELECT column list at ~line 43.

- [ ] **Step 4: test_market_entry_completeness.py**

Remove `signal_schema_version` from the SELECT column list at ~line 59.

- [ ] **Step 5: test_all_signals_resolved.py**

Remove `signal_schema_version` from SELECT at ~line 65.
Remove `AND signal_schema_version = 'v1'` filter at ~line 139.

---

## Task 11: Final verification

- [ ] **Step 1: Full grep — confirm no remaining references**

```bash
grep -r "signal_schema_version\|SIGNAL_SCHEMA_VERSION" \
  src/ services/ tests/ production/scripts/ \
  --include="*.py" -l
```

Expected: no output.

- [ ] **Step 2: Run unit tests**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all green.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "refactor(signals): delete signal_schema_version — replace proxy-invariant with structural guards"
```
