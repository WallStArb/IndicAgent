---
phase: 129-database-migration
reviewed: 2026-06-16T09:45:00Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - production/migrations/137_3table_schema.sql
  - production/migrations/138_signal_ledger_readonly.sql
  - production/scripts/migrate_signal_ledger.py
  - src/intelligence/trading/signal_schema.py
findings:
  critical: 3
  warning: 4
  info: 2
  total: 9
status: issues_found
---

# Phase 129: Code Review Report

**Reviewed:** 2026-06-16T09:45:00Z
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

Phase 129 delivered the three-table signal architecture DDL (migration 137), a read-only lock on
the legacy `signal_ledger` (migration 138), a 1.44M-row batch migration script, and a
`SIGNAL_SCHEMA_VERSION` bump to `"v5"`. The DDL and idempotency design are sound. Three critical
defects were found: the new `signal_ledger_full` view omits twelve columns that `signal_tracker.py`
queries on bootstrap (service crash on restart), `signal_replay_auditor.py` casts the now-text
`direction` field to `int` (runtime `ValueError`), and migration 138's `REVOKE` against the
`postgres` superuser role is a no-op (the write-lock guarantee is illusory). Four warnings cover
a latent NULL-direction crash, OFFSET-based pagination skew during concurrent writes, a missing
`direction` CHECK constraint, and numeric float8 fields in `frame_details` that bypass
`safe_float`.

---

## Critical Issues

### CR-01: `signal_ledger_full` view missing 12 columns — `signal_tracker` bootstrap crashes on restart

**File:** `production/migrations/137_3table_schema.sql:204-257`

**Issue:** The new `signal_ledger_full` view (lines 204-257) exposes only the columns present in
`signal_events + trade_frames + trade_executions`. It is missing every column that lived only in
the legacy `signal_ledger` monolith and was not ported to the new tables. `signal_tracker.py`
bootstraps by querying `signal_ledger_full` for 12 of these absent columns:

```
activated_at, activation_price, stop_loss, targets,
entry_zone_low, entry_zone_high, market_entry_price,
trailing_stop_price, chandelier_vol_source,
mae, mfe, exit_at
```

Confirmed missing via live DB query — `SELECT activated_at FROM signal_ledger_full` returns
`ERROR: column "activated_at" does not exist`. Because `signal_tracker._bootstrap_load_signals()`
uses `await conn.fetch(_BOOTSTRAP_QUERY)` and asyncpg raises on unknown columns, the service
fails to start (or starts with empty state after exhausting retries, silently losing all
in-flight signals).

This is not theoretical: the 33 live signals written to `signal_ledger` today
(`2026-06-16 09:15–09:35 UTC`) by the still-active `signal_ledger` writer were never migrated.
After migration 138 revokes writes to `signal_ledger` and Phase 130 drops it, these signals will
be permanently lost unless the view is extended.

**Fix:** Add the missing lifecycle columns to `signal_ledger_full`. The data for `entry_zone_low`,
`entry_zone_high`, `stop_loss` (as `stop_price`), `targets`, `market_entry_price`, and
`trailing_stop_price` partially exists in `trade_frames`/`trade_executions` or `frame_details`
JSONB. The remaining lifecycle fields (`activated_at`, `mae`, `mfe`, `exit_at`) do not yet have a
home in the new schema and require adding columns to `trade_frames` or creating a new
`signal_lifecycle` table. Until the view exposes them (or `signal_tracker` is updated to not
require them), a restart of `signal_tracker` will fail.

Minimum emergency fix to unblock restart:
```sql
-- Add lifecycle columns to trade_frames for Phase 130
ALTER TABLE trade_frames ADD COLUMN IF NOT EXISTS activated_at timestamptz;
ALTER TABLE trade_frames ADD COLUMN IF NOT EXISTS mae float8;
ALTER TABLE trade_frames ADD COLUMN IF NOT EXISTS mfe float8;
ALTER TABLE trade_frames ADD COLUMN IF NOT EXISTS exit_at timestamptz;

-- Then extend signal_ledger_full to include them
```

The `signal_tracker.py` bootstrap query also must be updated to use new canonical names
(`stop_price` not `stop_loss`, `target_price` not `targets`, etc.) after the view is extended.

---

### CR-02: `signal_replay_auditor` casts text `direction` to `int` — `ValueError` on every row

**File:** `services/signal_replay_auditor.py:235`

**Issue:** `signal_ledger_full.direction` now returns text `"long"` or `"short"` (sourced from
`signal_events.direction`, which the migration script correctly converts from `int` to text). The
replay auditor reads from `signal_ledger_full` (lines 97 and 135) and then calls:

```python
"direction": int(row["direction"]),   # line 235
```

