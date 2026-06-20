---
phase: 131-signal-generation-integrity
reviewed: 2026-06-17T00:00:00Z
depth: deep
files_reviewed: 8
files_reviewed_list:
  - production/scripts/lifecycle_replay.py
  - production/scripts/run_historical_pipeline.py
  - src/intelligence/features/smc_context/bocpd_changepoint.py
  - src/intelligence/pipeline/feature_pipeline_executor.py
  - src/intelligence/trading/anchored_vwap_reversion.py
  - src/intelligence/trading/cross_asset_divergence.py
  - tests/unit/pipeline/test_feature_pipeline_executor_seed.py
  - tests/unit/test_anchored_vwap_reversion.py
findings:
  critical: 3
  warning: 4
  info: 2
  total: 9
status: issues_found
---

# Phase 131: Code Review Report

**Reviewed:** 2026-06-17
**Depth:** deep
**Files Reviewed:** 8
**Status:** issues_found

## Summary

Phase 131 correctly delivers the five advertised fixes (A4 asset_class injection, A6 BOCPD
look-ahead bias, A7 CTF cold-start seed, AnchoredVWAPReversion gate ordering, B6/B7 integrity
assertions). The core logic in each fix is sound. However, three defects were found that were
not part of the advertised changes but exist in adjacent code: a variable-before-assignment
that produces silent data corruption on zone exits with known outcomes, a NULL-parameter
silent no-op in `_reset_corrupt_data`, and an asyncpg JSONB anti-pattern in `_flush_writes`.
Four additional warnings cover convention violations and a missing shadow_only attribute.

---

## Critical Issues

### CR-01: `z_bit` used before assignment — silent data corruption in zone exits

**File:** `production/scripts/lifecycle_replay.py:786`

**Issue:** `z_bit` is only assigned inside the `if z_outcome is None:` branch (lines 763-767),
but is unconditionally referenced at line 786 (`"bars_in_trade": z_bit`) in the enclosing
zone-exit `else` block. When `z_trans.outcome` is already non-None (e.g. a direct stop-hit or
target-hit result from `evaluate_signal`), the `if z_outcome is None:` block is skipped and
`z_bit` is never set for this iteration.

Because `z_bit` is a local variable inside the `for sid in live_sids:` loop (not the outer
function), if a prior loop iteration set it, the stale value is silently used as
`bars_in_trade` for the current signal — recording the wrong signal's elapsed bar count.
If this is the very first zone exit in the batch (no prior iteration set `z_bit`), the
result is `UnboundLocalError`, crashing the worker.

In practice, `evaluate_signal` typically returns outcomes via `z_trans.outcome` only on the
final bar when a stop or target is hit cleanly. This will corrupt `bars_in_trade` for all
such "clean exit" signals whenever they are not the first exit in a batch.

**Fix:**
```python
# Replace the conditional z_bit assignment with an unconditional one:
else:
    # Zone exit — classify outcome and mark resolved
    z_outcome = z_trans.outcome
    z_bit = int(
        (bar_ts - zone_activated_at.get(sid, bar_ts)).total_seconds() / tf_secs
    )
    if z_outcome is None:
        z_outcome = _classify_stop_outcome(z_mfe, z_bit)
    stats["zone"][z_outcome] = ...
    pending_writes.append(
        (..., "bars_in_trade": z_bit, ...)
    )
```

---

### CR-02: `_reset_corrupt_data` silently no-ops when `after` or `before` is `None`

**File:** `production/scripts/lifecycle_replay.py:263-356`

**Issue:** `_reset_corrupt_data(db, symbols, timeframes, after, before)` is typed
`after: datetime, before: datetime` but the caller at line 1413 passes `after=None` and/or
`before=None` when `--reset-after` or `--reset-before` flags are omitted. The SQL queries
inside the function use:

```sql
WHERE se.ts >= $1 AND se.ts < $2
```

When asyncpg passes Python `None` as `$1` or `$2`, PostgreSQL evaluates `ts >= NULL` which is
`NULL` (not `TRUE`), so the `WHERE` clause matches **zero rows**. All three DELETE/UPDATE
statements silently affect no rows (`executions_deleted=0`, `outcomes_reset=0`). However,
`TRUNCATE swarm_agent_weights` and `TRUNCATE setup_performance` still execute. The operator
sees "reset complete" with zero row counts and proceeds to replay, which then inserts
into an empty state — producing a corpus with all prior signal data intact (not wiped) but
derived tables (weights, perf) truncated.

This is an intended "full reset" use case (no date bounds) that is silently broken.

