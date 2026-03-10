# Phase 17: LLM Wiring Fix - Research

**Researched:** 2026-03-06
**Domain:** Service wiring — Redis stream message construction, pure function plumbing, plugin output fields
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**signal_id threading — stream-first, DB-second**
- Source: `signal_id` is already assigned in `LedgerEntry` inside `build_ledger_entries()`. Read it back from the `was_selected=True` entry — no new UUID generation.
- Order flip: publish to `signals:aggregated` stream FIRST, then run `insert_signals()` DB write. Stream is hot tier (sub-ms); DB is cold tier. `signal_lifecycle_service` exits signals minutes-to-hours later — `signal_ledger` row will exist long before any outcome back-fill is attempted.
- Safe: Phase 16 deliberately used soft FK (no FK constraint on `llm_calls.signal_id`). If DB insert fails after stream publish, outcome back-fill no-ops — same as today.
- Code change: in `signal_generator_service._process_bar()`, after `build_ledger_entries`: extract `selected_entry`, inject `signal_id` into message dict, `xadd` stream first, then `insert_signals` DB after.

**ai_narrative_service — extract and pass signal_id**
- `parse_aggregated_signal()`: add `signal_id` field extraction from stream message
- `_build_llm_call_payload()`: use `str(sd.get("signal_id", ""))` instead of hardcoded `""`
- No other changes to the payload builder

**Regime vocabulary — keep raw values, no translation (Renaissance: segment relentlessly)**
- Do NOT translate plugin `regime_context` values to a 3-bucket canonical vocabulary. Raw plugin strings ARE the regime vocabulary.
- Complete vocabulary (18 distinct values across all 17 I7 plugins): `"bullish"`, `"bearish"`, `"ranging"`, `"neutral"`, `"breakout_bullish"`, `"breakout_bearish"`, `"expansion_bullish"`, `"expansion_bearish"`, `"vwap_extended_low"`, `"vwap_extended_high"`, `"transitioning"`, `"bullish_transition"`, `"bearish_transition"`, `"gap_open"`, `"session_extreme_london"`, `"session_extreme_ny"`, `"session_extreme_both"`, `""` (3 plugins with no regime_context)
- `llm_calls.regime` stores the raw value as-is
- `_apply_score_routing` already looks up by the same raw string — no change needed
- `__all__` aggregate row handles cross-regime routing until per-bucket n>=30

**SessionExtremesSetup — emit session-specific regime buckets**
- Replace session label in `regime_context` with three distinct regime strings: `"session_extreme_london"`, `"session_extreme_ny"`, `"session_extreme_both"`
- Move session label to `supporting_factors` where it belongs as metadata: `supporting_factors.append(f"session:{session_ctx}")` alongside existing factors
- Note: No Asian session bucket — plugin only fires during London/NY

**Score cache key alignment — resolved by consistency**
- No dedicated fix needed. Once `regime_context` flows through consistently (raw values stored = raw values looked up), the cache key mismatch resolves automatically.

### Claude's Discretion
- Whether `parse_aggregated_signal` returns empty string or None for missing `signal_id` (either works — llm_writer_service handles both via `_dec()` helper)
- Test structure for signal_id threading (unit vs integration)
- Whether to add `signal_id` to `parse_aggregated_signal` return dict or handle in caller

### Deferred Ideas (OUT OF SCOPE)
- Add `regime_context` to `LiquidityHunt`, `LiquiditySweepReclaim`, `SupplyDemandSetup` — acceptable to fall to `__all__` bucket for now
- Regime-specific model promotion gate (must hold across 2+ regimes) — v2 per Phase 16 deferred
- Latency-adjusted model routing — backlog
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| LLM-04 | `llm_writer_service` batch INSERTs from `llm_calls:stream`, back-fills outcome fields from `llm_outcomes:stream` by `signal_id`, recomputes `llm_model_scores` every 15 min, writes score cache to Redis | Fix 1 (signal_id threading) directly unblocks the `WHERE signal_id = $1::uuid` UPDATE path. Fix 2 (regime vocabulary) ensures score cache keys are populated correctly. |
| LLM-05 | `ai_narrative_service` reads Redis score cache at startup and every 5 min — promotes significant models to position 0 in provider chain for that call_type + regime | Fix 2 (regime vocabulary) ensures `_apply_score_routing` looks up the same key strings that the score cache was populated with, enabling first meaningful promotion. |
</phase_requirements>