`int("long")` raises `ValueError`. This error surfaces on every row processed by
`_build_signal_dict()`, causing the auditor to silently skip all signals or crash depending on
its exception handling. The PnL calculation at line 289 also does `int(state["direction"])` and
line 379 does `int(signal_dict["direction"])` — all three sites fail.

**Fix:** Replace the integer casts with a text-to-int conversion where the integer value is
genuinely needed, or update internal logic to use text direction throughout:

```python
# Option A: decode at load boundary
_DIRECTION_TO_INT = {"long": 1, "short": -1}
"direction": _DIRECTION_TO_INT.get(row["direction"], 0),

# Option B (preferred): propagate text direction and update PnL arithmetic
# line 289:
_side = 1 if state["direction"] == "long" else -1
_pnl_r = (float(bar["close"]) - _entry) * _side / _risk
```

`signal_tracker.py` line 378 has the same pattern (`int(raw.get("direction", 1))`) on data
sourced from Kafka payloads (not the DB), so verify whether those Kafka payloads still carry
integer direction or were also converted to text as part of Phase 129.

---

### CR-03: Migration 138 `REVOKE` against superuser is a no-op — write lock is ineffective

**File:** `production/migrations/138_signal_ledger_readonly.sql:7-8`

**Issue:** PostgreSQL superusers bypass all privilege checks. The `postgres` role is a superuser
(`Superuser, Create role, Create DB, Replication, Bypass RLS`). Revoking INSERT/UPDATE/DELETE from
a superuser has no effect — `SELECT has_table_privilege('postgres', 'signal_ledger', 'INSERT')`
returns `t` after the migration runs. Every service that connects as `postgres` (which is all of
them, per `DB_PARAMS` in the migration script and the project-wide connection pattern) retains
full write access to `signal_ledger`. The 48-hour transition guarantee stated in the migration
comment is not enforced.

**Fix:** Use a PostgreSQL row security policy or rename the table to create a write barrier that
superusers cannot bypass, or accept that this is a soft guard enforced at the application layer
(not the DB layer). If the intent is to prevent accidental writes, the migration comment should be
corrected to state that the lock applies to non-superuser roles only:

```sql
-- To protect against non-superuser writes:
REVOKE INSERT, UPDATE, DELETE ON signal_ledger FROM PUBLIC;
-- NOTE: postgres superuser bypass cannot be prevented via REVOKE.
-- Application-layer guard only. Consider RLS or table rename for hard enforcement.
```

---

## Warnings

### WR-01: `direction_to_text` returns `None` for unexpected values — silent NOT NULL violation

**File:** `production/scripts/migrate_signal_ledger.py:61-63`

**Issue:** `direction_to_text()` uses `dict.get()` with no default, returning `None` when
`direction_int` is not in `{1, -1}`. That `None` is passed directly into the INSERT tuple for
`signal_events.direction`, which is declared `NOT NULL`. The current data has no out-of-range
direction values (confirmed: `DISTINCT direction` returns only `{-1, 1}`), so this did not fire.
But a single corrupted row would cause a psycopg2 `IntegrityError` that rolls back the entire
batch, silently skipping up to 10,000 rows due to the `except` handler at line 396.

**Fix:**
```python
def direction_to_text(direction_int):
    result = DIRECTION_MAP.get(direction_int)
    if result is None:
        raise ValueError(f"Unexpected direction value: {direction_int!r}")
    return result
```

Alternatively, add a fallback and log a warning, but do not silently pass `None` into a NOT NULL
column.

---

### WR-02: OFFSET-based pagination is non-deterministic during concurrent writes

**File:** `production/scripts/migrate_signal_ledger.py:208-210, 365-370`

**Issue:** The migration uses `ORDER BY timestamp ASC, signal_id ASC LIMIT %s OFFSET %s` to
page through `signal_ledger`. If the `signal_ledger` writer is still active during migration
(which is the case — 33 live rows confirmed written today while migration was running), new rows
inserted at the end shift offsets. This causes:
- Rows near the last batch boundary to be skipped as the count grows.
- `total_rows` (captured at line 479) diverges from actual row count at each batch, making
  `num_batches` too small and leaving the most-recent rows unprocessed.

This explains exactly the 33 unprocessed rows observed (`signal_ledger` has 1,443,264 rows;
`signal_events` has 1,443,231 — a difference of 33, all timestamped today during the live
migration window).

**Fix:** Capture a snapshot via a stable cursor or use `WHERE timestamp < :cutoff` based on the
pre-migration timestamp:

```python
# Capture a stable upper bound before starting migration
cutoff_ts = conn.execute("SELECT MAX(timestamp) FROM signal_ledger").fetchone()[0]

# Then use WHERE timestamp <= cutoff_ts in SELECT_SQL
# This makes the page count stable regardless of concurrent inserts
```

Or run the migration with `signal_ledger` writes already blocked (apply migration 138 first, then
138, then run the script).

---

### WR-03: `build_frame_details` stores numeric fields without `safe_float` — Decimal serialization risk

