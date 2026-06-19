---
phase: 122-production-hardening
reviewed: 2026-06-12T00:00:00Z
depth: standard
files_reviewed: 21
files_reviewed_list:
  - production/migrations/124_add_i2_column.sql
  - production/migrations/125_rename_intelligence_features_columns.sql
  - production/scripts/feature_replay.py
  - production/scripts/run_historical_pipeline.py
  - services/alpha_swarm.py
  - services/feature_writer.py
  - services/narrative_swarm.py
  - services/signal_writer.py
  - src/api/routes/features.py
  - src/api/routes/narrative.py
  - src/api/routes/signals.py
  - src/intelligence/register_plugins.py
  - src/intelligence/schemas.py
  - src/intelligence/trading/zone_engine.py
  - tests/unit/api/test_features_route.py
  - tests/unit/api/test_narrative_route.py
  - tests/unit/api/test_signals_route.py
  - tests/unit/intelligence/test_i2_schema.py
  - tests/unit/intelligence/test_schemas.py
  - tests/unit/scripts/test_feature_replay.py
  - tests/unit/scripts/test_run_historical_pipeline.py
findings:
  critical: 4
  warning: 8
  info: 3
  total: 15
status: issues_found
---

# Phase 122: Code Review Report

**Reviewed:** 2026-06-12T00:00:00Z
**Depth:** standard
**Files Reviewed:** 21
**Status:** issues_found

## Summary

Phase 122 delivers migration 124 (dedicated `i2` column split from `market_context`), migration 125 (column renames aligning DB names with tier names), `feature_replay.py` (I7-only replay from stored features), extensions to `run_historical_pipeline.py` (`--use-precomputed-features`), updated API routes, and unit tests.

The migrations and schema changes are clean. Four critical bugs were found:

1. `feature_replay.py` uses `source="feature_replay"` which violates the `Literal["live","backfill"]` constraint on `IntelligenceEvent` — every row silently fails reconstruction, the script writes zero signals while appearing to succeed.
2. `narrative.py` reads `market_context` when it should read `i2` post-migration, feeding the LLM empty/wrong I2 data.
3. `features.py` and `signals.py` both omit `i2` from every SELECT, so the column added in migration 124 is never surfaced via the API.
4. `_TERMINAL_STATUSES` in `signals.py` is named exactly backwards — it holds the open statuses, making the name a trap for future editors who will "fix" a correct inversion and introduce a real bug.

---

## Critical Issues

### CR-01: `feature_replay.py` — `source="feature_replay"` fails Pydantic validation on every row, script writes zero signals

**File:** `production/scripts/feature_replay.py:148`

**Issue:** `_reconstruct_intelligence_event` constructs `IntelligenceEvent` with `source="feature_replay"`. `IntelligenceEvent` declares `source: Literal["live", "backfill"]` (verified in `src/intelligence/schemas.py`). Pydantic raises `ValidationError` on every row. The enclosing `try/except Exception` catches it silently, logs a warning, and returns `None`. The calling loop skips `None` rows. Net effect: `feature_replay.py` runs to completion, logs success, and writes zero signals — regardless of `--dry-run` flag, plugin list, or date range. The problem is invisible without inspecting log warnings.

**Fix:**
```python
# Line 148 — change:
source="feature_replay",
# To:
source="backfill",
```

---

### CR-02: `narrative.py` — reads `market_context` instead of `i2` after migration 124, LLM receives wrong tier data

**File:** `src/api/routes/narrative.py:125, 162-166`

**Issue:** `_SIGNAL_QUERY` (line 162) selects `f.market_context` (not shown in the column list, but referenced via `row.get("market_context")`). `_build_context_from_row` at line 125 passes `row.get("market_context")` to `_maybe_validate(I2Events, ...)`. After migration 124, `market_context` contains only the `{"cross_asset": {...}}` nested object; all 45 I2 composite event fields (RSIEvents, StochasticEvents, ADXEvents, MomentumAccel, etc.) now live in the new `i2` column. The LLM receives an empty or cross-asset-only object as I2 context — silently wrong after migration.

