---
phase: 134-signal-classification-type-safety
reviewed: 2026-06-18T00:00:00Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - production/migrations/149_phase134_outcome_column.sql
  - production/migrations/150_phase134_entry_type_constraint.sql
  - production/migrations/151_phase134_pg_enum_types.sql
  - production/scripts/lifecycle_replay.py
  - src/intelligence/ai/narrative/narrative_prompts.py
  - src/intelligence/trading/gap_analysis_setup.py
  - src/intelligence/trading/lifecycle_tracker.py
  - src/intelligence/trading/plugin_utils.py
  - src/intelligence/trading/signal_outcome.py
  - src/intelligence/trading/signal_schema.py
  - src/intelligence/trading/trade_framer.py
  - src/persistence/repository/signal_events_repository.py
  - tests/unit/intelligence/test_signal_outcome.py
  - tests/unit/intelligence/trading/test_entry_type_enum.py
  - tests/unit/intelligence/trading/test_outcome_persistence.py
  - tests/unit/intelligence/trading/test_pg_enum_enforcement.py
findings:
  critical: 2
  warning: 4
  info: 3
  total: 9
status: issues_found
---

# Phase 134: Code Review Report

**Reviewed:** 2026-06-18
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

Phase 134 adds a 9th `SignalOutcome` member (`CONDITION_EXPIRED`), promotes three text columns to PG ENUM types, and upgrades `lifecycle_replay.py` with the new `outcome` column in `trade_executions`. The migrations are well-structured and the type system changes are sound. Two critical bugs were found: a `NameError` in `lifecycle_replay.py` that fires on every target-exit during zone-track processing, and a latent constraint violation between `lifecycle_tracker.py`'s target exit reasons and the new `chk_te_exit_reason` constraint. Four warnings and three info-level issues round out the review.

## Critical Issues

### CR-01: `NameError` on zone-track target exits in `lifecycle_replay.py`

**File:** `production/scripts/lifecycle_replay.py:786`

**Issue:** `z_bit` is assigned at line 763 only inside the `if z_outcome is None:` branch (stop-loss path). The variable is then referenced unconditionally at line 786 (`"bars_in_trade": z_bit`) inside the enclosing `else` block, which executes for every zone exit including target exits where `z_trans.outcome is not None`. When a target exit occurs:

1. First signal ever to reach target in a replay run: `z_bit` is undefined — `NameError` crashes the worker.
2. Subsequent signals: `z_bit` silently holds the stale value from the last stop-loss exit processed in the same `for sid in live_sids` loop — `bars_in_trade` is wrong.

**Fix:** Compute `z_bit` unconditionally before the `if z_outcome is None` branch:

```python
# Zone exit — classify outcome and mark resolved
z_outcome = z_trans.outcome
z_bit = int(
    (bar_ts - zone_activated_at.get(sid, bar_ts)).total_seconds()
    / tf_secs
)
if z_outcome is None:
    z_outcome = _classify_stop_outcome(z_mfe, z_bit)
```

---

### CR-02: `chk_te_exit_reason` constraint rejects T2/T3 zone-track exits

**File:** `production/migrations/151_phase134_pg_enum_types.sql:141-153`

**Issue:** The `chk_te_exit_reason` constraint lists `'target_1'`, `'target_1_2'`, `'target_full'` as valid `exit_reason` values. These are `SignalOutcome` string values, not the exit-reason strings produced by `lifecycle_tracker.py`. `_check_active_exit()` uses `f"target_{i+1}"` for exit reasons, producing `"target_2"` (T2 hit, `i=1`) and `"target_3"` (T3 hit, `i=2`). Neither is in the constraint allowlist.

The constraint was applied with the comment that no T2/T3 exits exist in the current corpus. When any signal first reaches its second target on the zone track during a live replay or backfill, the INSERT into `trade_executions` will raise a constraint violation and the entire batch will be lost.

**Fix:** Either align the constraint with what `lifecycle_tracker.py` actually produces, or normalize `exit_reason` before writing. The simplest fix is updating the constraint:

```sql
-- Replace in migration 151 Step 5 (or add migration 152):
ALTER TABLE trade_executions DROP CONSTRAINT IF EXISTS chk_te_exit_reason;
ALTER TABLE trade_executions
    ADD CONSTRAINT chk_te_exit_reason
    CHECK (exit_reason IS NULL OR exit_reason IN (
        'stop_loss',
        'chandelier_stop',
        'condition_expired',
        'ttl_expired',
        'ttl_expired_ahead',
        'ttl_expired_behind',
        'target_1',
        'target_2',
        'target_3',
        'target_1_2',
        'target_full'
    ));
```

Or normalize in `_flush_writes` before the INSERT:

```python
# Map target_N exit_reason to canonical form
_EXIT_REASON_MAP = {
    "target_2": "target_1_2",
    "target_3": "target_full",
}
exit_reason = _EXIT_REASON_MAP.get(data.get("exit_reason"), data.get("exit_reason"))
```

Note: the `IS NULL OR` clause is also needed (see WR-04).

## Warnings

### WR-01: Market-track stop exits write `NULL` `exit_reason` to `trade_executions`

**File:** `production/scripts/lifecycle_replay.py:1052-1069`