**Fix:**
```python
async def _reset_corrupt_data(
    db: DatabaseManager,
    symbols: list[str],
    timeframes: list[str],
    after: datetime | None,
    before: datetime | None,
) -> dict:
    ...
    # In the DELETE query, use COALESCE or conditional WHERE:
    result = await conn.execute(
        """DELETE FROM trade_executions
           WHERE frame_id IN (
               SELECT tf.frame_id
               FROM trade_frames tf
               JOIN signal_events se ON tf.signal_id = se.signal_id AND tf.signal_ts = se.ts
               WHERE ($1::timestamptz IS NULL OR se.ts >= $1)
                 AND ($2::timestamptz IS NULL OR se.ts < $2)
                 AND se.symbol = ANY($3)
                 AND se.tf = ANY($4)
           )""",
        after, before, symbols, timeframes,
    )
```
Apply the same pattern to the other two UPDATE statements.

---

### CR-03: Exception variable named `exc` violates project convention

**File:** `production/scripts/lifecycle_replay.py:657, 722, 937`

**Issue:** Three `except` blocks use `exc` as the exception variable name, violating the
CLAUDE.md mandate: "Exception variable name is `error` — `except X as error:`, not `exc`."

```python
# Line 657
except Exception as exc:
    logger.warning("market eval error %s: %s", sid, exc)

# Line 722
except Exception as exc:
    logger.warning("zone eval error %s: %s", sid, exc)

# Line 937
except Exception as exc:
    logger.error("Error processing %s %s: %s", symbol, timeframe, exc)
```

**Fix:** Rename all three to `error`:
```python
except Exception as error:
    logger.warning("market eval error %s: %s", sid, error)
```

---

## Warnings

### WR-01: asyncpg JSONB passed as `json.dumps()` string — anti-pattern violation

**File:** `production/scripts/lifecycle_replay.py:998-1001`

**Issue:** `_flush_writes` constructs `activation_meta` as a dict and then passes
`json.dumps(activation_meta)` to asyncpg for a `JSONB` column, with an explicit `::jsonb`
cast in SQL:

```python
await conn.execute(
    """UPDATE trade_frames
       SET frame_details = COALESCE(frame_details, '{}'::jsonb) || $2::jsonb
       WHERE signal_id = $1::uuid""",
    sid,
    json.dumps(activation_meta),   # <-- anti-pattern
)
```

CLAUDE.md rule: "asyncpg JSONB → pass dicts (no `json.loads()`/`json.dumps()`)." While the
`::jsonb` cast in SQL makes this functional, it forces a text→JSONB parse on every activation
write, adds encoding overhead, and deviates from the project's established pattern. The correct
approach is to pass the dict directly and let asyncpg handle serialization.

**Fix:**
```python
await conn.execute(
    """UPDATE trade_frames
       SET frame_details = COALESCE(frame_details, '{}'::jsonb) || $2
       WHERE signal_id = $1::uuid""",
    sid,
    activation_meta,  # pass dict directly; asyncpg serializes JSONB natively
)
```

---

### WR-02: `CrossAssetDivergencePlugin` has no `shadow_only` attribute and uses hardcoded APR thresholds

**File:** `src/intelligence/trading/cross_asset_divergence.py:59-98`

**Issue (a) — Missing `shadow_only`:** The plugin dataclass does not declare `shadow_only`.
Per CLAUDE.md Plugin System: "6 GOOD patterns: ... `shadow_only=True`." The `validate_tier()`
function may not catch the omission for this specific attribute, but the absence means the
plugin will run in live mode rather than shadow-only by default, bypassing the proof-first
governance requirement.

**Issue (b) — APR violations:** Eight numeric constants are hardcoded at module level
(`_FIRE_THRESHOLD`, `_CONF_BASE`, `_CONF_SPREAD_SCALE`, `_CONF_MULTI_PAIR_MULT`,
`_CONF_MULTI_TF_MULT`, `_CONF_VOL_IMBALANCE_BOOST`, `_CONF_VOL_IMBALANCE_THRESHOLD`,
`_CONF_REGIME_PROB_THRESHOLD`, `_CONF_REGIME_PROB_BOOST`). Per CLAUDE.md Adaptive Parameter
Registry: "Hard-coded numeric thresholds, weights, periods, or counts in `src/` are an
architecture violation." None are loaded via `ConfigService.get()`. The plugin has no
`_config_service` attribute.

**Fix (a):** Add `shadow_only: bool = True` to the dataclass.

**Fix (b):** Add `_config_service: Any = field(default=None, compare=False, repr=False)` and
load each constant via `cfg.get_sync("threshold.cross_asset.fire_threshold", 2.0) if cfg else 2.0`
pattern, registering parameters in a migration. Also add `set_config_service()` and
register in `intelligence_pipeline._prewarm_threshold_config()`.

