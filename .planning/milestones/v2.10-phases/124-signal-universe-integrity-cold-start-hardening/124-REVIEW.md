---
phase: 124-signal-universe-integrity-cold-start-hardening
reviewed: 2026-06-14T00:00:00Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - src/intelligence/trading/trend_following.py
  - src/intelligence/trading/ofi_continuation.py
  - src/intelligence/trading/pattern_completion.py
  - src/intelligence/trading/liquidity_sweep_reclaim.py
  - src/intelligence/trading/anchored_vwap_reversion.py
  - services/feature_writer.py
  - production/scripts/run_historical_pipeline.py
  - production/migrations/130_promote_ctf_columns.sql
  - production/migrations/131_phase124_param_store.sql
  - tests/unit/intelligence/test_cis_plugins.py
  - tests/unit/intelligence/test_i7_extrinsic_contract.py
  - tests/unit/intelligence/trading/test_anchored_vwap_reversion.py
  - tests/unit/intelligence/trading/test_ofi_plugins.py
  - tests/unit/services/test_feature_writer.py
  - tests/unit/services/test_feature_writer_column_mapping.py
  - tests/unit/scripts/test_run_historical_pipeline.py
findings:
  critical: 4
  warning: 6
  info: 3
  total: 13
status: issues_found
---

# Phase 124: Code Review Report

**Reviewed:** 2026-06-14
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

Phase 124 rewrites 5 I7 trading plugins from persistent-state triggers to structural event triggers, promotes 4 CTF columns from JSONB to top-level double precision, and adds a `--warmup` flag to the backfill pipeline. The structural correctness of the onset-detection design is sound. However, four BLOCKER-level defects were found across the plugin and pipeline code; six warnings require attention before shipping.

---

## Critical Issues

### CR-01: `trend_following.py` pullback detection compares prices against SMA history, not price history

**File:** `src/intelligence/trading/trend_following.py:169-170`

**Issue:** The pullback-to-MA reversal logic is fundamentally broken. `ma_history` stores SMA values (appended at line 147: `state.ma_history.append(float(sma))`), but the `bars_below_sma` / `bars_above_sma` computation compares those stored SMA values against the *current* `price` scalar — not against the prices at those bars.

```python
bars_below_sma = sum(1 for ma_val in history[-pullback_min_bars:-1] if ma_val > price)
bars_above_sma = sum(1 for ma_val in history[-pullback_min_bars:-1] if ma_val < price)
```

This counts how many *past SMA values* are greater-than or less-than *today's close*. What it should count is how many past bars had `close < sma` (price was below the SMA on each historical bar). The correct implementation requires either (a) storing `(close, sma)` pairs or (b) storing `bool(close < sma)` per bar.

As coded, in a trending bull market where SMA has been rising steadily (e.g., SMA went from 5180 to 5200), *all* of those historical SMA values will be below the current price of 5200 — so `bars_below_sma` will always be 0 and the pullback condition never fires. Conversely, in some edge cases it can misfire. The entire onset-detection redesign goal is defeated.

**Fix:**
```python
# Replace ma_history deque with price_vs_sma_history (stores True = price below SMA)
# In state: below_sma_history: deque = field(default_factory=lambda: deque(maxlen=50))
# When computing:
if sma:
    current_sma = float(sma)
    state.below_sma_history.append(price < current_sma)  # True = price below SMA

if len(state.below_sma_history) >= pullback_min_bars:
    history = list(state.below_sma_history)
    bars_below_sma = sum(1 for was_below in history[-pullback_min_bars:-1] if was_below)
    bars_above_sma = sum(1 for was_below in history[-pullback_min_bars:-1] if not was_below)
    # Then check current bar crossed back:
    if direction == 1 and bars_below_sma >= pullback_min_bars - 1 and price > current_sma:
        pullback_reversal = True
```

---

### CR-02: `pattern_completion.py` confidence gate uses `<=` instead of `<`, silently drops patterns at exactly the threshold

**File:** `src/intelligence/trading/pattern_completion.py:195`

**Issue:** The confidence filter reads:
```python
if best_confidence <= confidence_min:
    return no_signal()
```
`confidence_min` defaults to `0.70`. A pattern with confidence exactly `0.70` is suppressed. The docstring says "filter out very weak patterns" but 0.70 is the *minimum*, not a weak pattern — a pattern at exactly the threshold should pass. Every other gate in this codebase uses strict `<` for "below threshold" checks. This introduces a systematic bias: the threshold in the APR parameter store means "must exceed", but the code rejects patterns at that value. More importantly, the test `test_low_confidence_below_threshold_no_signal` uses `dt_db_confidence=0.3` — far below threshold — so it does not catch this off-by-one.

