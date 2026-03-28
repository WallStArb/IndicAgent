# Phase 48.1 Investigation: I6 Confluence Violations

## Finding Summary

All 4 plugins violate the Renaissance principle: "Never drop data that could contain signal."

### Root Cause

The 4 plugins use I6 `ctf_*` scores in **binary mode** (gate check only) instead of **magnitude-weighted mode** (continuous value).

**Correct pattern** (from cis_scorer.py):
```python
c_ctf_trend = 0.10 * clamp(self._fval(f, "ctf_trend_alignment"))
```

**Incorrect pattern** (all 4 violating plugins):
```python
ctf_score = features.get("ctf_score", 0.0)
if abs(ctf_score) > 0.3:  # Binary gate - magnitude discarded!
    confidence += 0.05
```

## Violation Details

### 1. fvg_fill.py (Line 98)
**Violation:** Missing `ctf_fvg_alignment`, `ctf_ob_alignment` entirely

**Current:**
```python
raw_conf, supporting = apply_exhaustion_boost(features, direction, raw_conf, supporting)
confidence = compose_confidence(raw_conf)
```

**Missing:** FVG-specific I6 scores that would boost confidence when multi-TF FVGs align

**Fix location:** After line 98, before `compose_confidence()`

---

### 2. choch_reversal.py (Lines 87-105)
**Violation:** Missing `ctf_structure_alignment`, `ctf_trend_alignment`, `ctf_score`

**Current:**
```python
# Uses hmm_regime (binary check)
if direction == 1 and hmm_regime == 1.0:
    raw_conf += 0.2

raw_conf, supporting = apply_exhaustion_boost(features, direction, raw_conf, supporting)
confidence = compose_confidence(raw_conf)
```

**Missing:** Cross-timeframe structure breaks should boost CHoCH confidence

**Fix location:** After line 105, before `compose_confidence()`

---

### 3. liquidity_sweep_reclaim.py (Lines 99-102)
**Violation:** Uses `ctf_score` as binary gate, discards magnitude

**Current:**
```python
ctf_score = features.get("ctf_score", 0.0)
if abs(ctf_score) > 0.3:  # BINARY GATE - magnitude lost!
    confidence += 0.05
    supporting.append("cross_timeframe_aligned")
```

**Impact:** Strong alignment (0.9) gets same boost as weak alignment (0.4)

**Fix:** Weight by magnitude: `confidence += 0.05 * clamp(abs(ctf_score) / 0.5)`

---

### 4. supply_demand_setup.py (Lines 169-172)
**Violation:** Uses `ctf_score` as binary gate, discards magnitude

**Current:**
```python
ctf = float(features.get("ctf_score", 0.0))
if abs(ctf) > 0.3 and math.copysign(1, ctf) == direction:  # BINARY GATE
    confidence += 0.05
    supporting.append("ctf_aligned")
```

**Impact:** Same as liquidity_sweep_reclaim - strong/weak alignment treated equally

**Fix:** Weight by magnitude: `confidence += 0.05 * clamp(abs(ctf) / 0.5)`

## I6 Data Availability Verification

✅ **All I6 scores computed and flowing** (Phase 46 confirmed):
- `ctf_score` - Overall cross-timeframe alignment (-1.0 to +1.0)
- `ctf_trend_alignment` - Trend direction agreement across TFs (0.0 to 1.0)
- `ctf_structure_alignment` - Structure break agreement (0.0 to 1.0)
- `ctf_fvg_alignment` - FVG presence across multiple TFs (0.0 to 1.0)
- `ctf_ob_alignment` - Order block presence across multiple TFs (0.0 to 1.0)

## Correct Usage Pattern (from cis_scorer.py)

```python
# Extract I6 score from features
ctf_trend = float(features.get("ctf_trend_alignment", 0.0))

# Weight and clamp (normalize to 0-1)
weighted_boost = 0.10 * clamp(ctf_trend)

# Add to confidence
confidence += weighted_boost

# Track in supporting factors
if weighted_boost > 0.03:  # Meaningful boost threshold
    supporting.append("ctf_trend_aligned")
```

## Implementation Plan

### Atomic Commit 1: fvg_fill.py
- Add `ctf_fvg_alignment` check
- Add `ctf_ob_alignment` check
- Weight by magnitude (not binary)
- Test: FVG signals should see higher confidence when multi-TF aligned

### Atomic Commit 2: choch_reversal.py
- Add `ctf_structure_alignment` (0.08 weight)
- Add `ctf_trend_alignment` (0.06 weight)
- Add `ctf_score` as directional confirmation (0.05 weight)
- Test: CHoCH signals boosted when multi-TF structure breaks align

### Atomic Commit 3: liquidity_sweep_reclaim.py
- Change binary gate to magnitude-weighted
- Scale boost by alignment strength (0.0 to 0.10 range)
- Test: Strong CTF alignment gets 2x boost vs weak alignment

### Atomic Commit 4: supply_demand_setup.py
- Change binary gate to magnitude-weighted
- Scale boost by alignment strength (0.0 to 0.10 range)
- Test: Same as liquidity_sweep_reclaim

## Expected Impact

- **Signal quality:** Better separation between strong and weak setups
- **Renaissance compliance:** No computed signal data discarded
- **Confidence distribution:** Wider spread (more high-confidence signals when aligned)
- **Zero regressions:** Magnitude weighting is smoother than binary gating

## Verification Plan

1. Run full test suite: `pytest tests/unit/test_<plugin>.py -v`
2. Check shadow capture: I6 scores flow through unchanged
3. Verify confidence distribution: wider spread, higher mean
4. No new signals created (only confidence adjustments)