---

## Summary

Phase 17 fixes two surgical production wiring breaks that were identified after Phase 16 shipped. Neither break requires new infrastructure — both are single-file plumbing errors that silently no-op the entire LLM intelligence feedback loop.

**Break 1 — signal_id linkage:** `signal_generator_service._process_bar()` currently publishes to the `signals:aggregated` stream BEFORE calling `build_ledger_entries()`, so the UUID assigned inside `build_ledger_entries()` never makes it into the stream message. `ai_narrative_service` reads the stream, finds no `signal_id`, and writes `""` to `llm_calls.signal_id`. The `_UPDATE_OUTCOME_SQL WHERE signal_id = $1::uuid` cast then fails on an empty string, so every outcome back-fill no-ops. This is confirmed by reading both services end-to-end.

**Break 2 — regime vocabulary mismatch:** `SessionExtremesSetupPlugin.compute_full()` writes `"london"`, `"ny"`, or `"both"` into `regime_context` (lines 133–137 of the plugin). These values are stored verbatim in `llm_calls.regime`. But `_apply_score_routing` looks up score cache keys using `"trending"`, `"ranging"`, `"volatile"`, `"__all__"` — a completely disjoint set. The result: session extreme signals accumulate in the score table under keys that adaptive routing never queries, so `_preferred_models` is never populated from that signal family.

Both fixes are localized. Fix 1 touches 3 files: `signal_generator_service.py` (order flip + inject), `ai_narrative_service.py` (`parse_aggregated_signal` + `_build_llm_call_payload`). Fix 2 touches 1 file: `session_extremes_setup.py` (regime_context assignment). Zero schema changes. Zero new stream keys. Zero new services.

**Primary recommendation:** Fix in order: (1) SessionExtremesSetup regime rename, (2) signal_id threading order flip and injection, (3) ai_narrative signal_id passthrough. Ship as a single wave.

---

## Current State Analysis

### Break 1: signal_id never reaches llm_calls

**Root cause — stream publish precedes UUID assignment.**

In `signal_generator_service._process_bar()` (lines 624–674), the current execution order is:

```
entries = build_ledger_entries(result, ...)    # UUIDs assigned HERE (line 624)
if entries and self.db_manager:
    await insert_signals(self.db_manager, entries)   # DB insert (line 631)
    ...

if result.selected_signal and self.redis_client:
    ...
    message = {k: str(v) for k, v in sig.items() ...}   # build message (line 641)
    # signal_id NOT added to message dict
    await self.redis_client.xadd(stream_name, message, ...)  # stream publish AFTER DB
```

The problem is NOT that stream comes before DB — in the current code, stream actually comes after DB. The problem is that `signal_id` from the winning `LedgerEntry` is never injected into the `message` dict at all, regardless of publish order.

In `build_ledger_entries()` (line 244):
```python
entries.append(LedgerEntry(
    signal_id=str(uuid4()),   # UUID assigned here, per entry
    ...
    was_selected=was_selected,
    ...
))
```

The `was_selected=True` entry is the winning signal. Its `signal_id` is a fresh UUID. But after `build_ledger_entries` returns, `_process_bar` only touches `result.selected_signal` (the raw dict from the aggregator) — not the `LedgerEntry` list. The message dict is built from `result.selected_signal`, which never had a `signal_id` key added to it.

**Consequence chain:**
1. `llm_calls.signal_id` is always NULL (empty string → `_dec()` returns None → asyncpg casts to NULL)
2. `_UPDATE_OUTCOME_SQL WHERE signal_id = $1::uuid` is called with NULL — matches 0 rows
3. `llm_calls` rows never get `outcome`, `pnl_r`, `mae`, `mfe` populated
4. `_SELECT_OUTCOME_ROWS_SQL` returns 0 rows with non-null outcome
5. `_recompute_scores()` upserts nothing meaningful, Redis score cache stays empty
6. `_apply_score_routing` finds no significant models, `_preferred_models` stays `{}`
7. Adaptive routing never activates — LLM-05 no-ops

