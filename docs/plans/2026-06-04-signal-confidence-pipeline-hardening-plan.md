# Signal Confidence Pipeline Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four structural defects in the signal confidence pipeline: remove the hidden `CONF_FLOOR` bias from plugin construction, disambiguate two-layer `calibrated_confidence` semantics, reorder calibration before the quality gate (and implicitly fix a latent bug where regime gate attenuation was being silently wiped), and delete one dead-code guard.

**Architecture:** All changes are confined to `confidence_utils.py`, `signal_processor.py`, and `calibrator.py`. Tests are updated in `test_confidence_utils.py` and a new `test_signal_processor_pipeline.py`. No schema migrations — all fields live in JSONB. The regime gate already reads `calibrated_confidence`; after the reorder it will finally see the correct value instead of the fallback.

**Tech Stack:** Python 3.11, pytest, asyncio (`pytest.mark.asyncio`).

---

## Pre-flight check

Run the full unit suite first. All must be green before any change.

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all pass.

---

## Task 1: Remove `CONF_FLOOR` from `compose_confidence()`

**Files:**
- Modify: `src/intelligence/trading/confidence_utils.py`
- Modify: `tests/unit/intelligence/test_confidence_utils.py`

### Context

`compose_confidence()` currently clamps to `[0.10, 0.95]`. The floor silently upgrades weak-conviction signals before any gate sees them, corrupting `pre_quality_confidence` in ML training data. After this task, the floor is removed — only the ceiling clamp remains. The quality gate (`min_confidence=0.12` in `apply_quality_gate`) becomes the sole publication floor.

- [ ] **Step 1: Update the failing tests first**

Replace the entire content of `tests/unit/intelligence/test_confidence_utils.py`:

```python
"""Tests for src/intelligence/trading/confidence_utils.py."""

from __future__ import annotations

from src.intelligence.trading.confidence_utils import (
    CONF_CEIL,
    compose_confidence,
)


def test_conf_ceil_value():
    assert CONF_CEIL == 0.95


def test_compose_confidence_midpoint():
    assert compose_confidence(0.5) == 0.5


def test_compose_confidence_zero_passes_through():
    """Zero is a valid raw signal confidence — no longer boosted to a floor."""
    assert compose_confidence(0.0) == 0.0


def test_compose_confidence_negative_clamps_to_zero():
    """Negative is invalid; clamp to 0.0, not to the old floor."""
    assert compose_confidence(-0.5) == 0.0


def test_compose_confidence_sub_floor_passes_through():
    """0.03 is below the old CONF_FLOOR=0.10 — must now pass through unchanged."""
    assert compose_confidence(0.03) == 0.03


def test_compose_confidence_one_clamps_to_ceil():
    assert compose_confidence(1.0) == CONF_CEIL


def test_compose_confidence_above_one_clamps_to_ceil():
    assert compose_confidence(1.5) == CONF_CEIL


def test_compose_confidence_four_decimal_rounding():
    result = compose_confidence(0.12345)
    assert result == 0.1235


def test_compose_confidence_at_ceil_boundary():
    assert compose_confidence(0.95) == 0.95


def test_compose_confidence_just_inside_ceil():
    assert compose_confidence(0.50) == 0.5000
```

- [ ] **Step 2: Run tests — expect failures**

```bash
.venv/bin/pytest tests/unit/intelligence/test_confidence_utils.py -v
```

Expected: tests referencing `CONF_FLOOR` import fail with `ImportError`; `test_compose_confidence_zero_passes_through` and `test_compose_confidence_sub_floor_passes_through` fail with assertion errors.

- [ ] **Step 3: Update `confidence_utils.py`**

Replace `src/intelligence/trading/confidence_utils.py` lines 1–45 (the constant definitions and `compose_confidence` function) with:

