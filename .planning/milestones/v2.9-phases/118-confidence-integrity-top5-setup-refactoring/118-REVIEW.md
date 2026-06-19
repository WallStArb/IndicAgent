---
phase: 118-confidence-integrity-top5-setup-refactoring
reviewed: 2026-06-09T00:00:00Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - src/intelligence/trading/cvd_divergence.py
  - src/intelligence/trading/divergence_stack.py
  - src/intelligence/trading/gap_analysis_setup.py
  - src/intelligence/trading/momentum_breakout.py
  - src/intelligence/trading/ofi_continuation.py
  - src/intelligence/trading/pattern_completion.py
  - src/intelligence/trading/squeeze_expansion.py
  - src/intelligence/trading/trend_following.py
  - tests/unit/intelligence/test_cvd_divergence.py
  - tests/unit/intelligence/test_divergence_stack.py
  - tests/unit/intelligence/test_gap_analysis_setup.py
  - tests/unit/intelligence/test_i7_exhaustion_wiring.py
  - tests/unit/intelligence/test_i7_extrinsic_contract.py
  - tests/unit/intelligence/test_ofi_continuation.py
  - tests/unit/intelligence/test_pattern_completion.py
  - tests/unit/intelligence/trading/test_cvd_plugins.py
findings:
  critical: 3
  warning: 5
  info: 3
  total: 11
status: issues_found
---

# Phase 118: Code Review Report

**Reviewed:** 2026-06-09T00:00:00Z
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

Phase 118 refactors 8 I7 trading setup plugins to strip extrinsic confidence modifiers (CTF, HMM regime weights, exhaustion guards) and replace them with 4-factor intrinsic confidence composites. The extrinsic strip is well-executed and thoroughly tested. Three correctness bugs are present: SqueezeExpansion emits signals with empty symbol/timeframe fields (all signals are unidentifiable in the ledger), CVDDivergence uses `__symbol__` for state tracking but `frames.get("symbol")` for signal emission (state key and emitted symbol can silently diverge), and the DivergenceStack `n_agreeing` counter conflates inputs where bull == bear (tie-score, direction=0) as agreeing inputs, inflating the gate check. Five warnings cover a dead variable fetch, a stale persistence score inversion logic, an inconsistent gate comparison operator, and two open TODO stubs shipped without integration.

---

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: SqueezeExpansion emits every signal with empty symbol and timeframe

**File:** `src/intelligence/trading/squeeze_expansion.py:156-168`
**Issue:** The `make_signal_from_frame()` call hard-codes `symbol=""`, `timeframe=""`, and `timestamp=""`. This is not a default fallback — it is unconditional. Every signal emitted by `trad_SqueezeExpansion` will have a blank symbol and timeframe, making the records unidentifiable in `signal_ledger` and unusable for lifecycle tracking, shadow governance, and ML training. All other plugins in this phase either read `frames.get("symbol", "")` or read from `__symbol__`/`__timeframe__` keys.

**Fix:**
```python
return make_signal_from_frame(
    tf,
    symbol=frames.get("symbol", ""),
    timeframe=features.get("timeframe", frames.get("__timeframe__", "")),
    timestamp=features.get("timestamp", ""),
    signal_type=signal_type,
    setup_plugin=self.name,
    direction=direction,
    confidence=confidence,
    regime_context=regime_ctx,
    supporting_factors=supporting,
    features_snapshot=capture_signal_features(features, direction, "trend", confidence),
)
```

---

### CR-02: CVDDivergence uses `__symbol__` key for state tracking but `frames.get("symbol")` for signal emission — symbol can silently diverge

**File:** `src/intelligence/trading/cvd_divergence.py:99-101, 184`
**Issue:** State tracking uses `symbol = frames.get("__symbol__", "_")` (line 99), which is the internal pipeline key. Signal emission on line 184 uses `frames.get("symbol", "")`, which is the external consumer key. If the pipeline populates only one of these keys (common in tests and in the live pipeline depending on the caller), the state key is keyed on the internal symbol (`"ES"` from `__symbol__`) while the emitted signal is attributed to `""` (from the absent `"symbol"` key). This means the signal ledger receives blank-symbol signals while state accumulates correctly, causing a state/emission mismatch. Sibling plugin `ofi_continuation.py` has the same two-key pattern consistently (uses `__symbol__` for both state key and signal emission), but CVDDivergence mixes them.

**Fix:** Line 184 — use the same key as the state:
```python
symbol=frames.get("__symbol__", frames.get("symbol", "")),
```

---

### CR-03: DivergenceStack `n_agreeing` counts direction=0 inputs as agreeing