---

### WR-03: `get_active_contracts()` called without `settings` argument in lifecycle_replay

**File:** `production/scripts/lifecycle_replay.py:1350`

**Issue:** The CLAUDE.md convention: "Call as `get_active_contracts(settings)`, not
`settings.get_active_contracts()`." Line 1350 calls `get_active_contracts()` without the
`settings` parameter, causing the function to construct its own `Settings()` instance
internally. This is not a runtime failure (the function handles it), but it silently
constructs a second Settings object during replay — diverging from the `settings` instance
already constructed at line 1344.

**Fix:**
```python
# Line 1344
settings = Settings()
# Line 1350
symbols = (
    args.symbols.split(",") if args.symbols else [c.symbol for c in get_active_contracts(settings)]
)
```

---

### WR-04: `_process_symbol_tf` — connection potentially undefined in outer `except` handler

**File:** `production/scripts/lifecycle_replay.py:937-945`

**Issue:** The outer `try` block in `_process_symbol_tf` (line 427) contains two connection
acquisitions. The first uses `async with db.pool.acquire() as conn:` (lines 430-470, context
manager releases on exit). The second is `conn = await db.pool.acquire()` (line 545). If an
exception is raised between lines 472-544 (after the first context manager exits but before
the second `conn` is assigned), the outer `except` handler at line 937 will execute
`await conn.execute("ROLLBACK")` and `await db.pool.release(conn)` on the already-released
first connection — potentially returning a released connection to the pool a second time.

The inner `try/except Exception: pass` at line 940 prevents a crash, but `conn` in this case
refers to the old asyncpg `Connection` object from the first block, not `None`. A double-release
of a pool connection corrupts the asyncpg pool state.

This window is narrow (lines 472-544 only compute `_assert_row_types` and dict manipulations),
but if `_assert_row_types` raises, the pool will receive a double-release.

**Fix:** Initialize `conn` to `None` before the try block and guard the `except` handler:
```python
conn = None
try:
    async with db.pool.acquire() as conn:
        ...
    # signals loaded, conn released
    if not signals:
        return stats
    conn = await db.pool.acquire()
    ...
except Exception as error:
    logger.error(...)
    if conn is not None:
        try:
            if not dry_run:
                await conn.execute("ROLLBACK")
            await db.pool.release(conn)
        except Exception:
            pass
```

---

## Info

### IN-01: `replay_symbol` A7 seed reads only 4 standard TFs but function processes all requested TFs including 4h/1d

**File:** `production/scripts/run_historical_pipeline.py:1694`

**Issue:** The A7 seed in `replay_symbol` hardcodes `_standard_tfs = ["1m", "5m", "15m", "1h"]`
and only seeds `intelligence_cache` for those four TFs:

```python
_standard_tfs = ["1m", "5m", "15m", "1h"]
for _seed_tf in _standard_tfs:
```

However, `replay_symbol` processes whatever `timeframes` list is passed, which can include
`"4h"` and `"1d"` (the default `DEFAULT_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]`).
For 4h and 1d timeframes, the I6 CTF cold-start seed is not applied. On a full rebuild that
includes 4h/1d, the first few bars of those TFs will still have `ctf_score=0` from the
cold-start problem the A7 fix aimed to eliminate.

**Fix:** Replace the hardcoded list with the actual `timeframes` parameter:
```python
for _seed_tf in timeframes:
    with db_conn.cursor() as _cur:
        _cur.execute(...)
```
Or document explicitly why 4h/1d are intentionally excluded.

---

### IN-02: Test for `_seed_last_events_from_db` does not assert `trend_duration_bars` mapping

**File:** `tests/unit/pipeline/test_feature_pipeline_executor_seed.py:78-83`

**Issue:** `test_seed_populates_last_events_with_trend_fields` asserts that `trend_direction`
and `trend_strength` are correctly seeded into the I3 structure, but does not verify
`trend_duration_bars` (which maps from DB column `trend_bars_elapsed`). The mapping in the
implementation is:

```python
trend_duration_bars=(
    float(trend_bars_elapsed_raw) if trend_bars_elapsed_raw is not None else None
),
```

The test passes `"trend_bars_elapsed": "5"` in `fake_row` but never asserts
`event.i3.trend_duration_bars == 5.0`. A future rename or mismatch in the `I3Structure`
field name would not be caught by the test.

**Fix:** Add an assertion:
```python
assert event.i3.trend_duration_bars == pytest.approx(5.0), \
    f"Expected trend_duration_bars=5.0, got {event.i3.trend_duration_bars}"
```

---

_Reviewed: 2026-06-17_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