```python
"""System-wide confidence contract for I7 trading plugins.

Per D-12/D-13/D-14: All I7 plugins route their final confidence value through
compose_confidence(). Zero inline min()/max() clamping in plugin bodies.

The contract: ceiling only — [0.0, CONF_CEIL] = [0.0, 0.95].
The publication floor (0.12) is enforced exclusively by apply_quality_gate().
Rounding: 4 decimal places for consistent ML feature representation.

capture_signal_features() captures I4 macro context + I6 ctf_* scores + exhaustion state into
signal["features_snapshot"] for ML training — zero confidence modification.
Shadow dict has 17 keys: 2 metadata (profile, existing_confidence) + 6 I6 confluence
(ctf_score, ctf_trend_alignment, ctf_structure_alignment, ctf_regime_agreement,
ctf_fvg_alignment, ctf_ob_alignment) + 2 momentum divergence (ctf_momentum_divergence,
ctf_momentum_regime) + 4 I4 macro context (vix_level, vix_z, eq_spread_z,
eq_pairs_confirming) + 3 exhaustion fields.
ConfluenceWeightProfile holds placeholder weights (all 0.0) for each plugin family.
Phase 49 fills non-zero values once XGBoost/logistic training produces learned weights.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CONF_CEIL: float = 0.95
"""Maximum allowed confidence for any I7 signal. Floor is enforced by apply_quality_gate()."""
```

Then update the `compose_confidence` function body (keep the docstring, replace the return):

```python
def compose_confidence(raw: float) -> float:
    """Clamp raw confidence to the system ceiling [0.0, CONF_CEIL].

    All I7 plugins must route through this function before emitting a signal.
    This enforces the system-wide ceiling at a single point.

    The publication floor (min_confidence=0.12) is applied by apply_quality_gate()
    after isotonic calibration — not here. Enforcing a floor at construction time
    would corrupt pre_quality_confidence in ML training data.

    Args:
        raw: Raw confidence value (any float, including out-of-range).

    Returns:
        Float in [0.0, CONF_CEIL] rounded to 4 decimal places.
    """
    return round(min(CONF_CEIL, max(0.0, raw)), 4)
```

- [ ] **Step 4: Run tests — all must pass**

```bash
.venv/bin/pytest tests/unit/intelligence/test_confidence_utils.py -v
```

Expected: all 10 tests pass.

- [ ] **Step 5: Run the full unit suite — no regressions**

```bash
.venv/bin/pytest tests/unit/ -q
```

Some tests in `test_signal_quality_hardening.py` may import `CONF_FLOOR` and fail. Fix any import references by removing `CONF_FLOOR` from all `from confidence_utils import ...` lines in that file. Search:

```bash
grep -rn "CONF_FLOOR" tests/
```

Remove all occurrences. `CONF_FLOOR` no longer exists as an export. Rerun until green.

- [ ] **Step 6: Commit**

```bash
git add src/intelligence/trading/confidence_utils.py tests/unit/intelligence/test_confidence_utils.py
git commit -m "fix(signals): remove CONF_FLOOR from compose_confidence — gate is sole publication floor

CONF_FLOOR = 0.10 was boosting weak-conviction signals at plugin construction,
corrupting pre_quality_confidence in ML training data. compose_confidence() is
now ceiling-only [0.0, 0.95]. The quality gate (min_confidence=0.12) is the
sole publication floor, applied after isotonic calibration.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: Rename winner's CIS calibration field to `cis_calibrated_confidence`

**Files:**
- Modify: `src/intelligence/pipeline/signal_processor.py` (lines 374–377, 469–472)
- Modify: `services/intelligence_pipeline.py` (line 748 — reads winner's confidence)

### Context

`apply_calibration()` writes `calibrated_confidence = per-plugin isotonic value` on every ranked signal. Then `signal_processor.py:472` overwrites the winner's `calibrated_confidence` with `cis_result.calibrated_cis` (CIS ensemble calibration). This makes `calibrated_confidence` mean two different things for winner vs non-winner in the ledger.

After this task:
- `calibrated_confidence` = per-plugin isotonic value for ALL signals (winner and non-winner), potentially attenuated by regime gate for soft-band signals
- `cis_calibrated_confidence` = CIS ensemble calibration, ADDITIVE field on winner only

- [ ] **Step 1: Write the test first**

Create `tests/unit/intelligence/pipeline/test_signal_processor_pipeline.py`:

```python
"""Tests for signal_processor CIS field disambiguation (Fix 2)."""

from __future__ import annotations


