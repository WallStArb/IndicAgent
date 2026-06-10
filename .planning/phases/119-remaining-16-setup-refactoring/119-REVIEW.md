---
phase: 119-remaining-16-setup-refactoring
reviewed: 2026-06-10T00:00:00Z
depth: standard
files_reviewed: 41
files_reviewed_list:
  - docs/architecture/i7-setup-confidence-patterns.md
  - src/intelligence/plugins/base.py
  - src/intelligence/register_plugins.py
  - src/intelligence/trading/candlestick_pattern_setup.py
  - src/intelligence/trading/cvd_spike.py
  - src/intelligence/trading/delta_exhaustion.py
  - src/intelligence/trading/dual_divergence.py
  - src/intelligence/trading/failed_breakout.py
  - src/intelligence/trading/liquidity_hunt.py
  - src/intelligence/trading/lvn_breakout.py
  - src/intelligence/trading/microstructure_utils.py
  - src/intelligence/trading/momentum_breakout.py
  - src/intelligence/trading/ofi_divergence.py
  - src/intelligence/trading/ofi_spike.py
  - src/intelligence/trading/orb15.py
  - src/intelligence/trading/orb30.py
  - src/intelligence/trading/second_leg_continuation.py
  - src/intelligence/trading/session_extremes_setup.py
  - src/intelligence/trading/trade_framer.py
  - src/intelligence/trading/vcp.py
  - src/intelligence/trading/vwap_deviation.py
  - src/intelligence/trading/vwap_reclaim.py
  - tests/unit/intelligence/test_i6_confluence_enforcement.py
  - tests/unit/intelligence/test_i6_hmm_confidence_wiring.py
  - tests/unit/intelligence/test_i7_extrinsic_contract.py
  - tests/unit/intelligence/test_momentum_breakout.py
  - tests/unit/intelligence/test_ofi_divergence.py
  - tests/unit/intelligence/test_vwap_deviation.py
  - tests/unit/intelligence/trading/test_candlestick_pattern_setup.py
  - tests/unit/intelligence/trading/test_candlestick_tier1_setups.py
  - tests/unit/intelligence/trading/test_cvd_plugins.py
  - tests/unit/intelligence/trading/test_dual_divergence.py
  - tests/unit/intelligence/trading/test_failed_breakout.py
  - tests/unit/intelligence/trading/test_liquidity_hunt.py
  - tests/unit/intelligence/trading/test_lvn_breakout.py
  - tests/unit/intelligence/trading/test_ofi_plugins.py
  - tests/unit/intelligence/trading/test_orb15.py
  - tests/unit/intelligence/trading/test_orb30.py
  - tests/unit/intelligence/trading/test_second_leg_continuation.py
  - tests/unit/intelligence/trading/test_session_extremes_setup.py
  - tests/unit/intelligence/trading/test_vcp.py
  - tests/unit/intelligence/trading/test_vwap_reclaim.py
findings:
  critical: 7
  warning: 5
  info: 2
  total: 14
status: issues_found
---

# Phase 119: Code Review Report

**Reviewed:** 2026-06-10
**Depth:** standard
**Files Reviewed:** 41
**Status:** issues_found

## Summary

Phase 119 refactored 17 I7 setup plugins to implement the 6 GOOD patterns (dual gate,
4-factor confidence composite, shadow_only=True, requires_i6_confluence=True). The
structural implementation - dual gate placement, gate logic, confidence formula weights,
and ClassVar declarations - is largely correct.

However, four plugins carry a `regime_type` mismatch between what the architecture doc
declares and what the code implements. Since `regime_type` affects stop-placement via
`frame_trade()` and aggregator regime suppression, these are correctness defects. Two
additional signal identity bugs (hardcoded empty symbol/timeframe) produce silent data
loss at the ledger layer. One formula defect in `microstructure_utils.py` produces a
systematically negative confidence factor. Three plugins return a bare `{}` instead of
`no_signal()` in their short-circuit exit path, breaking the canonical no-signal contract.

---

## Critical Issues