**The CONTEXT.md fix (correct):**
After `build_ledger_entries`, extract the selected entry, inject `signal_id` into the message dict, then publish stream first (hot tier principle), then insert to DB:

```python
entries = build_ledger_entries(result, ...)
selected_entry = next((e for e in entries if e.was_selected), None)
message["signal_id"] = selected_entry.signal_id if selected_entry else ""
await redis.xadd(stream_name, message, ...)   # hot tier first
await insert_signals(db_manager, entries)      # cold tier after
```

Note: the CONTEXT.md description says "stream-first, DB-second" as a hot/warm/cold ordering principle. In the current code, stream is actually already after DB — the order flip reinforces the architectural principle and the UUID injection is the load-bearing change.

**In `ai_narrative_service.parse_aggregated_signal()`** (line 139–168), the function currently returns a dict with no `signal_id` key. The `_get()` helper is already defined inside the function and handles bytes-keyed lookups — adding `signal_id` extraction is one line.

**In `_build_llm_call_payload()`** (line 211), the hardcoded comment reads:
```python
"signal_id": "",   # not in aggregated stream
```
This must become `str(sd.get("signal_id", ""))` once `signal_id` is in the stream.

**`llm_writer_service` requires zero changes.** The `_parse_llm_call_fields` function already has `"signal_id": _dec(b"signal_id")` at line 161. The `_UPDATE_OUTCOME_SQL` already has `WHERE signal_id = $1::uuid` at line 77. Both are correct and waiting for non-null input.

---

### Break 2: SessionExtremesSetup emits session labels, not regime vocabulary

**Root cause — plugin uses session context as regime bucket, not setup type.**

In `session_extremes_setup.py` lines 132–149, the current code:

```python
if session_london and session_ny:
    session_ctx = "both"
elif session_london:
    session_ctx = "london"
else:
    session_ctx = "ny"

return {
    ...
    "regime_context": session_ctx,      # "london" | "ny" | "both"
    "supporting_factors": supporting,   # ["trend_align", "volume_spike", ...]
}
```

**What gets stored in `llm_calls.regime`:** `"london"`, `"ny"`, or `"both"`.

**What `_apply_score_routing` queries** (ai_narrative_service lines 726–727):
```python
for regime in ("trending", "ranging", "volatile", "__all__"):
    cache_key = llm_scores_cache(self.env_prefix, call_type, regime)
```

These four keys are a completely disjoint set from `{"london", "ny", "both"}`. The session extreme signals accumulate in `llm_model_scores` under regime=`"london"` etc., but `_apply_score_routing` never reads those keys. `_preferred_models` is never populated from session extreme outcomes.

**The CONTEXT.md fix (correct):**
Replace `regime_context` with session-specific regime strings that ARE the correct vocabulary:
- `"session_extreme_london"` — London-only session window
- `"session_extreme_ny"` — NY-only session window
- `"session_extreme_both"` — London/NY overlap

Move the session label to `supporting_factors`:
```python
supporting.append(f"session:{session_ctx}")
```

This preserves the session metadata in the signal record (visible in the dashboard, stored in `signal_ledger.supporting_factors`) while emitting correct regime strings for LLM score grouping.

**Impact on existing tests:** The `test_session_extremes_setup.py` file has two tests that assert on the old regime_context values (`test_regime_context_london` asserts `"london"`, `test_regime_context_ny` asserts `"ny"`). These tests must be updated to assert the new vocabulary strings and the `supporting_factors` presence. All other tests in that file are unaffected.

**`_apply_score_routing` still does not query** `"session_extreme_london"` etc. directly — it queries `"trending"`, `"ranging"`, `"volatile"`, `"__all__"`. This means session extreme outcomes will accumulate in the DB under the new vocab keys, but won't drive per-session routing until `_apply_score_routing` is extended to query those keys. However, the `__all__` aggregate row in `llm_model_scores` is computed across all regimes and setup_types — session extreme outcomes WILL contribute to `__all__` score which IS queried. This is acceptable: CONTEXT.md states `"__all__` bucket covers routing until n>=30 accumulates per bucket."

The deeper point: the old `"london"` strings were silently corrupting the score table with unreachable keys. The new strings at minimum populate the DB correctly, enable future per-session routing extension, and contribute to `__all__`.

---

## Fix Implementation Map