def test_winner_carries_cis_calibrated_confidence_not_overwriting():
    """winner_payload must carry cis_calibrated_confidence as additive field.

    After Fix 2, calibrated_confidence on the winner remains the plugin-level
    isotonic value. CIS calibration is a separate additive field.
    """
    # Simulate what signal_processor does when stamping CIS calibration on winner
    winner = {
        "setup_plugin": "trend_following",
        "confidence": 0.72,
        "calibrated_confidence": 0.68,  # plugin-level isotonic
    }
    cis_calibrated = 0.81

    # The NEW logic (what we're implementing)
    winner["cis_calibrated_confidence"] = cis_calibrated

    # calibrated_confidence must NOT be overwritten
    assert winner["calibrated_confidence"] == 0.68
    # cis_calibrated_confidence must be the CIS value
    assert winner["cis_calibrated_confidence"] == 0.81
    # both fields coexist
    assert "calibrated_confidence" in winner
    assert "cis_calibrated_confidence" in winner
```

- [ ] **Step 2: Run test — expect pass (it's a unit assertion)**

```bash
.venv/bin/pytest tests/unit/intelligence/pipeline/test_signal_processor_pipeline.py -v
```

Expected: PASS (the test validates the contract we're about to enforce in production code).

- [ ] **Step 3: Update `signal_processor.py`**

Find the two locations referencing the CIS stamp on winner:

**Location A** — stale comment at approximately line 374–377. Find:
```python
        # CRITICAL-02: per-signal plugin confidence calibration before winner selection.
        # apply_calibration uses 3-tuple (plugin, tf, symbol) key with '*' global fallback.
        # Winner's calibrated_confidence is later overwritten by cis_result.calibrated_cis
        # (CIS-level calibration) — the two layers are intentionally distinct.
```

Replace with:
```python
        # CRITICAL-02: per-signal plugin confidence calibration before winner selection.
        # apply_calibration uses 3-tuple (plugin, tf, symbol) key with '*' global fallback.
        # calibrated_confidence = isotonic-calibrated value (plugin-level).
        # CIS-level calibration is stamped separately as cis_calibrated_confidence on the winner.
```

**Location B** — the actual stamp at approximately line 469–472. Find:
```python
            # Design B: stamp calibrated_confidence from CIS-level calibration.
            # cis_result.calibrated_cis is None when no curve is available (passthrough).
            if cis_result.calibrated_cis is not None:
                winner_payload["calibrated_confidence"] = cis_result.calibrated_cis
```

Replace with:
```python
            # CIS-level calibration: additive field distinct from plugin-level calibrated_confidence.
            # cis_result.calibrated_cis is None when no curve is available (omit field).
            if cis_result.calibrated_cis is not None:
                winner_payload["cis_calibrated_confidence"] = cis_result.calibrated_cis
```

- [ ] **Step 4: Check `intelligence_pipeline.py:748`**

Read the context around that line:

```bash
grep -n "calibrated_confidence" services/intelligence_pipeline.py
```

If it reads `winner.get("calibrated_confidence")` to log or route winner confidence, it should continue to work: the winner now has `calibrated_confidence` = isotonic value (set by `apply_calibration`), which is the correct value to report. No change needed unless the code was relying on the CIS overwrite.

If the code says something like:
```python
winner_confidence = winner.get("calibrated_confidence")
```

Leave it. It now reads the isotonic value, which is the right thing to report. If it was using the CIS value for routing decisions, flag it — but based on the context (logging/metrics), it should be fine.

- [ ] **Step 5: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all pass. If any test explicitly asserts that the winner's `calibrated_confidence` equals `cis_result.calibrated_cis`, update that test to check `cis_calibrated_confidence` instead.

- [ ] **Step 6: Commit**

```bash
git add src/intelligence/pipeline/signal_processor.py tests/unit/intelligence/pipeline/test_signal_processor_pipeline.py
git commit -m "fix(signals): rename winner CIS calibration field to cis_calibrated_confidence

calibrated_confidence now means exactly one thing across all signals: the
per-plugin isotonic regression output (attenuated by regime gate for soft-band
signals). CIS ensemble calibration is additive as cis_calibrated_confidence on
the winner only. Prevents heterogeneous column semantics in signal_ledger that
was corrupting ML training feature vectors.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: Move `apply_calibration()` before `apply_quality_gate()`

