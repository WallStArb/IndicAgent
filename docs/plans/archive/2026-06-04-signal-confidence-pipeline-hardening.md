# Signal Confidence Pipeline Hardening

**Date:** 2026-06-04
**Status:** Approved for implementation

## Problem Statement

The signal confidence pipeline has four structural defects identified in a first-principles Renaissance audit. One additional finding (Fix 4, timestamp-based alpha decay) was proposed and rejected after mathematical analysis proved the current fire-count alpha decay is already fire-frequency independent — the "asymmetry" was a false alarm.

## What Is Being Changed

### Fix 1 — Remove CONF_FLOOR from `compose_confidence()` (CRITICAL)

**File:** `src/intelligence/trading/confidence_utils.py`

**Problem:** `compose_confidence()` clamps to `[0.10, 0.95]`. The floor is a hidden bias: any plugin with raw conviction < 0.10 is silently boosted to 0.10. `pre_quality_confidence` (stamped after `compose_confidence()`) therefore never reflects genuine weak signals. ML training data has a structural gap below 0.10 that was injected by the system, not by market reality.

**Fix:** Remove `CONF_FLOOR`. `compose_confidence()` becomes a ceiling-only clamp: `round(min(CONF_CEIL, max(0.0, raw)), 4)`. The quality gate (`min_confidence=0.12` in `apply_quality_gate()`) is the sole publication floor.

Remove the `CONF_FLOOR = 0.10` constant from `confidence_utils.py`. Update the module docstring.

**Calibration curve taint:** Existing isotonic curves were fitted on a confidence distribution with a 0.10 hard floor. Sub-floor inputs will extrapolate via `np.interp` constant extrapolation from the leftmost breakpoint (conservative: all sub-floor signals map to the same calibrated value). Accept this; let curves self-heal as the ML trainer resamples on post-fix data.

**`_make_signal()` note:** `signal_schema.py:165` already clamps to `[0, 1]` via `round(min(1.0, max(0.0, confidence)), 4)`. This is correct defensive range validation — leave it unchanged. The two functions are not in conflict: `compose_confidence` owns the domain ceiling (0.95), `_make_signal` owns hard range safety (0.0–1.0).

---

### Fix 2 — Disambiguate two-layer `calibrated_confidence` (HIGH)

**File:** `src/intelligence/pipeline/signal_processor.py`

**Problem:** `apply_calibration()` writes `calibrated_confidence = per-plugin isotonic value` on every ranked signal. Then `signal_processor.py:471-472` overwrites the winner's `calibrated_confidence` with `cis_result.calibrated_cis` (CIS ensemble calibration). The signal_ledger persists all ranked signals. `calibrated_confidence` now means two different things for winner vs non-winner signals — an invisible corruption of the training feature space.

**Fix:** Rename the CIS-layer stamp to `cis_calibrated_confidence`:

```python
# Before:
winner_payload["calibrated_confidence"] = cis_result.calibrated_cis

# After:
winner_payload["cis_calibrated_confidence"] = cis_result.calibrated_cis
```

`calibrated_confidence` then consistently means: per-plugin isotonic-regression output, for all signals including the winner. `cis_calibrated_confidence` is an additive field on the winner reflecting the CIS ensemble view.

No schema migration needed: both fields live in JSONB payloads.

---

### Fix 3 — Move calibration before quality gate (HIGH)

**File:** `src/intelligence/pipeline/signal_processor.py`

**Problem:** `apply_quality_gate()` drops signals below `min_confidence=0.12`, operating on raw (uncalibrated) confidence. `apply_calibration()` runs after ranking. A signal at raw=0.11 that isotonically calibrates to 0.30 is dropped incorrectly. A signal at raw=0.12 that calibrates to 0.05 is published incorrectly. The gate is deciding on stale data.

**Fix:** New pipeline order in `process()`:

```
pre_quality_confidence stamp
alpha decay
apply_calibration()          ← moved here (dag_order=0)
apply_quality_gate()         ← now sees calibrated confidence
apply_regime_gate()
apply_tod_adjustment()
rank_signals()
annotate (CIS fields, status, bar_id)
winner selection
prepare_signals_or_dlq
```

Cold-start behavior (empty `cal_curves`): `apply_calibration()` passes through unchanged. Quality gate sees raw confidence — identical to old behavior. No regression.

Update `dag_order` in the recorder call inside `calibrator.py` from `4` to `0`.

---

### Fix 5 — Remove dead `bars_since == 0` guard (LOW)

**File:** `src/intelligence/pipeline/signal_processor.py`

**Problem:** `_apply_alpha_decay` contains:

```python
bars_since = last_fire_state.get("bars_since", 0)
if bars_since == 0:
    return
```

The guard is unreachable. `_setup_last_fire` is only queried when not None, and `bars_since` is incremented to at least 1 immediately before `_apply_alpha_decay` is called. The guard reads as meaningful logic but is dead code.

**Fix:** Remove the guard. Add a comment confirming the invariant: when this function is called with a non-None state, `bars_since >= 1`.

---

## What Was Proposed and Rejected

**Fix 4 — Timestamp-based alpha decay:** Proposed switching from `bars_since` (fires since last win) to elapsed real bars since last win. Rejected after mathematical proof that the current design is already fire-frequency independent.

Two plugins with identical win rates but different fire frequencies (one fires every bar, one every 10 bars) both accumulate the same average `bars_since` at fire time, because `bars_since` counts fires-since-last-win not elapsed calendar bars. The win rate is the sole determinant of average `bars_since`. The timestamp approach would have created a 10× asymmetry (penalizing niche plugins that fire rarely but win reliably), which is the opposite of correct.

The fire-count alpha decay is correct and unchanged.

---

## Files Modified

| File | Change |
|------|--------|
| `src/intelligence/trading/confidence_utils.py` | Remove `CONF_FLOOR`, update `compose_confidence()` to ceiling-only |
| `src/intelligence/pipeline/signal_processor.py` | Reorder calibration, rename CIS field, remove dead guard |
| `src/intelligence/pipeline/calibrator.py` | Update `dag_order` from 4 to 0 |
| `tests/unit/intelligence/test_signal_quality_hardening.py` | Update floor behavior tests |
| `tests/unit/intelligence/test_aggregator.py` | Update winner `calibrated_confidence` assertions |

## Testing

- All existing unit tests must pass green
- New test: `compose_confidence(0.03)` returns `0.03` (not `0.10`)
- New test: `compose_confidence(0.99)` returns `0.95` (ceiling still enforced)
- New test: after pipeline, winner carries both `calibrated_confidence` (plugin-level) and `cis_calibrated_confidence` (CIS-level)
- New test: signal at raw confidence 0.08 survives the pipeline if calibrated value >= 0.12 (gate sees calibrated)
- New test: signal at raw confidence 0.14 is dropped if calibrated value < 0.12
