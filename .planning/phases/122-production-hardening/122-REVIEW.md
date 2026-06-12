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
  critical: 3
  warning: 4
  info: 3
  total: 10
status: issues_found
---

# Phase 122: Code Review Report

**Reviewed:** 2026-06-12
**Depth:** standard
**Files Reviewed:** 21
**Status:** issues_found

## Summary

Phase 122 adds the i2 column (migration 124), renames legacy tier columns (migration 125), introduces `feature_replay.py` for I7-only replay, and wires i2 data into both the historical pipeline and the live feature writer. The migrations and schema change are clean. Three blockers were found: one renders `feature_replay.py` completely non-functional (every row silently fails reconstruction); one means the narrative route feeds stale/wrong i2 data to the LLM after the migration; one is a misnamed sentinel that inverts a critical status filter. Four warnings cover dead RETURNING clause, missing i2 exposure in the features API, autocommit/explicit-commit dualism, and a fragile undeclared-field access in narrative_swarm.

---

## Critical Issues

### CR-01: `feature_replay.py` — `source="feature_replay"` violates `IntelligenceEvent` literal and silently zeros all output

**File:** `production/scripts/feature_replay.py:148`

**Issue:** `_reconstruct_intelligence_event` constructs an `IntelligenceEvent` with `source="feature_replay"`. The schema declares `source: Literal["live", "backfill"]` (schemas.py:879), so pydantic raises `ValidationError` on every row. The enclosing `try/except Exception` catches it, logs a warning, and returns `None`. The calling loop skips `None` rows. Net result: every single feature row fails reconstruction, `raw_signals` is always empty, and `feature_replay.py` writes zero signals regardless of `--dry-run` flag or plugin list. The script appears to complete successfully (no crash) while producing no output.

**Fix:**
```python
# Change line 148:
source="backfill",  # was "feature_replay" — not a valid Literal value
```

---

### CR-02: `narrative.py` — reads `market_context` instead of `i2` after migration 124

**File:** `src/api/routes/narrative.py:125` and `:163`

**Issue:** `_SIGNAL_QUERY` at line 163 selects `f.market_context` from `intelligence_features`. `_build_context_from_row` at line 125 maps this to `i2`:
```python
i2=_maybe_validate(I2Events, _parse_jsonb(row.get("market_context"), default=None)),
```
After migration 124 applies, `market_context` contains only `{"cross_asset": {...}}` (the cross-asset object). All I2 composite event fields (RSIEvents, StochasticEvents, ADXEvents, etc.) now live in the new `i2` column. The LLM receives an empty or cross-asset-only I2 tier instead of the 45-field composite event context. Narratives will silently lack I2 signal context post-migration.

**Fix:**
```python
# In _SIGNAL_QUERY (line 163), replace f.market_context with f.i2:
f.bar, f.i1, f.i2, f.i3,
f.i4, f.i5, f.smc, f.cross_timeframe_context

# In _build_context_from_row (line 125), read from i2:
i2=_maybe_validate(I2Events, _parse_jsonb(row.get("i2"), default=None)),
```

---

### CR-03: `signals.py` — `_TERMINAL_STATUSES` is named exactly backwards, inverts the resolved/open logic

**File:** `src/api/routes/signals.py:28-31` and `:411`

**Issue:** The variable is named `_TERMINAL_STATUSES` but contains the two **non-terminal** (open) statuses:
```python
_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {SignalStatus.PENDING.value, SignalStatus.ACTIVE.value}
)
```
Line 411 uses it as:
```python
resolved = s["status"] not in _TERMINAL_STATUSES
```
The logic is accidentally correct (`not in {pending, active}` == resolved), but the name asserts the opposite semantic. Anyone reading this code — or modifying it — will immediately misread the intent and could introduce a real inversion bug by "fixing" the backwards name. This is a logic-invariant naming error that is one refactor away from data corruption in the summary statistics.

**Fix:**
```python
# Rename to accurately reflect the contents:
_OPEN_STATUSES: frozenset[str] = frozenset(
    {SignalStatus.PENDING.value, SignalStatus.ACTIVE.value}
)
# And update line 411:
resolved = s["status"] not in _OPEN_STATUSES
```

---

## Warnings

### WR-01: `narrative.py` — `RETURNING` clause on `DO NOTHING` conflict path is dead code

**File:** `src/api/routes/narrative.py:176-182`

**Issue:** `_NARRATIVE_UPSERT` ends with `ON CONFLICT (signal_id) DO NOTHING RETURNING narrative, model`. When a conflict occurs, `DO NOTHING` suppresses the insert and `RETURNING` yields zero rows. Even on successful insert, the result is discarded: `conn.execute()` is called (not `fetchrow()`), so the returned row is never read. The `RETURNING` clause is entirely dead.

On a concurrent double-request to the same signal: both requests succeed (generate narrative, call LLM), the second INSERT is silently no-op'd, and both callers return the locally-computed narrative. This is benign but wastes one LLM call.

**Fix:**
```python
_NARRATIVE_UPSERT = """
    INSERT INTO signal_narratives (signal_id, symbol, timeframe, narrative, model,
                                   agent_id, prompt_version, prompt_hash, latency_ms)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
    ON CONFLICT (signal_id) DO NOTHING
"""
```
Remove the `RETURNING` clause since it is never consumed.

---

### WR-02: `features.py` — `i2` column not exposed in any API response or export after migration 124

**File:** `src/api/routes/features.py:53-64` and `:123-133`