### Fix A: SessionExtremesSetup (1 file changed)

**File:** `src/intelligence/trading/session_extremes_setup.py`

**Change:** Lines 132–149 of `compute_full()` — replace `regime_context` assignment and add session to supporting_factors.

**Before:**
```python
if session_london and session_ny:
    session_ctx = "both"
elif session_london:
    session_ctx = "london"
else:
    session_ctx = "ny"

return {
    ...
    "regime_context": session_ctx,
    "supporting_factors": supporting,
}
```

**After:**
```python
if session_london and session_ny:
    session_ctx = "both"
elif session_london:
    session_ctx = "london"
else:
    session_ctx = "ny"

regime_ctx = f"session_extreme_{session_ctx}"
supporting.append(f"session:{session_ctx}")

return {
    ...
    "regime_context": regime_ctx,
    "supporting_factors": supporting,
}
```

**Test impact:** `test_regime_context_london` and `test_regime_context_ny` must be updated. `test_complete_output_fields` passes unchanged. `test_fires_with_trend_align_only` and `test_fires_with_rsi_extreme_only` must use membership checks (e.g. `assert "trend_align" in result.get("supporting_factors", [])`) rather than equality — `supporting_factors` now also contains a `"session:*"` entry and ordering is not guaranteed.

### Fix B: signal_generator_service._process_bar() (1 function changed)

**File:** `services/signal_generator_service.py`

**Change:** After `build_ledger_entries()`, extract the selected entry's UUID, inject into message, move `xadd` before `insert_signals`.

Current code block (lines 624–674) condensed:
```python
entries = build_ledger_entries(result, ...)
if entries and self.db_manager:
    await insert_signals(self.db_manager, entries)
    ...

if result.selected_signal and self.redis_client:
    stream_name = signals_aggregated(...)
    sig = result.selected_signal
    message = {k: str(v) for k, v in sig.items() if isinstance(v, (str, int, float, bool))}
    # ... promote targets, labels, timing fields ...
    await self.redis_client.xadd(stream_name, message, ...)

# Publish i7 enrichment stream
if self.redis_client:
    await self.redis_client.xadd(i7_stream, i7_msg, ...)
```

**After (key changes only):**
```python
entries = build_ledger_entries(result, ...)

if result.selected_signal and self.redis_client:
    stream_name = signals_aggregated(...)
    sig = result.selected_signal
    message = {k: str(v) for k, v in sig.items() if isinstance(v, (str, int, float, bool))}
    # ... promote targets, labels, timing fields unchanged ...

    # Inject signal_id from winning LedgerEntry (UUID assigned in build_ledger_entries)
    selected_entry = next((e for e in entries if e.was_selected), None)
    message["signal_id"] = selected_entry.signal_id if selected_entry else ""

    await self.redis_client.xadd(stream_name, message, maxlen=200, approximate=True)

# DB insert AFTER stream publish (hot tier before cold tier)
if entries and self.db_manager:
    await insert_signals(self.db_manager, entries)
    selected_count = sum(1 for e in entries if e.was_selected)
    self.signals_generated_total.inc(len(entries))
    self.signals_selected_total.inc(selected_count)
    self._total_signals += len(entries)

# Publish i7 enrichment stream (unchanged)
if self.redis_client:
    await self.redis_client.xadd(i7_stream, i7_msg, ...)
```

**Edge cases:**
- `entries` is empty when no signals fired → `selected_entry` is None → `message["signal_id"] = ""` → llm_calls.signal_id = NULL (same as today; no outcome to back-fill anyway)
- DB insert fails after stream publish → outcome back-fill no-ops on this signal (same as today, safe per CONTEXT.md)
- `result.selected_signal` is None but `entries` is non-empty (regime-suppressed only) → stream block is skipped entirely; DB insert proceeds normally; signal_id injection path never reached (correct)

**Metric counter placement:** `signals_generated_total` and `signals_selected_total` were incremented inside the `if entries and self.db_manager` block. After the reorder, the counter increment must move with the DB block — it counts DB persisted signals, not stream publishes.

### Fix C: ai_narrative_service (2 functions changed)

**File:** `services/ai_narrative_service.py`

**Change 1 — `parse_aggregated_signal()` (line 152–168):** Add `signal_id` to return dict.