**Issue:** `_flush_writes` writes `m_outcome` as both the `exit_reason` ($11) and `outcome` ($14) parameters for market-track rows. For stop-loss exits, `_make_market_exit()` returns a `MarketTransition` with `outcome=None`. This means `exit_reason=NULL` and `outcome=NULL` in `trade_executions` for all market-track stop exits. Querying market stop rates on `trade_executions` directly will produce zero results for market stops — the data is silently missing from `exit_reason`.

**Fix:** Populate `exit_reason='stop_loss'` independently from `outcome` in the market-track INSERT, and call `_classify_stop_outcome()` to derive the stop outcome before writing:

```python
m_exit_reason = data.get("market_entry_exit_reason") or (
    "stop_loss" if m_outcome is None else m_outcome
)
# For market stop exits, derive outcome from bars/mfe:
if m_outcome is None:
    m_outcome = _classify_stop_outcome(
        data.get("market_entry_mfe") or 0.0,
        data.get("market_entry_bars_in_trade"),
    ).value
```

---

### WR-02: Exception variable named `exc` instead of `error`

**File:** `production/scripts/lifecycle_replay.py:657, 722, 937`

**Issue:** CLAUDE.md mandates `except X as error:` throughout the codebase. Three catch blocks in `lifecycle_replay.py` use `exc` instead:

```python
except Exception as exc:  # lines 657, 722, 937
```

**Fix:**

```python
except Exception as error:
    logger.warning("market eval error %s: %s", sid, error)
```

---

### WR-03: `get_active_contracts()` called without `settings` argument

**File:** `production/scripts/lifecycle_replay.py:1354`

**Issue:** CLAUDE.md requires `get_active_contracts(settings)` — passing the `Settings` instance explicitly. Line 1354 calls `get_active_contracts()` with no argument, which causes the function to create a new `Settings()` instance via `_default_settings()` internally. `settings` is already constructed at line 1349 and available in scope. The bare call is inconsistent with the project rule and may use different configuration if environment variables differ at call time.

**Fix:**

```python
symbols = (
    args.symbols.split(",")
    if args.symbols
    else [c.symbol for c in get_active_contracts(settings)]
)
```

---

### WR-04: `chk_te_exit_reason` does not explicitly allow `NULL`

**File:** `production/migrations/151_phase134_pg_enum_types.sql:141-153`

**Issue:** The constraint uses `CHECK (exit_reason IN (...))`. In PostgreSQL, `NULL IN (...)` evaluates to `NULL` (unknown), which satisfies a CHECK constraint. This is safe today but is non-obvious: a reader seeing this constraint would expect it to block `NULL` values. If the column ever gains a `NOT NULL` constraint, the current expression covers the right values. However, making the null-permissiveness explicit improves readability and avoids accidents if someone copies the pattern without understanding PostgreSQL's CHECK NULL semantics.

Additionally, when CR-02 is fixed, the corrected constraint should explicitly include `IS NULL OR` to make intent clear and to guard against potential future changes to CHECK semantics in PostgreSQL forks.

**Fix:**

```sql
ALTER TABLE trade_executions
    ADD CONSTRAINT chk_te_exit_reason
    CHECK (exit_reason IS NULL OR exit_reason IN (
        'stop_loss',
        ...
    ));
```

## Info

### IN-01: `SignalOutcome` docstring still says "8-class" after adding the 9th member

**File:** `src/intelligence/trading/signal_outcome.py:7`

**Issue:** The class docstring reads `"Signal exit outcome — the 8-class classification used as ML training labels."` Phase 134 added `CONDITION_EXPIRED` as the 9th member. The comment is now incorrect and will mislead anyone reading the taxonomy.

**Fix:**

```python
"""Signal exit outcome — the 9-class classification used as ML training labels.
```

Also update the same stale comment at `src/persistence/repository/signal_events_repository.py:79`:
```python
# Signal outcome re-exports — 9-class ML training label taxonomy
```

---

### IN-02: `test_signal_outcome_values_match_db_strings` does not cover `CONDITION_EXPIRED`

**File:** `tests/unit/intelligence/test_signal_outcome.py:14-21`

**Issue:** `test_signal_outcome_values_match_db_strings` asserts the string values of 8 members but omits `CONDITION_EXPIRED`. Since `test_outcome_taxonomy_is_exhaustive` and `TestConditionExpiredIsValidOutcome` in the other test file do verify it, this is a coverage gap rather than a blind spot. But the existing test by name implies it tests all DB strings, and it does not.

**Fix:** Add the assertion:

```python
assert SignalOutcome.CONDITION_EXPIRED.value == "condition_expired"
```

---

### IN-03: `_process_symbol_tf` opens two connections for the same (symbol, tf) pair

**File:** `production/scripts/lifecycle_replay.py:430-545`

**Issue:** The function acquires a connection at line 431 inside `async with db.pool.acquire()`, uses it for the signals query, then releases it implicitly when the `async with` block exits at line 470. It then acquires a second connection at line 545 (`conn = await db.pool.acquire()`) for bar streaming. The first connection is used only for fetching signals, which could be done on the same connection used for bar streaming. With 8 workers and many (symbol, tf) pairs, this doubles peak connection consumption during the signal-fetch phase.

**Fix:** Reuse the bar-streaming connection for the signal query by restructuring to acquire once:

```python
conn = await db.pool.acquire()
try:
    await conn.execute("BEGIN")
    signals = await conn.fetch(...)
    ...
    # bar streaming continues on same conn
```

---

_Reviewed: 2026-06-18_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