**Issue:** Both `GET /features/{symbol}/{timeframe}` and `GET /features/export` SELECT from `intelligence_features` without including the `i2` column. The column was added in migration 124 as a dedicated I2 tier. Neither endpoint returns it. Dashboard or ML callers fetching feature rows get stale/incomplete tier data.

**Fix for GET /features/{symbol}/{timeframe} query (line 123):**
```sql
SELECT ts, symbol, tf, platform, source, schema_version,
       bar, i1, i2, i5, i3,
       i4, smc, cross_timeframe_context
FROM intelligence_features
```
Add `"i2": _parse_jsonb(row["i2"], default={})` to the response dict at line 148.

**Fix for export query (line 53) and tier loop (line 75-87):**
Add `("i2", "i2")` to the tier/col mapping list so the column is expanded into the Parquet output.

---

### WR-03: `run_historical_pipeline.py` — autocommit=True makes all explicit `conn.commit()` calls dead code

**File:** `production/scripts/run_historical_pipeline.py:1303-1306`

**Issue:** `connect_db()` sets `conn.autocommit = True` (line 1306). With autocommit enabled, psycopg2 auto-commits after every statement — explicit `conn.commit()` calls are no-ops. There are 7 explicit `conn.commit()` calls across `_upsert_contract_metadata`, `_insert_features_sync`, `_insert_signals_sync`, `store_bars`, and `replay_symbol`. These are not bugs (data is committed), but they are dead code that misleads the reader about transaction boundaries, and they interfere with the `SET synchronous_commit = off` optimization at lines 1668/2264 — that session-level SET only holds for the current transaction, but autocommit=True means there is no current transaction.

**Fix:** Either switch to autocommit=False and rely on the explicit commits (adds proper transaction atomicity to batch inserts), or remove all the explicit `conn.commit()` calls and document that autocommit mode is intentional. The `SET synchronous_commit = off` line should be noted as having no effect under autocommit=True.

---

### WR-04: `narrative_swarm.py` — `signal.symbol` and `signal.tf` access undeclared fields on `RankedSignal`

**File:** `services/narrative_swarm.py:115` and `:127`

**Issue:** After `signal_dict_to_ranked(raw_signal)`, lines 115 and 127 access `signal.symbol` and `signal.tf`. These fields are NOT declared on `RankedSignal` (schemas.py:916-934). They are only present if the raw signal dict included `symbol` and `tf` keys, which then land in pydantic's `__pydantic_extra__` via `extra="allow"`. The access works at runtime only because pydantic forwards attribute lookups to the extra dict, but:
1. This is undocumented behavior that silences typos — if the upstream payload uses `timeframe` instead of `tf`, `signal.tf` returns `None` rather than raising.
2. Line 88 already reads `raw_signal.get("tf") or raw_signal.get("timeframe", "")` from the raw dict before converting — it has the `tf` value before calling `signal_dict_to_ranked`. Using the raw dict directly avoids the undeclared access.

**Fix:**
```python
# Extract symbol/tf from raw_signal before converting (they're already available):
symbol = raw_signal.get("symbol", "")
tf = raw_signal.get("tf") or raw_signal.get("timeframe", "")
# ... then use local variables instead of signal.symbol / signal.tf
```

---

## Info

### IN-01: `signals.py` — `_RECENT_SIGNAL_WINDOW_DAYS` constant declared but never used

**File:** `src/api/routes/signals.py:33`

**Issue:** `_RECENT_SIGNAL_WINDOW_DAYS = 90` is declared at module level but never referenced. The `get_recent_signals` query hardcodes `'90 days'` in the SQL string.

**Fix:** Either use the constant in the SQL query (`f"... WHERE sl.timestamp >= NOW() - INTERVAL '{_RECENT_SIGNAL_WINDOW_DAYS} days'"`) or remove the unused constant.

---

### IN-02: `narrative.py` — `_HASH_TIERS` comment references non-pipeline Tier members that may not exist

**File:** `src/api/routes/narrative.py:48`

**Issue:** `_HASH_TIERS = tuple(t.value for t in _Tier if t.value not in ("bar", "i7"))` — the comment says "excludes non-pipeline Tier members" but the filter only excludes `"bar"` and `"i7"`. This is fine as long as `Tier` doesn't add members whose `.value` shouldn't be hashed. Minor documentation gap.

**Fix:** No code change needed, but add a comment listing the explicitly excluded values for future readers.

---

### IN-03: `feature_replay.py` — `market_entry_price` uses `or None` falsy pattern on a float

**File:** `production/scripts/feature_replay.py:336`

**Issue:** `market_entry_price=float(bar_data.get("c", 0.0)) or None` uses the Python `or` idiom on a float. This returns `None` when `close == 0.0`. A zero close price is theoretically impossible for real market data but is the default when `bar_data` is empty. The `run_historical_pipeline.py` equivalent at line 845 uses the correct conditional form: `bar_close = float(last_bar["close"]) if last_bar else None`. More importantly, the whole expression `float(bar_data.get("c", 0.0)) or None` returns `None` when close is exactly `0.0` — in practice this is never a real price, but the pattern is confusing and inconsistent with the rest of the codebase.

**Fix:**
```python
# Replace:
market_entry_price=float(bar_data.get("c", 0.0)) or None,
# With:
_close = bar_data.get("c")
market_entry_price=float(_close) if _close is not None else None,
```

---

_Reviewed: 2026-06-12_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