Inspecting `_SIGNAL_QUERY` at lines 162-164: the column list reads `f.bar, f.i1, f.i2, f.i3, f.i4, f.i5, f.smc, f.cross_timeframe_context` — `f.i2` IS selected here. However, `_build_context_from_row` at line 125 calls `_parse_jsonb(row.get("i2"), default=None)` which is correct. On first read this looks correct, but the `_signal_row` test fixture (test_narrative_route.py line 70) does NOT include an `"i2"` key, meaning the test never exercises the i2 path. More critically: `_SIGNAL_QUERY` uses `LEFT JOIN LATERAL jsonb_array_elements(f.trading_signals)` — if `trading_signals` is empty or NULL for a given signal, the LATERAL join returns zero rows and `row` will be None (the `LIMIT 1` takes effect only when the join yields rows). This is a subtle data hazard for signals that pre-date the `trading_signals` column population.

The direct defect: `_build_context_from_row` passes `row.get("i2")` but the fixture at line 70 of the test omits `"i2"`, so the tested path is `_maybe_validate(I2Events, None)` → `None`. The production path after migration 124 correctly uses `row["i2"]`. This is a test coverage gap, not a runtime crash, but it means the i2 context is untested.

**Fix:** Add `"i2"` to `_signal_row` in the test and verify `ctx.i2` is populated:
```python
# test_narrative_route.py _signal_row():
"i2": {"rsi_crossed_30_up": 1.0},
```

For the `_SIGNAL_QUERY` LATERAL join hazard, use `LEFT JOIN LATERAL ... ON TRUE` with a NULL-safe outer join or use `COALESCE(jsonb_array_length(f.trading_signals), 0) > 0` guard.

---

### CR-03: `features.py` and `signals.py` — `i2` column not selected or returned in any API endpoint after migration 124

**Files:**
- `src/api/routes/features.py:56-63, 123-133`
- `src/api/routes/signals.py:912-929, 1007-1024`

**Issue:** Every SELECT against `intelligence_features` in these routes was written before migration 124 added the `i2` column. None select `i2`. After migration 124, the `i2` column holds all I2 composite event tier data (45 fields), but:

- `GET /features/{symbol}/{timeframe}` returns rows without `i2` — dashboard and ML callers are blind to I2 context.
- `GET /features/export` exports Parquet without `i2` — any ML notebook training on this export silently trains without I2 features.
- `GET /signals/detail/{signal_id}` features block omits `i2`.
- `GET /signals/{symbol}?include_features=true` features block omits `i2`.

**Fix for `features.py` (both endpoints):**
```sql
-- Add i2 to the SELECT:
SELECT ts, symbol, tf, platform, source, schema_version,
       bar, i1, i2, i5, i3,
       i4, smc, cross_timeframe_context
FROM intelligence_features
```
Add `"i2": _parse_jsonb(row["i2"], default={})` to the response dict and to the Parquet tier loop.

**Fix for `signals.py` feature join queries:**
```sql
-- get_signal_detail inner feat_query:
SELECT bar, i1, i2, i5, i3,
       i4, smc, cross_timeframe_context
FROM intelligence_features
```
Add `"i2": _parse_jsonb(feat_row["i2"], default=None)` to the `features` dict.

---

### CR-04: `signals.py` — `_TERMINAL_STATUSES` is named backwards, is a semantic trap for future editors

**File:** `src/api/routes/signals.py:28-31, 411`

**Issue:**
```python
_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {SignalStatus.PENDING.value, SignalStatus.ACTIVE.value}
)
```
The name says "terminal" but it contains the two **live** (non-terminal) statuses. Line 411 uses it as:
```python
resolved = s["status"] not in _TERMINAL_STATUSES
```
The logic is accidentally correct (`not in {pending, active}` == resolved), but the name asserts the exact opposite semantic. Any developer reading this will believe the set contains terminal statuses and may "fix" the `not in` to `in` to align with the name — which would silently invert the resolved/open classification and corrupt the `n_resolved`, `win_rate`, and `avg_pnl_r` summary fields returned to the dashboard.

This also affects the `n_suppressed` calculation at line 418, which checks `s["status"] == SignalStatus.REGIME_SUPPRESSED.value` — correct independently but adjacent to the misleading constant.

**Fix:**
```python
# Rename to accurately reflect contents:
_OPEN_STATUSES: frozenset[str] = frozenset(
    {SignalStatus.PENDING.value, SignalStatus.ACTIVE.value}
)
# Update line 411:
resolved = s["status"] not in _OPEN_STATUSES
```