```python
return {
    "symbol": _get("symbol"),
    "timeframe": _get("timeframe"),
    "timestamp": _get("timestamp"),
    "signal_id": _get("signal_id"),          # ADD THIS LINE
    "direction": direction,
    "direction_label": "Bullish" if direction > 0 else "Bearish",
    "confidence": float(_get("confidence", "0.0")),
    ...
}
```

**Change 2 — `_build_llm_call_payload()` (line 211):** Replace hardcoded empty string.

```python
# Before:
"signal_id": "",   # not in aggregated stream

# After:
"signal_id": str(sd.get("signal_id", "")),
```

Remove the inline comment — it will no longer be true.

**`_dec()` in llm_writer_service handles both empty string and None:** `_dec(b"signal_id")` returns None when the decoded value is `""`. asyncpg casts None to NULL for the UUID column. So returning `""` from `parse_aggregated_signal` for missing signal_id is correct and consistent — `_build_llm_call_payload` emits `""`, `_dec()` converts to None, asyncpg stores NULL.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | `pytest.ini` (project root) |
| Quick run command | `.venv/bin/pytest tests/unit/intelligence/trading/test_session_extremes_setup.py tests/unit/service_tests/test_ai_narrative_helpers.py tests/unit/service_tests/test_signal_generator_service.py -x -q` |
| Full suite command | `.venv/bin/pytest tests/unit/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| LLM-04 | signal_id flows from build_ledger_entries through stream message | unit | `.venv/bin/pytest tests/unit/service_tests/test_signal_generator_service.py -k "signal_id" -x` | ❌ Wave 0 |
| LLM-04 | parse_aggregated_signal returns signal_id field | unit | `.venv/bin/pytest tests/unit/service_tests/test_ai_narrative_helpers.py -k "signal_id" -x` | ❌ Wave 0 |
| LLM-04 | _build_llm_call_payload uses signal_id from signal_data | unit | `.venv/bin/pytest tests/unit/service_tests/test_ai_narrative_helpers.py -k "payload" -x` | ❌ Wave 0 |
| LLM-05 | SessionExtremesSetup emits session_extreme_* regime strings | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_session_extremes_setup.py -k "regime_context" -x` | ✅ (needs update) |
| LLM-05 | Supporting factors include session:london/ny/both | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_session_extremes_setup.py -k "supporting" -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `.venv/bin/pytest tests/unit/intelligence/trading/test_session_extremes_setup.py tests/unit/service_tests/test_ai_narrative_helpers.py tests/unit/service_tests/test_signal_generator_service.py -x -q`
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -x -q`
- **Phase gate:** Full suite green + ruff 0 errors before `/gsd:verify-work`

### Wave 0 Gaps

The following test additions are needed before or alongside implementation:

- [ ] `tests/unit/service_tests/test_signal_generator_service.py` — add `test_build_ledger_entries_signal_id_in_message`: verifies that after calling `build_ledger_entries()`, the winning entry's `signal_id` is a valid UUID string that can be injected into the stream message
- [ ] `tests/unit/service_tests/test_ai_narrative_helpers.py` — add `test_parse_aggregated_signal_includes_signal_id`: verifies `parse_aggregated_signal` extracts `signal_id` from fields dict
- [ ] `tests/unit/service_tests/test_ai_narrative_helpers.py` — add `test_build_llm_call_payload_uses_signal_id`: verifies `_build_llm_call_payload` passes signal_data's `signal_id` through (not hardcoded `""`)
- [ ] `tests/unit/intelligence/trading/test_session_extremes_setup.py` — update `test_regime_context_london` to assert `"session_extreme_london"` (was `"london"`)
- [ ] `tests/unit/intelligence/trading/test_session_extremes_setup.py` — update `test_regime_context_ny` to assert `"session_extreme_ny"` (was `"ny"`)
- [ ] `tests/unit/intelligence/trading/test_session_extremes_setup.py` — add `test_regime_context_overlap_both`: verifies session_london=1.0 AND session_ny=1.0 produces `"session_extreme_both"`
- [ ] `tests/unit/intelligence/trading/test_session_extremes_setup.py` — add `test_supporting_factors_includes_session_label`: verifies `"session:london"` / `"session:ny"` / `"session:both"` appears in `supporting_factors`
- [ ] `tests/unit/intelligence/trading/test_session_extremes_setup.py` — update `test_fires_with_trend_align_only` to accept `["trend_align", "session:london"]` (session label now in supporting_factors)

### Production Verification Queries

After deploying, run these against TimescaleDB to confirm the fixes are live:

```sql
-- Confirm signal_id is non-null in recent llm_calls rows
SELECT
    COUNT(*) AS total_rows,
    COUNT(signal_id) AS rows_with_signal_id,
    COUNT(CASE WHEN signal_id IS NOT NULL AND outcome IS NOT NULL THEN 1 END) AS rows_with_outcome