**File:** `src/intelligence/trading/divergence_stack.py:144-155`
**Issue:** When `bull == bear` (both non-zero and equal), `per_input_direction[name]` is set to `0` (line 152), but `per_input_scores[name]` is still `max(bull, bear) > 0`. The `n_agreeing` counter on line 155 counts any input where `score > 0`. This means a tied input (bull=0.5, bear=0.5) counts as an agreeing input toward the `DIVERGENCE_MIN_AGREEING=3` gate, even though it contributes direction=0 and provides no directional evidence. The gate can fire on ambiguous evidence. Additionally, `per_input_direction[name] == 0` inputs contribute to neither `bull_weight` nor `bear_weight` (lines 196-205) so the direction determination is correct, but the gate count is inflated, violating the documented invariant "inputs with score > 0 and a direction."

**Fix:**
```python
# n_agreeing: inputs with a clear directional score
n_agreeing = sum(
    1 for name, s in per_input_scores.items()
    if s > 0 and per_input_direction[name] != 0
)
```

---

## Warnings

### WR-01: CVDDivergence fetches `cvd_slope_5bar` twice — dead variable on line 93

**File:** `src/intelligence/trading/cvd_divergence.py:93, 148`
**Issue:** `cvd_slope` is read from `features` at line 93 (`cvd_slope = features.get("cvd_slope_5bar")`). The confidence computation on line 148 then re-fetches the same key into `cvd_slope_raw`. The variable `cvd_slope` (line 93) is only used in the supporting factors section (line 175). While not a correctness bug, this is a code smell that obscures why the variable exists and creates a maintenance trap — future edits to one fetch may miss the other. The naming (`cvd_slope` vs `cvd_slope_raw`) implies they differ when they do not.

**Fix:** Remove the early fetch at line 93 and rename the confidence-section variable to `cvd_slope`:
```python
# Remove: cvd_slope = features.get("cvd_slope_5bar")  # line 93 — dead until line 175
# Use cvd_slope consistently throughout
cvd_slope = features.get("cvd_slope_5bar")
if cvd_slope is not None:
    slope_score = 1.0 if (float(cvd_slope) * cvd_div > 0) else 0.2
...
if cvd_slope is not None:
    supporting.append(f"cvd_slope_5bar={float(cvd_slope):.1f}")
```

---

### WR-02: DivergenceStack `persistence_score` logic is inverted relative to its documented intent

**File:** `src/intelligence/trading/divergence_stack.py:264-274`
**Issue:** The comment says "freshness, not max-age — a stale stack is lower quality than one with a freshly-confirmed input." The score is `1.0 - min_active_age / 10.0` where `min_active_age` is the minimum age among active inputs. After the first call (age=1), this yields `1.0 - 1/10 = 0.90`. After 10 calls (age=10), this yields `0.0`. The intent is correct in the comment. However, the age increment logic on lines 163-168 runs **before** the gate check — so on the same bar a signal fires, the age has already been incremented for that bar. On the very first firing bar with all inputs active, `min_active_age = 1` and `persistence_score = 0.90`. This is not a bug per se, but the test `TestFreshnessPersistenceRecentHigherThanStale` calls the plugin 1 vs 9 times and expects fresh > stale. At call 1: age=1, score=0.90. At call 9: age=9, score=0.10. This is correct. However, at call 10: score=0.0, and at call 11 and beyond: score stays at 0.0 (clamped). Any stack held for more than 10 bars gets a zero persistence score and the confidence drops significantly. This cliff at bar 10 is not documented and may cause unexpected signal quality degradation for durable divergence stacks.

**Fix:** Document the 10-bar freshness cliff or increase the denominator:
```python
# Consider: persistence_score = min(1.0, max(0.0, 1.0 - min_active_age / 20.0))
# This gives positive scores for stacks up to 20 bars old
```

---

### WR-03: GapAnalysisSetup `high_volume` uses strict inequality (`>=`) while `timing_score` time gate uses non-strict (`>`) — inconsistent boundary semantics

**File:** `src/intelligence/trading/gap_analysis_setup.py:83, 116, 119`
**Issue:** The session time gate on line 83 fires for `bars_since > 30` (strict). Line 116 `high_volume = vol_ratio >= self.volume_confirm_ratio` uses non-strict. Line 119 `gap_size_atr >= self.continuation_atr_mult` uses non-strict. This is inconsistent: at the exact boundary value `vol_ratio == 1.5`, a signal is classified as `high_volume`; at `bars_since == 30`, the time gate is NOT triggered. These inconsistencies are minor individually but compound when boundary test cases are written (see `test_accepts_gap_at_0_8_atr` which relies on this). The `min_gap_atr_mult` gate on line 102 uses strict `<` so `abs(gap_size) == 0.8 * atr` does pass the gate — which the test on line 224 correctly asserts. No incorrect behavior for typical market data, but boundary semantics should be documented or unified.

**Fix:** Document boundary semantics in each gate comment or unify to strict `>` for all:
```python
high_volume = vol_ratio > self.volume_confirm_ratio   # strictly exceed to classify as high-volume
```

---