**File:** `production/scripts/migrate_signal_ledger.py:139-156`

**Issue:** `build_frame_details` passes several `numeric`-typed columns directly into the dict
without calling `safe_float()`:

```python
"structural_stop_distance_atr": row["structural_stop_distance_atr"],  # numeric
"adaptive_buffer_mult": row["adaptive_buffer_mult"],                   # numeric
"trailing_stop_price": row["trailing_stop_price"],                     # jsonb
"trailing_stop_tightening_rate": row["trailing_stop_tightening_rate"], # float8
"shadow_mae": row["shadow_mae"],                                        # float8
"shadow_mfe": row["shadow_mfe"],                                        # float8
```

psycopg2 returns `numeric` columns as Python `Decimal` objects. `json.dumps()` at line 350
does not know how to serialize `Decimal`, and will raise `TypeError: Object of type Decimal is
not JSON serializable` when any of these fields is non-NULL. The migration succeeded (all
1,443,231 rows were inserted), which means these columns were NULL for all rows in the dataset.
If any future row or a different dataset has non-NULL values, `json.dumps` will crash and the
entire batch will be rolled back silently.

**Fix:**
```python
"structural_stop_distance_atr": safe_float(row["structural_stop_distance_atr"]),
"adaptive_buffer_mult": safe_float(row["adaptive_buffer_mult"]),
"trailing_stop_tightening_rate": safe_float(row["trailing_stop_tightening_rate"]),
"shadow_mae": safe_float(row["shadow_mae"]),
"shadow_mfe": safe_float(row["shadow_mfe"]),
```

Note: `trailing_stop_price` is `jsonb` in `signal_ledger` (confirmed via schema), so psycopg2
returns it as a dict/list — no `safe_float` needed there, but it is already handled by
`json.dumps` at the outer level correctly.

---

### WR-04: `signal_ledger_full` view missing `direction` CHECK constraint on base tables

**File:** `production/migrations/137_3table_schema.sql:37, 116`

**Issue:** Both `signal_events.direction` and `trade_frames.direction` are declared `NOT NULL text`
with a comment `-- long / short`, but there is no `CHECK` constraint enforcing the value set.
Any writer that passes an arbitrary string (or the old integer `1` / `-1` as text) will be
accepted silently, producing direction values that break downstream arithmetic (e.g., PnL
calculations that decode direction by string comparison). Given that `signal_tracker.py` still
casts direction with `int()`, the schema has no enforcement layer to catch regressions.

**Fix:**
```sql
ALTER TABLE signal_events ADD CONSTRAINT chk_signal_events_direction
    CHECK (direction IN ('long', 'short'));

ALTER TABLE trade_frames ADD CONSTRAINT chk_trade_frames_direction
    CHECK (direction IN ('long', 'short'));
```

---

## Info

### IN-01: `SIGNAL_SCHEMA_VERSION = "v5"` is an orphaned constant — never consumed

**File:** `src/intelligence/trading/signal_schema.py:25-27`

**Issue:** `SIGNAL_SCHEMA_VERSION` is defined as `"v5"` but is not imported or referenced anywhere
outside `signal_schema.py` itself. The comment on line 13 says `signal_schema_version` is the
DB column type (text), but `signal_events.signal_schema_version` is now `int4` (per migration 137,
line 53). The constant type (`str = "v5"`) and the DB column type (`int4`) are mismatched —
if the constant were ever used to write to the DB, psycopg2/asyncpg would reject it unless cast.

Since the constant is unused, this is currently dead code. The comment on line 13 is also stale
("text type" was the legacy column type; the new schema uses int4).

**Fix:** Either delete the constant (it serves no purpose as-is), or update it to `int = 5` and
wire it into the signal construction path and DB write path so Kafka payloads and new rows carry
the correct version stamp.

---

### IN-02: `migrated` counter includes ON CONFLICT skipped rows — progress reporting is inaccurate

**File:** `production/scripts/migrate_signal_ledger.py:388`

**Issue:** `migrated += len(rows)` counts the source rows fetched, not the rows actually
inserted. `ON CONFLICT DO NOTHING` silently skips duplicates. On a re-run, `migrated` will
report 1,443,231 rows "processed" even if every row was skipped. For a one-shot migration this
is cosmetic, but for a restart scenario (e.g., after a batch failure) the operator cannot tell
from the output whether data was actually written.

**Fix:**
```python
# Use cursor.rowcount after execute_values to get actual insert count
psycopg2.extras.execute_values(cur, SIGNAL_EVENTS_INSERT, se_rows, ...)
se_inserted = cur.rowcount  # rows actually inserted (not skipped by ON CONFLICT)
migrated += se_inserted
```

Note: `execute_values` sets `rowcount` to the total rows affected, not the page count.

---

_Reviewed: 2026-06-16T09:45:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