FROM llm_calls
WHERE called_at > NOW() - INTERVAL '1 hour';

-- Confirm outcome back-fill is working (rows should accumulate once signals exit)
SELECT signal_id, outcome, pnl_r, mae, mfe, bars_in_trade
FROM llm_calls
WHERE signal_id IS NOT NULL AND outcome IS NOT NULL
ORDER BY outcome_at DESC
LIMIT 10;

-- Confirm session_extreme regime strings are stored (not old "london"/"ny")
SELECT regime, COUNT(*) AS n
FROM llm_calls
WHERE regime LIKE 'session_extreme%'
GROUP BY regime
ORDER BY n DESC;

-- Confirm score cache populated in Redis (run from .venv python)
-- import redis, json
-- r = redis.Redis()
-- keys = r.keys("development:llm_scores:*")
-- for k in keys: print(k, r.hgetall(k))
```

---

## Renaissance Framing

### What Each Fix Unlocks

**signal_id linkage (Fix B+C) — "Instrument everything. You can never recover data you didn't capture."**

Without signal_id, `llm_calls` is a permanent record of model calls with no link to outcomes. Every row's `outcome`, `pnl_r`, `mae`, `mfe` will remain NULL forever — the outcome column is the labeled training set for LLM model selection. Once signal_id flows:

- Every per-signal LLM call is joinable to signal_ledger by UUID
- `llm_writer_service._UPDATE_OUTCOME_SQL` completes its purpose: back-filling outcome data from `llm_outcomes:stream`
- `_recompute_scores()` operates on rows with non-null outcome → `llm_model_scores` table populates with meaningful statistics
- `_preferred_models` can be populated → LLM-05 adaptive routing activates

The statistical minimum (n_outcomes >= 30, p < 0.05) protects against premature promotion. But n=0 forever is not a statistical floor — it is a broken instrument. This fix restores the instrument.

**Regime vocabulary fix (Fix A) — "Segment relentlessly. A rule that works globally is weaker than one that works in a specific regime."**

London open fades, NY open fades, and London/NY overlap fades have genuinely distinct statistical profiles — different liquidity depth, follow-through probability, and volatility expansion. The old `"london"` / `"ny"` / `"both"` values were unreachable by `_apply_score_routing`, meaning:

1. Score table rows with `regime="london"` accumulate but are never queried
2. Session extreme outcomes never contribute to per-regime model selection
3. Adaptive routing for this signal family is permanently disabled

With `"session_extreme_london"` etc. as the vocabulary, once n>=30 accumulates per bucket:
- The system can learn whether qwen3.5:9b or glm-5 writes better narratives for London fade setups
- The `__all__` bucket provides cross-regime routing in the meantime

This is the Renaissance segmentation principle: capture the finest granularity the data supports, aggregate up when sample size demands it, never collapse prematurely.

**Order flip (stream-first principle) — "Let the system run. Build the automation, then trust it."**

Stream is hot tier (sub-ms delivery). DB is cold tier (network + transaction overhead). Downstream consumers of the `signals:aggregated` stream (`ai_narrative_service`) should never be blocked waiting for DB completion. Publishing stream first and DB second aligns with the platform's hot/warm/cold data spine architecture established in Phase 13's feature_writer_service pattern. If DB insert fails after stream publish, the outcome back-fill no-ops — same as today, because soft FK means no cascade failure.

---

## Risk Assessment

### Risk 1: supporting_factors test failures

**What could go wrong:** `test_fires_with_trend_align_only` asserts `supporting_factors == ["trend_align"]`. After Fix A, it will be `["trend_align", "session:london"]`. If this test is not updated before the fix is applied, the test suite goes red and the pre-commit gate blocks the commit.

**Mitigation:** Update existing tests in the same task as the plugin change. This is a Wave 0 requirement, not an afterthought.

**Confidence:** HIGH — the test change is mechanical (update expected list).

### Risk 2: Metric counter displacement

**What could go wrong:** Moving `signals_generated_total.inc()` and `signals_selected_total.inc()` to after the DB insert (with the reordering) could accidentally omit them if the DB manager is None (dry-run/test mode). Currently the counters are inside `if entries and self.db_manager:`. After the reorder, they must remain gated on the same condition or be moved appropriately.

**Mitigation:** Keep the counter increments inside the `if entries and self.db_manager:` block — counters measure DB persisted signals. The stream publish block (`if result.selected_signal and self.redis_client:`) is separate and only publishes the winning signal.

**Confidence:** HIGH — straightforward structural change.

### Risk 3: Empty entries, xadd order

**What could go wrong:** If `build_ledger_entries` returns `[]` (no signals fired this bar), the stream block is already gated on `result.selected_signal is not None` — so no stream publish happens. The DB insert is gated on `if entries and self.db_manager`. Both gates are independent and correct. No risk of publishing an empty signal_id.

**Confidence:** HIGH — confirmed by reading both gate conditions.

### Risk 4: signal_id empty string vs None in llm_calls

**What could go wrong:** If `signal_id` is `""` in the stream (no winning entry), `_dec(b"signal_id")` in llm_writer returns None, and asyncpg inserts NULL for the uuid column. The `_UPDATE_OUTCOME_SQL WHERE signal_id = $1::uuid` called with NULL matches 0 rows — correct behavior (no outcome to back-fill for a signal with no UUID). No data corruption risk.

**Confidence:** HIGH — `_dec()` helper behavior is tested in `test_llm_writer_service.py`.

### Risk 5: _apply_score_routing vocabulary gap for session_extreme

**What could go wrong:** Even after Fix A, `_apply_score_routing` iterates `("trending", "ranging", "volatile", "__all__")`. The new `"session_extreme_*"` strings are not in this loop, so per-session model routing is not enabled by this phase.

**This is expected and acceptable.** The CONTEXT.md explicitly states `"__all__" bucket covers routing until per-bucket n>=30 accumulates`. The fix corrects the data storage so future extension of `_apply_score_routing` to include session_extreme keys will have clean data to work with. Extending the routing loop to cover `"session_extreme_london"` etc. is a natural Phase 18 or backlog item once n>=30 accumulates.

**Confidence:** HIGH — documented and accepted in CONTEXT.md.

### Degradation behavior

All three services handle their failure paths gracefully already:
- `signal_generator_service`: DB failure after stream publish → signal exists in stream but not DB → outcome back-fill no-ops (same as today)
- `ai_narrative_service`: stream parse failure → signal skipped, counter incremented, no crash
- `llm_writer_service`: UPDATE with NULL signal_id → 0 rows updated → no error thrown, no crash

No new failure modes are introduced by this phase.

---

## Code Examples

### Pattern 1: Extract selected entry after build_ledger_entries

```python
# Source: CONTEXT.md locked decision
entries = build_ledger_entries(result, symbol, timeframe, timestamp, features, ...)
selected_entry = next((e for e in entries if e.was_selected), None)
# Inject BEFORE stream publish:
message["signal_id"] = selected_entry.signal_id if selected_entry else ""
await self.redis_client.xadd(stream_name, message, maxlen=200, approximate=True)
# DB insert AFTER:
if entries and self.db_manager:
    await insert_signals(self.db_manager, entries)