**Files:**
- Modify: `src/intelligence/pipeline/signal_processor.py` (reorder calls in `process()`)
- Modify: `src/intelligence/pipeline/calibrator.py` (update `dag_order` from 4 to 0)
- Modify: `tests/unit/intelligence/pipeline/test_signal_processor_pipeline.py` (add tests)

### Context

**Current (broken) order:**
```
quality_gate (raw confidence) → regime_gate (reads calibrated_confidence — NOT SET, falls back to confidence, attenuation written but later wiped) → tod → rank → apply_calibration (OVERWRITES regime gate work)
```

**After fix:**
```
apply_calibration (sets calibrated_confidence = isotonic) → quality_gate (now sees calibrated confidence) → regime_gate (reads calibrated_confidence = isotonic, attenuates for soft-band — THIS NOW PERSISTS) → tod → rank
```

This also silently fixes a latent bug: the regime gate's soft-band attenuation of `calibrated_confidence` was being wiped by the old calibration order. After this fix, that attenuation is load-bearing and correct.

Cold-start behavior (empty `cal_curves`): `apply_calibration()` passes signals through unchanged (`confidence` and `calibrated_confidence` set to raw value). Quality gate sees raw confidence — identical to old behavior.

- [ ] **Step 1: Add tests for the new gate semantics**

Append to `tests/unit/intelligence/pipeline/test_signal_processor_pipeline.py`:

```python
import numpy as np
import pytest

from src.intelligence.pipeline.calibrator import apply_calibration
from src.intelligence.pipeline.quality_gate import apply_quality_gate


@pytest.mark.asyncio
async def test_signal_below_raw_floor_survives_if_calibrated_above():
    """A signal at raw=0.08 must survive if isotonic curve calibrates it to 0.25.

    Before Fix 3, this signal was dropped by the quality gate before calibration
    ran, so the calibrated value was never seen.
    """
    sig = {
        "confidence": 0.08,
        "setup_plugin": "trend_following",
        "signal_id": "abc123",
        "direction": 1,
        "regime_type": "trend",
    }

    # Calibration curve: maps 0.08 → 0.25 (this plugin historically accurate despite low raw)
    breakpoints = np.array([0.0, 0.08, 0.50, 1.0])
    values = np.array([0.10, 0.25, 0.60, 0.95])
    cal_curves = {("trend_following", "1m", "*"): (breakpoints, values)}

    calibrated = await apply_calibration([sig], cal_curves, tf="1m")
    assert calibrated[0]["confidence"] == pytest.approx(0.25, abs=0.01)

    # Quality gate sees calibrated confidence = 0.25 → above 0.12 floor → survives
    gated = await apply_quality_gate(calibrated, {}, min_confidence=0.12)
    assert len(gated) == 1


@pytest.mark.asyncio
async def test_signal_above_raw_floor_dropped_if_calibrated_below():
    """A signal at raw=0.14 must be dropped if isotonic curve calibrates it to 0.05.

    Before Fix 3, this signal passed the gate at raw=0.14 and was never reconsidered.
    """
    sig = {
        "confidence": 0.14,
        "setup_plugin": "mean_reversion",
        "signal_id": "def456",
        "direction": -1,
        "regime_type": "mean_reversion",
    }

    # Calibration curve: maps 0.14 → 0.05 (this plugin historically poor at 0.14)
    breakpoints = np.array([0.0, 0.14, 0.50, 1.0])
    values = np.array([0.01, 0.05, 0.45, 0.90])
    cal_curves = {("mean_reversion", "1m", "*"): (breakpoints, values)}

    calibrated = await apply_calibration([sig], cal_curves, tf="1m")
    assert calibrated[0]["confidence"] == pytest.approx(0.05, abs=0.01)

    # Quality gate sees calibrated confidence = 0.05 → below 0.12 → dropped
    gated = await apply_quality_gate(calibrated, {}, min_confidence=0.12)
    assert len(gated) == 0


@pytest.mark.asyncio
async def test_cold_start_no_curves_behaves_as_before():
    """Empty cal_curves → passthrough → quality gate sees raw confidence.

    Cold-start behavior must be identical to old behavior.
    """
    sig = {
        "confidence": 0.15,
        "setup_plugin": "trend_following",
        "signal_id": "ghi789",
        "direction": 1,
        "regime_type": "trend",
    }

    calibrated = await apply_calibration([sig], {}, tf="1m")
    # Passthrough: confidence unchanged
    assert calibrated[0]["confidence"] == 0.15

    gated = await apply_quality_gate(calibrated, {}, min_confidence=0.12)
    assert len(gated) == 1
```