### CR-01: `DeltaExhaustion` declares `regime_type = "mean_reversion"` but architecture doc mandates `"any"`

**File:** `src/intelligence/trading/delta_exhaustion.py:62`

**Issue:** `docs/architecture/i7-setup-confidence-patterns.md` (line 176) lists DeltaExhaustion
as `regime_type = "any"`. The code declares `regime_type = "mean_reversion"`. This has
two concrete consequences:

1. `frame_trade()` passes `regime_type="mean_reversion"` to `_adaptive_buffer()`, which
   tightens the Hurst regime-confirmation path for mean-reversion. For a signal that should
   be regime-agnostic, this silently narrows stop buffers in mean-reversion conditions.
2. The aggregator regime suppression gate reads `regime_type` from the plugin ClassVar to
   decide whether to suppress signals in trending vs ranging markets. With `mean_reversion`,
   DeltaExhaustion signals are suppressed in trending regimes - the wrong behavior for an
   exhaustion signal that fires regardless of regime.

The gate code correctly uses `hmm_regime_weight(features, "ranging")` (line 89), but the
`regime_type` ClassVar contradicts it and propagates incorrect metadata downstream.

**Fix:**
```python
regime_type: str = "any"
```
Also update the gate comment at line 88 to reflect the doc: the ranging gate is a domain
gate (exhaustion requires price failure), not a "mean_reversion regime gate".

---

### CR-02: `FailedBreakout` declares `regime_type = "mean_reversion"` but architecture doc mandates `"any"`

**File:** `src/intelligence/trading/failed_breakout.py:57`

**Issue:** `docs/architecture/i7-setup-confidence-patterns.md` (line 172) lists FailedBreakout
as `regime_type = "any"`. The code has `regime_type: str = "mean_reversion"`. The gate
implementation at lines 119-122 correctly uses the "any" semantics (blocks only when BOTH
up AND down are below threshold, matching the pattern for `regime_type = "any"` trend
plugins), but the ClassVar is `"mean_reversion"`. This inconsistency means:

- `frame_trade()` uses the wrong Hurst/GARCH buffer path.
- The aggregator suppresses FailedBreakout in trending regimes, but BOS reversals are
  specifically relevant in trending regimes where a structure break fails.

**Fix:**
```python
regime_type: str = "any"
```

---

### CR-03: `ORB15` and `ORB30` declare `regime_type = "trend"` but architecture doc mandates `"any"`

**File:** `src/intelligence/trading/orb15.py:82`, `src/intelligence/trading/orb30.py:86`

**Issue:** `docs/architecture/i7-setup-confidence-patterns.md` (lines 181-182) lists both
ORB plugins as `regime_type = "any"`. Both files declare `regime_type: str = "trend"`.
The gate implementation uses the direction-specific trending form (blocking only when both
"up" and "down" are below threshold, line 109-110 in orb15.py), which matches the
architectural intent for `"any"` regime plugins, not `"trend"`. The ClassVar mismatch
passes incorrect metadata to `frame_trade()` and the aggregator.

**Fix (both files):**
```python
regime_type: str = "any"
```

---

### CR-04: `DualDivergence` declares `regime_type = "mean_reversion"` but architecture doc mandates `"any"`

**File:** `src/intelligence/trading/dual_divergence.py:71`

**Issue:** `docs/architecture/i7-setup-confidence-patterns.md` (line 185) lists
DualDivergence as `regime_type = "any"`. The code has `regime_type: str = "mean_reversion"`.
The gate uses `hmm_regime_weight(features, "ranging")` at line 111, which is valid for
the mean-reversion domain gate, but `regime_type = "any"` is specified in the doc and the
domain of dual divergence signals spans all regimes. The `"mean_reversion"` ClassVar will
cause aggregator suppression of DualDivergence signals in trending regimes.

**Fix:**
```python
regime_type: str = "any"
```
Retain the `hmm_regime_weight(features, "ranging")` gate - that is the domain gate, not
the regime classification.

---

### CR-05: `LVNBreakout` and `SecondLegContinuation` pass hardcoded empty strings for `symbol`, `timeframe`, and `timestamp` to `make_signal_from_frame()`