**Fix:**
```python
if best_confidence < confidence_min:
    return no_signal()
```

---

### CR-03: `liquidity_sweep_reclaim.py` confidence can silently exceed 1.0 before `compose_confidence()`

**File:** `src/intelligence/trading/liquidity_sweep_reclaim.py:123-149`

**Issue:** `confidence` is built additively:
```python
base_conf = cfg.get_sync("weights.liquidity_sweep.base_conf", 0.40) ...
confidence = base_conf + depth_scale * linear_ramp(...)  # up to 0.40 + 0.20 = 0.60
if fvg_type == float(direction):
    confidence += 0.15   # → 0.75
if ob_type == float(direction):
    confidence += 0.10   # → 0.85
if sig >= 0.60:
    confidence += min(0.10, sig * 0.12)  # → up to 0.95
```

This is fine at default values. However, if an operator sets `weights.liquidity_sweep.base_conf` to e.g. 0.55 via the APR (the parameter spec does not appear in migration 131 to cap it), then `confidence` can reach 1.0+ before `compose_confidence()` is called. `compose_confidence()` does clamp to 0.95, so the emitted value is safe — but the `factor_scores` dict is computed *before* `compose_confidence()` and captures the raw (potentially >1.0) components:

```python
factor_scores = {
    "sweep_depth_score": round(min(1.0, max(0.0, sweep_depth_atr / 2.0)), 4),
    "fvg_confirmed": round(1.0 if fvg_type == float(direction) else 0.0, 4),
    "ob_confirmed": round(1.0 if ob_type == float(direction) else 0.0, 4),
}
```

The `factor_scores` values are fine, but `confidence` passed to `compose_confidence()` could be >1.0. The CLAUDE.md contract states "factor_scores dict values must all be float in [0.0, 1.0]" which is satisfied here, but the additive `confidence` pre-composition has no guard. The real risk is that the LiquiditySweep APR params (`base_conf`, `depth_scale`) are not seeded in migration 131 at all — there is no schema or state entry for `weights.liquidity_sweep.*`. This means `cfg.get_sync()` will always fall back to the hardcoded defaults (0.40, 0.20), making this a latent risk rather than an immediate defect.

**Fix:** Add the two missing APR entries to migration 131, and guard the additive pre-composition:
```python
confidence = min(1.0, base_conf + depth_scale * linear_ramp(sweep_depth_atr, 0.0, 2.0))
# ... after additions:
confidence = min(1.0, confidence)
confidence = compose_confidence(confidence)
```

---

### CR-04: `run_historical_pipeline.py:1224` uses `exc` instead of `error` (CLAUDE.md convention violation in production code path)

**File:** `production/scripts/run_historical_pipeline.py:1224-1226`

**Issue:** CLAUDE.md mandates `except X as error:` — not `exc`. Two violations exist in this file:
- Line 1224: `except Exception as exc:` in `seed_roll_chain` (async, production-facing function)
- Line 2416: `except Exception as exc:` in the parallel worker result loop

While purely a convention violation, the project ruleset explicitly calls this out as non-enforced by pre-commit and requiring manual compliance. More concretely, `seed_roll_chain` logs `error=str(exc)` which is consistent only by accident — a future refactor moving to structured logging could silently drop the field.

**Fix:**
```python
# Line 1224
except Exception as error:
    log.error("seed_roll_chain_error", base=base_symbol, error=str(error))
    print(f"  [ERROR] seed_roll_chain: {base_symbol} — {error}")

# Line 2416
except Exception as error:
    print(f"\n  {symbol} FAILED: {error}")
```

---

## Warnings

### WR-01: `trend_following.py` consolidation state resets BEFORE checking breakout when range_pct < threshold, missing same-bar breakout

**File:** `src/intelligence/trading/trend_following.py:182-208`