- [ ] **Step 2: Run new tests — expect pass**

```bash
.venv/bin/pytest tests/unit/intelligence/pipeline/test_signal_processor_pipeline.py -v
```

Expected: all tests pass (these test the calibrator and quality_gate in isolation — the fix is in signal_processor.py which we do next).

- [ ] **Step 3: Reorder calls in `signal_processor.py`**

In `process()`, locate the pipeline stage block. The current order starting from the features build is:

```python
        features = flat_features if flat_features is not None else build_flat_features(event)

        # Design B: Update CIS scorer's calibration curves before scoring.
        self._cis_scorer.set_calibration_curves(cache_snapshot.calibration_curves)

        # Compute CIS score once per bar ...
        ...
        cis_result = self._cis_scorer.score(...)
        raw_cis: float = cis_result.cis_score
        kalman_key = (tf, symbol)
        filtered_cis = self._cis_scorer._cis_kalman_state.get(kalman_key, {}).get("x", raw_cis)

        def _record_dropped(...): ...
        def _stamp_pre(...): ...

        # Pipeline stages
        hour_et = bar.ts.astimezone(_ET).hour
        quality_gated = await apply_quality_gate(
            raw_signals,
            {...},
            tf=tf,
            recorder=self._transform_recorder,
            min_confidence=getattr(self._settings, "SIGNAL_MIN_PUBLISHABLE_CONFIDENCE", 0.12),
        )
        _record_dropped("quality", raw_signals, quality_gated)

        _stamp_pre("pre_regime_confidence", quality_gated)
        regime_gated = await apply_regime_gate(...)
        ...
        ranked = await rank_signals(...)

        # CRITICAL-02: per-signal plugin confidence calibration before winner selection.
        ranked = await apply_calibration(
            ranked,
            cache_snapshot.calibration_curves,
            tf=tf,
            symbol=symbol,
            recorder=self._transform_recorder,
        )
```

Replace the pipeline stages block with the new order. Find the comment `# Pipeline stages` and rewrite from there through the end of `apply_calibration`. The new block:

```python
        # Pipeline stages
        hour_et = bar.ts.astimezone(_ET).hour

        # CRITICAL-02: Calibrate before quality gate so the gate operates on
        # isotonic-calibrated confidence, not raw plugin values. Cold-start
        # (empty cal_curves) passes through unchanged — no behavior delta.
        # After calibration, regime_gate.apply_regime_gate() reads
        # calibrated_confidence and its soft-band attenuation now persists
        # (previously wiped by calibration running after regime gate).
        calibrated_signals = await apply_calibration(
            raw_signals,
            cache_snapshot.calibration_curves,
            tf=tf,
            symbol=symbol,
            recorder=self._transform_recorder,
        )

        quality_gated = await apply_quality_gate(
            calibrated_signals,
            {
                "hurst_quality": features.get("hurst_trend_quality", _QUALITY_FEATURE_ABSENT),
                "entropy_quality": features.get("entropy_quality", _QUALITY_FEATURE_ABSENT),
                "drift_penalty": cache_snapshot.drift_penalties.get(symbol, _DRIFT_PENALTY_ABSENT),
            },
            tf=tf,
            recorder=self._transform_recorder,
            min_confidence=getattr(self._settings, "SIGNAL_MIN_PUBLISHABLE_CONFIDENCE", 0.12),
        )
        _record_dropped("quality", calibrated_signals, quality_gated)

        _stamp_pre("pre_regime_confidence", quality_gated)
        regime_gated = await apply_regime_gate(
            quality_gated,
            features,
            prob_min=self._regime_prob_min,
            prob_soft_max=self._regime_prob_soft_max,
            dur_min=self._regime_dur_min,
            tf=tf,
            recorder=self._transform_recorder,
        )
        for sig in regime_gated:
            if not sig.get("regime_eligible", True):
                REGIME_GATE_SUPPRESSIONS_TOTAL.add(
                    1,
                    {
                        "reason": "regime_type",
                        "plugin": sig.get("setup_plugin", ""),
                        "tf": tf,
                    },
                )
        _record_dropped("regime", quality_gated, regime_gated)

        _stamp_pre("pre_tod_confidence", regime_gated)
        tod_adjusted = await apply_tod_adjustment(
            regime_gated,
            cache_snapshot.tod_priors,
            tf,
            hour_et,
            symbol=symbol,
            recorder=self._transform_recorder,
        )
        _record_dropped("tod", regime_gated, tod_adjusted)

        ranked = await rank_signals(
            tod_adjusted,
            cache_snapshot.perf_weights,
            tf,
            symbol=symbol,
            recorder=self._transform_recorder,
        )
```