**File:** `src/intelligence/trading/lvn_breakout.py:227-229`, `src/intelligence/trading/second_leg_continuation.py:232-234`

**Issue:** Both plugins call `make_signal_from_frame()` with `symbol=""`, `timeframe=""`,
`timestamp=""`. Every other Phase-119 plugin correctly reads these from the frames dict.
With blank symbol/timeframe, every signal emitted by these two plugins will:

- Have an empty `symbol` field in `signal_ledger` - the JOIN used by downstream consumers
  (`signal_ledger_full`, `signal_outcomes`) is `(symbol, feature_ts, feature_tf)`. An empty
  symbol makes the signal unqueryable by symbol.
- Have empty `timeframe`, breaking feature-ts computation and TTL evaluation.
- Have empty `timestamp`, creating a null primary time column entry.

This is silent data corruption. The signals fire and reach Kafka but produce ledger rows
that cannot be joined to any instrument context.

**Fix for `lvn_breakout.py`:**
```python
# Replace the hardcoded empty strings:
symbol=frames.get("symbol", "") or frames.get("__symbol__", ""),
timeframe=frames.get("__timeframe__", "") or features.get("timeframe", ""),
timestamp=features.get("timestamp", ""),
```

**Fix for `second_leg_continuation.py`:** same pattern - read from frames dict like
all other plugins in this phase.

---

### CR-06: `microstructure_utils.py` - `persistence_score` formula produces negative values that are always clamped to 0.0 when spike and price move in the same magnitude range

**File:** `src/intelligence/trading/microstructure_utils.py:104`

**Issue:** The formula is:
```python
persistence_score = clamp01(abs(spike_z) / max(1.0, abs(float(price_return_z))) - 1.0)
```
This computes `ratio - 1.0` before clamping. When `price_return_z` is larger than
`spike_z` (price has followed through at least as much as the spike) the ratio is < 1.0
and the result is negative, which `clamp01` maps to 0.0. This means `persistence_score`
is **always 0.0** unless the OFI/CVD spike magnitude exceeds the price return z-score. At
`spike_z = 2.01` (gate threshold +epsilon) with `price_return_z = 3.0`, the score is 0.0
despite the signal having passed the 2-sigma gate.

The denominator `max(1.0, ...)` also means that when `price_return_z` is missing
(defaulting to 0.3), the score is `2.01/1.0 - 1.0 = 1.01` clamped to 1.0, giving
artificially maximum persistence_score when no price data is available.

The 10% weight of `persistence_score` makes this a moderate but silent quality distortion.
A meaningful "persistence" metric should measure how many bars the spike has been sustained,
not the spike/price magnitude ratio.

**Fix:**
```python
# Use bars-of-persistence or a simpler signal-relative magnitude score:
if price_return_z is not None:
    price_follow_ratio = abs(float(price_return_z)) / max(1.0, abs(spike_z))
    persistence_score = clamp01(1.0 - price_follow_ratio)  # high when spike >> price move
else:
    persistence_score = 0.3
```

---

### CR-07: `validate_tier()` in `base.py` - `_I7_I6_EXEMPT` import uses function-local import that could mask `ImportError` as silent bypass

**File:** `src/intelligence/plugins/base.py:155`

**Issue:**
```python
from src.intelligence.register_plugins import _I7_I6_EXEMPT  # noqa: PLC0415
```
This import is inside `validate_tier()` to avoid a circular import. However, if
`register_plugins.py` fails to import for any reason (a broken plugin import, syntax
error), this function-local import raises `ImportError` - which is not caught. The
`validate_tier()` function would crash with `ImportError` rather than `ArchitectureViolation`,
and the error message would point to `base.py` rather than the actual broken plugin.
This is acceptable, but a secondary risk exists: if `_I7_I6_EXEMPT` is refactored or
renamed in `register_plugins.py`, the local import silently breaks startup without any
test covering the import itself (all tests in `test_i6_confluence_enforcement.py` import
`_I7_I6_EXEMPT` directly at module level from the test, which fails differently).