**Issue:** The consolidation tracking has an ordering ambiguity. When `range_pct >= consolidation_range_pct` (current bar is wide — a potential breakout bar), the code correctly checks breakout before resetting state. However, if the current bar is still narrow (`range_pct < consolidation_range_pct`), it updates `consolidation_high` and `consolidation_low` and increments `consolidation_bars`. On the next wide bar, the breakout check includes the wide bar's high/low in the consolidation bounds because the wide bar itself was added on the *previous* iteration while still narrow. This means the breakout close is being compared against a `consolidation_high` that already includes that same bar's body. In practice the `consolidation_high` is updated with `max(...)` so this makes the breakout *harder* to trigger (close must exceed a wider range), which is conservative and not directionally wrong — but it is not the intended logic.

**Fix:** Only update consolidation bounds when the bar qualifies as a consolidation bar, then separately check breakout on the next bar that *exits* the range. The current structure is close; document the intent explicitly to prevent future regression.

---

### WR-02: `ofi_continuation.py` acceleration check requires only 3 items in buffer but buffer minimum is 5

**File:** `src/intelligence/trading/ofi_continuation.py:193-205`

**Issue:** The EWMA buffer minimum (`ewma_min_history`, default 5) guards entry to the acceleration block via `if len(ofi_state.ewma_buffer) >= ewma_min_history`. Inside, the code accesses `buf[-1]`, `buf[-2]`, `buf[-3]` (3 elements). The guard is stricter than needed (5 ≥ 3 is fine), but if `ewma_min_history` is set to 2 via the APR, the guard becomes `>= 2` and `buf[-3]` would fail with an `IndexError` since the deque has only 2 elements.

The APR schema for `threshold.ofi_continuation.ewma_min_history` sets `min_value: 2` in migration 131, which is exactly the boundary case that breaks the `buf[-3]` access.

**Fix:** Either enforce `min_value: 3` in the config schema, or add an explicit `len(buf) >= 3` guard before the triple-index access:
```python
if len(ofi_state.ewma_buffer) >= ewma_min_history and len(ofi_state.ewma_buffer) >= 3:
```

---

### WR-03: `anchored_vwap_reversion.py` departure state is never cleared after signal emission — re-fires if close drifts back above VWAP briefly then reclaims again

**File:** `src/intelligence/trading/anchored_vwap_reversion.py:149-203`