Note: the `apply_calibration` call that previously appeared after `rank_signals` is now gone (moved to before quality gate). The `ranked` variable now comes directly from `rank_signals`.

- [ ] **Step 4: Update `calibrator.py` dag_order**

In `src/intelligence/pipeline/calibrator.py`, find the recorder call:

```python
                await recorder.record(
                    signal_id=s["signal_id"],
                    transform_id="isotonic",
                    dag_order=4,
```

Change `dag_order=4` to `dag_order=0` (calibration now runs first in the pipeline):

```python
                await recorder.record(
                    signal_id=s["signal_id"],
                    transform_id="isotonic",
                    dag_order=0,
```

- [ ] **Step 5: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all pass. If any pipeline test hard-codes the old ordering assumption (e.g., asserts calibration runs at dag_order=4, or asserts a signal with raw=0.08 is dropped before calibration), update those tests to match the correct new semantics.

- [ ] **Step 6: Commit**

```bash
git add src/intelligence/pipeline/signal_processor.py \
        src/intelligence/pipeline/calibrator.py \
        tests/unit/intelligence/pipeline/test_signal_processor_pipeline.py
git commit -m "fix(signals): move apply_calibration before quality gate — gate now sees calibrated confidence

Two bugs fixed in one reorder:
1. Quality gate now operates on isotonic-calibrated confidence. Signals that
   calibrate above 0.12 survive even if raw < 0.12; signals that calibrate
   below 0.12 are dropped even if raw >= 0.12.
2. regime_gate soft-band attenuation of calibrated_confidence now persists.
   Previously, apply_calibration running after regime_gate silently wiped the
   attenuation on every bar — the regime gate's soft-band logic had no effect.

calibrator.py dag_order updated from 4 to 0.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: Remove dead `bars_since == 0` guard from `_apply_alpha_decay`

**Files:**
- Modify: `src/intelligence/pipeline/signal_processor.py` (`_apply_alpha_decay` function)

### Context

`_apply_alpha_decay` contains `if bars_since == 0: return`. This guard is unreachable: the caller increments `state["bars_since"]` from its stored value before calling this function, so `bars_since` is always ≥ 1 when the function is called with a non-None state. The guard reads as meaningful logic but is dead code.

- [ ] **Step 1: Add a test documenting the invariant**

Append to `tests/unit/intelligence/pipeline/test_signal_processor_pipeline.py`:

```python
from src.intelligence.pipeline.signal_processor import _apply_alpha_decay, ALPHA_HALF_LIFE_BARS


def test_alpha_decay_applies_when_bars_since_is_one():
    """bars_since=1 must apply decay, never be short-circuited by a zero guard.

    Invariant: state["bars_since"] is always >= 1 when _apply_alpha_decay is called
    with a non-None state (caller increments before calling).
    """
    sig = {"confidence": 0.80}
    state = {"bars_since": 1}
    half_life = ALPHA_HALF_LIFE_BARS["1m"]  # 10

    _apply_alpha_decay(sig, "1m", state)

    expected = round(0.80 * (0.5 ** (1 / half_life)), 4)
    assert sig["confidence"] == expected
    assert sig["confidence"] < 0.80  # decay actually applied