### WR-04: MomentumBreakout and SqueezeExpansion ship with `requires_i6_confluence: bool = False` plus open TODO comments

**File:** `src/intelligence/trading/momentum_breakout.py:51`, `src/intelligence/trading/squeeze_expansion.py:52`
**Issue:** Both plugins carry `requires_i6_confluence = False` with `# TODO(phase-118): integrate I6 confluence`. The CLAUDE.md and intelligence CLAUDE.md document that `requires_i6_confluence` controls the aggregator's pre-promotion gate. Shipping phase-118 with these TODOs means two trend-regime plugins bypass the I6 confluence check that was expressly re-stated as a quality gate for this phase. The TODOs are not tracked in a separate issue; they are inline in production code.

**Fix:** Either complete the I6 integration before merging, or remove the TODO comment and add a tracking note to ROADMAP:
```python
requires_i6_confluence: bool = False  # Phase 119 target — see ROADMAP #momentum-i6
```

---

### WR-05: OFIContinuation uses `frames.get("__symbol__", "_")` for state tracking, passes `symbol` (not `__symbol__`) to `make_signal_from_frame` — same dual-key pattern as CR-02 but with fewer consequences

**File:** `src/intelligence/trading/ofi_continuation.py:104, 183`
**Issue:** State tracking and signal emission both use `symbol` correctly (state uses `__symbol__`, signal uses `symbol` resolved at line 183 from `symbol` local variable set at line 104 which reads `__symbol__`). However, line 183 passes `symbol=symbol` where `symbol` was extracted with `frames.get("__symbol__", "_")`. If the pipeline populates `"symbol"` but not `"__symbol__"`, the state key is `"_"` while the signal emits `"_"` too — both are wrong but consistently wrong. Lower severity than CR-02 because both fields use the same variable; but the fallback default `"_"` will cause all unknown-symbol signals to share a single state bucket, which corrupts the consecutive bar count when multiple instruments are processed by the same plugin instance.

**Fix:**
```python
symbol = frames.get("__symbol__") or frames.get("symbol", "_")
```

---

## Info

### IN-01: DivergenceStack state key uses a tuple `(symbol, timeframe)` while CVDDivergence and OFIContinuation use a string `f"{symbol}_{tf}"` — inconsistency across sibling plugins

**File:** `src/intelligence/trading/divergence_stack.py:114`
**Issue:** `state_key = (symbol, timeframe)` is a tuple. All other plugins in this phase construct `state_key = f"{symbol}_{tf}"` (a string). Both work, but the inconsistency means `state_utils.reset_consecutive_state()` cannot be used with DivergenceStack (the utility builds the key as a formatted string internally). This is not a bug since DivergenceStack manages its own state dict directly without `state_utils`, but it increases cognitive overhead.

**Fix:** Align to the project convention (string key):
```python
state_key = f"{symbol}_{timeframe}"
```

---

### IN-02: `test_i7_exhaustion_wiring.py` tests are negative-only (no-boost / no-penalty paths) — the boost and guard positive paths are absent

**File:** `tests/unit/intelligence/test_i7_exhaustion_wiring.py:170-228`
**Issue:** The file is titled "RED test stubs for I7 exhaustion wiring" and the header comment states these tests "FAIL with AssertionError — the I7 plugins exist but the exhaustion wire logic is not yet implemented." But the tests all assert that boost/penalty is NOT applied under below-threshold conditions. These tests pass today (they are negative assertions). The positive-path tests ("when score is above threshold, boost IS applied") are entirely absent. If the exhaustion boost/guard is intentionally removed by Phase 118, this file should be updated to reflect that. If it is still planned, the positive-path stubs are missing.

**Fix:** Either delete this file (if exhaustion wiring is permanently removed) or add positive-path tests and mark them with `@pytest.mark.xfail(strict=True)` until implemented.

---

### IN-03: GapAnalysisSetup `entry_type` field for fade signals is set to `"at_limit"` in the plugin code (line 129) but the test on line 161 asserts `entry_type == "at_close"` claiming `frame_trade` overwrites it

**File:** `src/intelligence/trading/gap_analysis_setup.py:129`, `tests/unit/intelligence/test_gap_analysis_setup.py:159-161`
**Issue:** The plugin sets `entry_type = "at_limit"` on line 129 before calling `frame_trade()`. The test comment says "frame_trade resolves gap signals to at_close." If `frame_trade()` silently overwrites `entry_type`, the plugin's explicit assignment is dead code. If `frame_trade()` does not overwrite it, the test assertion for `at_close` would fail. Either the plugin assignment is dead (and should be removed), or the test expectation is wrong (and `at_limit` should be asserted instead). This needs verification against `frame_trade()` internals and the test should document which path is authoritative.

**Fix:** Verify `frame_trade()` behavior and either remove the `entry_type = "at_limit"` assignment if it is overwritten, or update the test to assert `at_limit`.

---

_Reviewed: 2026-06-09T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