**Issue:** When a signal fires, `state.departure_sigma` and `state.departure_bars` are NOT reset. The state is only cleared when `abs(sigma) < sigma_min` (line 144-146). If price briefly dips below sigma_min then re-extends, a new `departure_sigma` is captured. But if price stays above sigma_min throughout the reversion (unusual but possible in volatile ranging), `departure_sigma` remains set from the original departure. After emission, the `deduplicate_event` guard keyed on `(departure_sigma, vwap)` prevents re-fire for the same event. However, if VWAP drifts slightly (it's a session VWAP that updates continuously), `round(vwap, 4)` will produce a slightly different key, and the deduplicate guard will not block a second fire on the same departure episode.

The instance consumption pattern in `PatternCompletionPlugin` (permanently marking an instance as consumed) is the correct reference. After emission, the departure state should be explicitly cleared:
```python
# After successful signal emission:
state.departure_sigma = None
state.departure_bars = 0
```

---

### WR-04: `feature_writer.py` ON CONFLICT guard updates CTF columns only when `ctf_score IS NULL`, silently loses genuine 0.0 → non-null updates

**File:** `services/feature_writer.py:98-104`

**Issue:** The ON CONFLICT clause:
```sql
DO UPDATE SET
    ctf_score = EXCLUDED.ctf_score,
    ...
WHERE intelligence_features.ctf_score IS NULL
```

This means if a row was first inserted with `ctf_score = NULL` (cold-start bar) and then a second message arrives with `ctf_score = 0.2`, the update fires correctly. But if a row was first inserted with `ctf_score = 0.0` (genuine neutral, not cold-start), a conflict with `ctf_score = 0.3` will be silently dropped because `0.0 IS NULL` is false. The comments acknowledge the `None = cold-start, 0.0 = genuine neutral` distinction, but the ON CONFLICT guard effectively makes `0.0` permanent once written — a warm re-insert cannot correct an incorrect 0.0. In practice this requires an understanding of when the same `(ts, symbol, tf)` row would be re-inserted with different CTF values. Under normal live pipeline operation (one bar = one insert) this would not occur. Under warmup/replay scenarios it could, making this a latent correctness risk in the backfill path.

**Fix:** Document the assumption explicitly in a comment, or broaden the guard: `WHERE intelligence_features.ctf_score IS NULL OR intelligence_features.ctf_score = 0.0` — though this trades one issue for another. The safest fix is to document the invariant that "a given (ts, symbol, tf) is only ever inserted once from the live pipeline."

---

### WR-05: `migration 130` backfill UPDATE races with live `feature_writer` inserts on `ctf_score IS NULL` rows

**File:** `production/migrations/130_promote_ctf_columns.sql:33-39`

**Issue:** Statement 2 (the backfill UPDATE) is guarded by `WHERE ctf_score IS NULL AND cross_timeframe_context ? 'ctf_score'`. The pre-execution note correctly warns to wait for `lifecycle_replay.py` to complete. However, if `feature_writer` is running during the backfill UPDATE, it can insert rows with `ctf_score = <value>` concurrently. The backfill UPDATE uses `ctf_score IS NULL` so it will correctly skip those rows. The risk is Statement 3 (strip JSONB keys) running while feature_writer is simultaneously inserting rows that still have `ctf_score` in `cross_timeframe_context`. Those new rows will have the JSONB key stripped by Statement 3 only if they existed before Statement 3 ran — rows inserted *after* Statement 3 will retain the key in JSONB, creating a mixed state where some rows have the CTF score in the top-level column only (stripped from JSONB) and others have it in both places.

The migration note says to apply BEFORE deploying updated feature_writer, which mitigates this if followed. But Statement 3 has no guard (`WHERE cross_timeframe_context ? 'ctf_score'` is present but that only gates on key existence, not on column population) and there is no explicit dependency check between Statements 2 and 3. The rollout instruction should be more explicit: stop `intelligence_pipeline` before running Statement 2 and Statement 3, then restart after deploying updated `feature_writer`.

---

### WR-06: `test_feature_writer_column_mapping.py:145` misleading test name asserts 32 elements but expects 37

**File:** `tests/unit/services/test_feature_writer_column_mapping.py:145-152`

**Issue:** The test function is named `test_record_to_insert_params_returns_32_element_tuple` but the assertion inside is `assert len(params) == 37`. This is a clear copy-paste artifact from before the Phase 124 CTF column promotion expanded the tuple from 33 to 37 elements. The test passes (correct behaviour is asserted), but the function name is wrong and actively misleads any developer reading it about the expected tuple arity.

**Fix:** Rename to `test_record_to_insert_params_returns_37_element_tuple`.

---

## Info

### IN-01: `run_historical_pipeline.py:1224` `seed_roll_chain` exception variable naming (see CR-04)

Covered under CR-04. Listed here as a secondary reference.

---

### IN-02: `ofi_continuation.py` `_MAGNITUDE_FLOORS_DEFAULT` is a module-level mutable dict

**File:** `src/intelligence/trading/ofi_continuation.py:31-37`

**Issue:** `_MAGNITUDE_FLOORS_DEFAULT: dict[str, float] = {...}` is a mutable module-level constant. In normal usage this is safe — nobody mutates it — but if `cfg.get_sync()` returns a dict reference and a caller modifies the fallback, it would mutate the module-level default. This is a very low-risk issue in a read-only plugin but worth flagging as a style concern. The simpler pattern used by other modules is to use a frozen structure or at minimum prefix with `_`.

**Fix:** No immediate action required. If the pattern causes a test failure in the future, replace with `types.MappingProxyType({...})`.

---

### IN-03: `pattern_completion.py` triangle lookback slice uses `high[-lookback - 1 : -1]` which excludes the current bar

**File:** `src/intelligence/trading/pattern_completion.py:175`

**Issue:** Triangle structural completion uses:
```python
lookback = max(2, min(apex_bars, len(close) - 1))
consolidation_high = float(high[-lookback - 1 : -1].max())
consolidation_low = float(low[-lookback - 1 : -1].min())
```

The slice `[-lookback - 1 : -1]` excludes the current bar (`close[-1]`). This is intentional — it measures the consolidation range from *before* the current breakout bar. The current bar's `close` is then compared against this historical range. This is architecturally correct (you don't want the breakout bar's own high/low to set the boundary it's being tested against). However, this is subtle and undocumented, and differs from how consolidation_high/low are computed in `trend_following.py` (which includes the current bar in the accumulation). Consider adding a brief comment explaining the exclusion.

---

_Reviewed: 2026-06-14_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