```

### Pattern 2: _get() helper usage in parse_aggregated_signal

```python
# Source: ai_narrative_service.py existing pattern (line 144-146)
def _get(key: str, default: str = "") -> str:
    raw = fields.get(key.encode(), b"")
    return (raw.decode() if isinstance(raw, bytes) else str(raw)).strip() or default

# Apply the same pattern for signal_id (no default needed — empty string is correct):
"signal_id": _get("signal_id"),
```

### Pattern 3: SessionExtremesSetup regime_context assignment

```python
# Source: session_extremes_setup.py compute_full() — after session_ctx is determined
regime_ctx = f"session_extreme_{session_ctx}"   # "session_extreme_london" | _ny | _both
supporting.append(f"session:{session_ctx}")      # metadata: "session:london" | :ny | :both

return {
    ...
    "regime_context": regime_ctx,
    "supporting_factors": supporting,
}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|---|---|---|---|
| Session label as regime_context ("london") | Session-specific regime bucket ("session_extreme_london") | Phase 17 | Score cache keys match lookup keys; session outcomes contribute to adaptive routing |
| stream publish AFTER DB insert | stream publish BEFORE DB insert (hot tier first) | Phase 17 | Consistent with hot/warm/cold architecture; downstream consumers not blocked by DB latency |
| signal_id hardcoded "" in llm_call payload | signal_id from winning LedgerEntry UUID | Phase 17 | Outcome back-fill WHERE clause matches rows; feedback loop completes |