The more serious concern: the exemption check logic on lines 157-163 uses `getattr(plugin,
"requires_i6_confluence", None)` which returns `None` for a missing attribute. The condition
`not getattr(..., None)` is `True` when the value is `False` OR when the attribute is
missing. But the `hasattr` check on line 148 should have already caught the missing case
and raised `ArchitectureViolation` before reaching line 157. If the hasattr check on line
148 fires for a plugin in `_I7_I6_EXEMPT`, the function correctly skips it. However, if
a plugin is NOT in `_I7_I6_EXEMPT` but has `requires_i6_confluence = None` (not False),
the condition `not None` is `True` and an `ArchitectureViolation` would fire correctly.
No actual bug here - but the dual `hasattr`/`getattr` makes the logic hard to verify.

**Fix (robustness improvement):**
```python
# After the hasattr check already confirmed the attribute exists, use direct access:
if name not in _I7_I6_EXEMPT and not plugin.requires_i6_confluence:
    raise ArchitectureViolation(...)
```

---

## Warnings

### WR-01: Three plugins return bare `{}` instead of `no_signal()` in the min_lookback short-circuit

**File:** `src/intelligence/trading/failed_breakout.py:76`, `src/intelligence/trading/second_leg_continuation.py:94`, `src/intelligence/trading/session_extremes_setup.py:77`

**Issue:** When `df is None or len(df) < self.min_lookback`, these three plugins return
`{}` instead of `no_signal()`. The canonical no-signal dict is
`{"signal_type": "none", "direction": 0, "confidence": 0.0}`. A bare `{}` has
`direction == 0` (falsy), so most downstream consumers don't break, but:

- Any code doing `result.get("confidence", default)` will get a different default than the
  rest of the pipeline.
- The `BaseWriter._parse_payload` contract states `None` triggers DLQ; `{}` has ambiguous
  semantics at that boundary.
- Inconsistency with all other plugins in this phase.

**Fix:**
```python
# Replace all three `return {}` with:
return no_signal()
```

---

### WR-02: `SessionExtremesSetup` declares `regime_type = "mean_reversion"` but architecture doc mandates `"any"`

**File:** `src/intelligence/trading/session_extremes_setup.py:60`

**Issue:** `docs/architecture/i7-setup-confidence-patterns.md` (line 174) lists
SessionExtremesSetup as `regime_type = "any"`. The code has `regime_type = "mean_reversion"`.
The gate correctly uses `hmm_regime_weight(features, "ranging")` which is a domain gate
(Asian session fade setups work better in ranging conditions), but the ClassVar should
be `"any"` to match the architecture spec. With `"mean_reversion"`, the aggregator
will suppress these signals in trending regimes, which is architecturally wrong.

Unlike the BLOCKER cases (CR-01 to CR-04), the downstream data impact is lower here
because session extreme fades are less common and the shadow_only flag limits live signal
promotion, but the mismatch is still a correctness defect.

**Fix:**
```python
regime_type: str = "any"
```

---

### WR-03: `DeltaExhaustion` docstring says `regime_type="any"` (module header) but class declares `"mean_reversion"`

**File:** `src/intelligence/trading/delta_exhaustion.py:1-11`

**Issue:** The module docstring (lines 1-11) does not mention a specific regime constraint
and describes the pattern as "fires when a large CVD spike occurs but price fails to follow
through" without any regime qualifier. The class docstring (lines 34-42) correctly does not
say "mean_reversion" but the ClassVar at line 62 says `"mean_reversion"`. This contradicts
both the architecture doc and the module framing. (Also covered in CR-01 for the code fix -
this warning is about the docstring accuracy after the fix.)

**Fix:** After fixing CR-01, update the class docstring Gates section to clarify that the
ranging gate is a domain quality gate, not a regime prerequisite.

---

### WR-04: `VCPPlugin.compute_full` accesses `df["close"]`, `df["high"]`, `df["low"]` before the I6 ctf_score gate fires

**File:** `src/intelligence/trading/vcp.py:127-130`