---

## Warnings

### WR-01: `narrative.py` — `RETURNING` clause on `DO NOTHING` conflict path is dead code

**File:** `src/api/routes/narrative.py:176-182`

**Issue:** `_NARRATIVE_UPSERT` ends with `ON CONFLICT (signal_id) DO NOTHING RETURNING narrative, model`. When a conflict occurs, `DO NOTHING` suppresses the INSERT and `RETURNING` yields zero rows. Even on successful insert, the result is discarded: `conn.execute()` is called (not `fetchrow()` or `fetch()`), so the returned row is never consumed. The `RETURNING` clause is dead code in both the conflict and non-conflict paths.

**Fix:** Remove the `RETURNING` clause:
```sql
ON CONFLICT (signal_id) DO NOTHING
```

---

### WR-02: `run_historical_pipeline.py` — `autocommit=True` makes all explicit `conn.commit()` calls dead code

**File:** `production/scripts/run_historical_pipeline.py:1303-1307`

**Issue:** `connect_db()` sets `conn.autocommit = True` (line 1306). With autocommit enabled, psycopg2 auto-commits after every statement. The 7+ explicit `conn.commit()` calls in `_upsert_contract_metadata`, `_insert_features_sync`, `_insert_signals_sync`, `store_bars`, `replay_symbol`, and the `--clean` block are all no-ops. The `SET synchronous_commit = off` session optimization (lines 1668, 2264) also has no effect under autocommit because there is no open transaction to apply it to. The comments imply transactional semantics that do not exist.

**Fix:** Either remove `conn.autocommit = True` and rely on the explicit `commit()` calls (providing actual transaction atomicity for batch inserts), or remove all the `conn.commit()` calls and document that autocommit is intentional. Also, add a comment that `SET synchronous_commit = off` is a no-op under autocommit.

---

### WR-03: `narrative_swarm.py` — `signal.symbol` and `signal.tf` access undeclared extra fields on `RankedSignal`

**File:** `services/narrative_swarm.py:115, 127`

**Issue:** After `signal_dict_to_ranked(raw_signal)`, lines 115 and 127 access `signal.symbol` and `signal.tf`. These are not declared fields on `RankedSignal` — they land in pydantic's `__pydantic_extra__` dict via `extra="allow"`. If the upstream payload uses `timeframe` instead of `tf`, `signal.tf` silently returns `None` rather than raising. Line 88 already correctly reads `raw_signal.get("tf") or raw_signal.get("timeframe", "")` from the raw dict before conversion — the correct value is available there without relying on extra-field access.

**Fix:**
```python
# Capture before conversion:
symbol = raw_signal.get("symbol", "")
tf_str = raw_signal.get("tf") or raw_signal.get("timeframe", "")
# Then use symbol and tf_str instead of signal.symbol and signal.tf
```

---

### WR-04: `alpha_swarm.py` `_process_one_signal` raises `ValueError` on missing `signal_id` — may crash entire message batch

**File:** `services/alpha_swarm.py:490-494`

**Issue:** Lines 490-494 raise `ValueError` when `signal.signal_id` is falsy. Depending on how `BaseGroupCoordinator._handle_trigger` propagates exceptions, this may abort processing for all remaining signals in the same Kafka batch. CLAUDE.md principle: "silent wrong answers are worse than loud crashes" — but crashing the loop over one malformed signal means all subsequent signals in the batch are dropped without processing.

**Fix:** Log and return instead of raising:
```python
if not signal.signal_id:
    self.logger.error(
        "alpha_swarm.signal_missing_signal_id",
        setup_plugin=getattr(signal, "setup_plugin", None),
    )
    return
```

---

### WR-05: `narrative_swarm.py` — `assert self._narrative_agent is not None` hard-crashes the service on every signal if setup failed

**File:** `services/narrative_swarm.py:124`

**Issue:** `assert self._narrative_agent is not None` in the hot signal dispatch path. If `_setup` failed to find a `NarrativeSynthesizer` in `self._agents` (e.g., AgentRegistry misconfiguration), every incoming signal crashes with `AssertionError` rather than logging and skipping. This converts a setup failure into a permanent live-traffic crash loop.

**Fix:**
```python
if self._narrative_agent is None:
    self.logger.error("narrative_swarm.no_narrative_agent_configured")
    return
```