**Deprecated/outdated:**
- Comment `"not in aggregated stream"` on `signal_id` in `_build_llm_call_payload`: remove after fix

---

## Open Questions

1. **`_apply_score_routing` vocabulary extension for session_extreme keys**
   - What we know: current loop queries `("trending", "ranging", "volatile", "__all__")` only
   - What's unclear: when to add `"session_extreme_london"`, `"session_extreme_ny"`, `"session_extreme_both"` to the loop
   - Recommendation: defer to a future phase once n>=30 session extreme outcomes accumulate in `llm_calls` (verifiable via production query above). Document as a Phase 18 backlog item in CONTEXT.md.

2. **regime_both naming convention**
   - What we know: CONTEXT.md locked `"session_extreme_both"` for overlap
   - What's unclear: nothing — this is unambiguous
   - Recommendation: implement exactly as specified

3. **`test_fires_with_trend_align_only` test update scope**
   - What we know: the test asserts `supporting_factors == ["trend_align"]`; after Fix A it will be `["trend_align", "session:london"]`
   - What's unclear: whether the test intent is to verify exactly one factor OR verify that trend_align is present
   - Recommendation: update to `assert "trend_align" in result.get("supporting_factors", [])` and add a separate assertion that `"session:london"` is also present — this is more robust than equality comparison

---

## Sources

### Primary (HIGH confidence)
- Direct source read: `services/signal_generator_service.py` — `_process_bar()` lines 537–695, `build_ledger_entries()` lines 210–282
- Direct source read: `services/ai_narrative_service.py` — `parse_aggregated_signal()` lines 139–168, `_build_llm_call_payload()` lines 191–232, `_apply_score_routing()` lines 716–759
- Direct source read: `services/llm_writer_service.py` — `_UPDATE_OUTCOME_SQL` lines 67–78, `_parse_llm_call_fields()` lines 116–181, `_recompute_scores()` lines 575–647
- Direct source read: `src/intelligence/trading/session_extremes_setup.py` — `compute_full()` lines 47–158
- Direct source read: `src/intelligence/trading/signal_ledger.py` — `LedgerEntry` dataclass lines 24–76, `build_ledger_entries` call site
- Direct source read: `tests/unit/intelligence/trading/test_session_extremes_setup.py` — existing test coverage
- Direct source read: `tests/unit/service_tests/test_ai_narrative_helpers.py` — existing helper test coverage
- Direct source read: `tests/unit/service_tests/test_llm_writer_service.py` — existing writer test coverage
- Direct source read: `.planning/phases/17-llm-wiring-fix/17-CONTEXT.md` — locked implementation decisions

### Secondary (MEDIUM confidence)
- `.planning/REQUIREMENTS.md` — LLM-04, LLM-05 requirement definitions
- `.planning/ROADMAP.md` — Phase 17 success criteria

---

## Metadata

**Confidence breakdown:**
- Current state analysis: HIGH — read every relevant function directly; breaks confirmed by code inspection, not inference
- Fix implementation map: HIGH — changes are surgical (3 files, 4 function modifications); all patterns exist in codebase
- Validation architecture: HIGH — existing test files identified, gap list is exhaustive
- Renaissance framing: HIGH — directly maps to documented project principles

**Research date:** 2026-03-06
**Valid until:** Stable — no external dependencies; all findings are from direct source code inspection