**Issue:** The dual gate (Gate 1 at line 116, Gate 2 at line 121) runs BEFORE the OHLCV
array reads at lines 127-130. This is correct per the Pattern 3 spec (gates before OHLCV).
However, within the contraction tracking block at lines 144-163, `df["volume"].iloc[-1]`
and `df["high"/-1]`/`df["low"/-1]` are accessed *after* the gates, which is fine. But
there is a subtle issue: the session date reset block at lines 101-112 accesses
`df["timestamp"]` BEFORE Gate 1 and Gate 2. This is a timestamp lookup (not OHLCV
computation), but it does access the DataFrame before the cheap regime gates run.

This is a minor Pattern 3 violation - the session date reset is stateful bookkeeping that
arguably must run regardless of regime, so it is justifiable. But the architectural principle
"cheap gates before expensive operations" is violated if `df["timestamp"]` is considered
an OHLCV access.

**Fix:** Move the session date reset block after Gate 1 and Gate 2, or add a comment
explicitly documenting why it precedes the dual gate (state bookkeeping that must run even
when no signal fires).

---

### WR-05: `microstructure_utils.detect_spike_signal` - `ctf_factor` is included in the 4-factor confidence composite, creating a contradiction with the test comment

**File:** `src/intelligence/trading/microstructure_utils.py:100`, `tests/unit/intelligence/test_i6_hmm_confidence_wiring.py:176`

**Issue:** The test at line 176 of `test_i6_hmm_confidence_wiring.py` has a comment:
```
# ctf_factor IS part of the 4-factor composite — it does change confidence above threshold.
```
This contradicts the extrinsic contract tested in `test_i7_extrinsic_contract.py`, which
asserts that perturbing `ctf_score` must NOT change confidence. The `_PHASE_119_PLUGINS`
set in `register_plugins.py` excludes `ctf_score` from the perturbation for Phase-119
plugins precisely because `ctf_factor` IS in the confidence composite. This means
OFISpike and CVDSpike (which use `detect_spike_signal`) DO have `ctf_score` inside
their confidence formula as `ctf_factor`.

This is documented behavior, but the two tests say contradictory things about the
intended invariant. The `test_i7_extrinsic_contract.py` test correctly excludes
`ctf_score` for `_PHASE_119_PLUGINS` (line 512), so OFISpike/CVDSpike are not tested
for ctf_score perturbation. However, the comment in `test_i6_hmm_confidence_wiring.py`
("CTF is a gate, not additive") in the test class docstring at line 107 says "HMM and CTF
are now gates-only" while `ctf_factor` contributes 20% to confidence. This is a
documentation contradiction that will mislead future developers.

**Fix:** Update the `TestSpikeI6HmmWiring` class docstring to accurately state:
"Phase 119 refactor: HMM is a gate only. CTF is both a gate (below 0.25 blocks)
AND a proportional confidence factor above the gate threshold."

---

## Info

### IN-01: `_in_window` helper function is duplicated identically in `orb15.py` and `orb30.py`

**File:** `src/intelligence/trading/orb15.py:46-51`, `src/intelligence/trading/orb30.py:50-55`

**Issue:** The `_in_window` function is copy-pasted verbatim into both ORB files. The
comment in `orb30.py` says "Identical logic to ORB15" (line 7) but the shared helper is
not extracted. A future bug fix in one file will silently not apply to the other.

**Fix:** Extract to a shared `orb_utils.py` module in `src/intelligence/trading/` and
import from both ORB files.

---

### IN-02: Duplicate section header `## 7. See Also` in `i7-setup-confidence-patterns.md` (section numbering error)

**File:** `docs/architecture/i7-setup-confidence-patterns.md:207` and `299`

**Issue:** The document has two sections numbered `## 7.` - one for "Enforcement" and one
for "See Also". The section starting at line 207 is labeled `## 7. Enforcement` and the
section at line 299 is also labeled `## 7. See Also`. The actual second "See Also" section
should be `## 9. See Also` (after Section 8 Anti-patterns).

**Fix:** Renumber the final section to `## 9. See Also`.

---

_Reviewed: 2026-06-10_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