def test_alpha_decay_noop_when_state_is_none():
    """None state means plugin has no prior win — no decay."""
    sig = {"confidence": 0.80}
    _apply_alpha_decay(sig, "1m", None)
    assert sig["confidence"] == 0.80
```

- [ ] **Step 2: Run tests — expect pass**

```bash
.venv/bin/pytest tests/unit/intelligence/pipeline/test_signal_processor_pipeline.py::test_alpha_decay_applies_when_bars_since_is_one tests/unit/intelligence/pipeline/test_signal_processor_pipeline.py::test_alpha_decay_noop_when_state_is_none -v
```

Expected: PASS (these already work with current code — they confirm the invariant before we touch anything).

- [ ] **Step 3: Remove the dead guard**

In `src/intelligence/pipeline/signal_processor.py`, find `_apply_alpha_decay`:

```python
def _apply_alpha_decay(sig: dict, tf: str, last_fire_state: dict | None) -> None:
    """QUAL-02: Apply exponential alpha decay to signal confidence in-place.

    Decays confidence by 0.5^(bars_since/half_life) — confidence halves every half_life
    fires since the last win. bars_since counts fires only, not elapsed bars, so silence
    does not penalize re-emergence.
    """
    if last_fire_state is None:
        return
    bars_since = last_fire_state.get("bars_since", 0)
    if bars_since == 0:
        return
    half_life = ALPHA_HALF_LIFE_BARS.get(tf, 6)
    multiplier = 0.5 ** (bars_since / half_life)
    sig["confidence"] = round(float(sig.get("confidence", 0.0)) * multiplier, 4)
```

Replace with:

```python
def _apply_alpha_decay(sig: dict, tf: str, last_fire_state: dict | None) -> None:
    """QUAL-02: Apply exponential alpha decay to signal confidence in-place.

    Decays confidence by 0.5^(bars_since/half_life) — confidence halves every half_life
    fires since the last win. bars_since counts fires only, not elapsed bars, so silence
    does not penalize re-emergence.

    Invariant: bars_since >= 1 when called with non-None state (caller increments before
    this call, so the zero case is impossible in production).
    """
    if last_fire_state is None:
        return
    bars_since = last_fire_state.get("bars_since", 0)
    half_life = ALPHA_HALF_LIFE_BARS.get(tf, 6)
    multiplier = 0.5 ** (bars_since / half_life)
    sig["confidence"] = round(float(sig.get("confidence", 0.0)) * multiplier, 4)
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/pipeline/test_signal_processor_pipeline.py -v
.venv/bin/pytest tests/unit/ -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/intelligence/pipeline/signal_processor.py \
        tests/unit/intelligence/pipeline/test_signal_processor_pipeline.py
git commit -m "fix(signals): remove dead bars_since==0 guard from _apply_alpha_decay

The guard was unreachable: caller increments state['bars_since'] before calling
this function, so bars_since is always >= 1 when state is not None. Dead code
removed; invariant documented in docstring and test.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 5: Final verification and done-coding SOP

- [ ] **Step 1: Full unit suite — must be green**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all pass, zero failures.

- [ ] **Step 2: Lint and format**

```bash
.venv/bin/ruff check . --fix && .venv/bin/black .
```

Fix any lint issues. Commit if ruff/black change files:

```bash
git add -u && git commit -m "chore: ruff/black cleanup after confidence pipeline hardening

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

- [ ] **Step 3: Verify no stray `CONF_FLOOR` references remain**

```bash
grep -rn "CONF_FLOOR" src/ tests/ services/
```

Expected: zero results. If any remain, remove them.

- [ ] **Step 4: Verify `calibrated_confidence` is no longer overwritten on winner**

```bash
grep -n "calibrated_confidence.*cis_result\|cis_result.*calibrated_confidence" src/intelligence/pipeline/signal_processor.py
```

Expected: zero results. The CIS stamp now uses `cis_calibrated_confidence`.

- [ ] **Step 5: Merge to main and push**

```bash
git checkout main && git merge --ff-only <feature-branch>
git branch -d <feature-branch>
git worktree prune
git push origin main
```