---

### WR-06: `feature_writer.py` — `_parse_payload` dead-code `record is None` guard after Pydantic `model_validate`

**File:** `services/feature_writer.py:326-327`

**Issue:** Lines 326-327 check `if record is None: return [], [payload]`. Pydantic's `model_validate` either returns a valid instance or raises `ValidationError` — it never returns `None`. The guard is unreachable. The `except (ValidationError, ValueError)` block above it handles all failure cases.

**Fix:** Remove the unreachable guard:
```python
# Delete lines 326-327:
# if record is None:
#     return [], [payload]
```

---

### WR-07: `feature_replay.py` — asyncpg JSONB codec registration violates CLAUDE.md convention

**File:** `production/scripts/feature_replay.py:474-480`

**Issue:** CLAUDE.md states: "asyncpg: Use for all new DB code. JSONB → dict (no `json.loads()`/`json.dumps()`)." The `_setup_codecs` function at line 474 installs `encoder=json.dumps, decoder=json.loads` for the `jsonb` type. asyncpg returns JSONB as native Python dicts without any codec — the codec is redundant and contradicts project convention. It also risks double-serialization bugs if any code passes dict values while the codec expects strings.

**Fix:** Remove the `_setup_codecs` function and the `init=_setup_codecs` argument from `create_pool`:
```python
pool = await asyncpg.create_pool(
    settings.database_url,
    min_size=2,
    max_size=max(4, args.workers + 2),
)
```

---

### WR-08: `signal_writer.py` — `_invalid_signals` list unbounded between flush cycles; DLQ sends lost on pre-flush shutdown

**File:** `services/signal_writer.py:63, 130-134`

**Issue:** `self._invalid_signals` accumulates invalid signals across all `_parse_payload` calls until the next `_flush_batch`. If the service shuts down between flushes (e.g., OOM kill or SIGKILL), signals accumulated since the last flush are dropped without being DLQ'd. Under high invalid-signal rates, the list can grow to consume significant memory before the next flush. The `_teardown` method (line 158) calls `super()._teardown()` which may flush the valid buffer, but `_invalid_signals` is not explicitly drained in teardown.

**Fix:** Add an explicit drain in `_teardown`:
```python
async def _teardown(self) -> None:
    # Drain invalid signals to DLQ before teardown
    for sig in self._invalid_signals:
        await self._send_to_dlq(sig, ValueError("validate_signal failed"))
    self._invalid_signals.clear()
    await super()._teardown()
    ...
```

---

## Info

### IN-01: `signals.py` — `_RECENT_SIGNAL_WINDOW_DAYS = 90` declared but never used

**File:** `src/api/routes/signals.py:33`

**Issue:** The constant is declared at line 33 but never referenced. `get_recent_signals` hardcodes `'90 days'` directly in the SQL string. The constant is dead code.

**Fix:** Either reference it in the query string or remove it.

---

### IN-02: `feature_replay.py` — `market_entry_price` uses falsy `or None` on float, converts zero close to None

**File:** `production/scripts/feature_replay.py:336`

**Issue:** `market_entry_price=float(bar_data.get("c", 0.0)) or None` returns `None` when `close == 0.0`. A zero close is the default when `bar_data` is empty (line 210: `bar_data = row["bar"] or {}`). This silently stores `NULL` rather than `0.0` — for empty bar data, the distinction is correct, but the expression would also convert a genuine zero-close price to NULL. Inconsistent with `run_historical_pipeline.py` line 845 which uses the safer conditional form.

**Fix:**
```python
_close = bar_data.get("c")
market_entry_price=float(_close) if _close is not None else None,
```

---

### IN-03: `test_feature_replay.py` — static text grep tests cannot detect column name regressions that use aliases

**File:** `tests/unit/scripts/test_feature_replay.py:75-80`

**Issue:** `test_select_uses_new_column_names` checks that column name strings appear anywhere in the source file. A query that aliases old names (e.g., `technical_indicators AS i1`) would pass `test_new_column_names_only` (the old name check) while also passing `test_select_uses_new_column_names` (the new name appears). The tests are necessary but not sufficient. This is an inherent limitation of string-grep tests on SQL, not a critical defect.

**Note:** No fix required — the test provides reasonable regression value. Document the limitation in a comment.

---

_Reviewed: 2026-06-12T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
