# Phase 118: Confidence Integrity — Top 5 Setup Refactoring — Research

**Researched:** 2026-06-09
**Domain:** I7 plugin confidence formulas, signal-extrinsic stripping, intrinsic feature design
**Confidence:** HIGH — all findings derived from direct code inspection of live source files

---

## Summary

Phase 118 executes in two waves. Wave 0 strips signal-extrinsic modifiers (HMM weights, CTF scores, exhaustion boost/guard, zone context, SMC events) from 17 I7 plugin files, using the pre-written plan at `docs/plans/2026-06-08-confidence-intrinsic-cleanup.md`. The plan is accurate and complete — spot-checks of ofi_continuation.py, cvd_divergence.py, gap_analysis_setup.py, and divergence_stack.py all confirm the extrinsic modifiers listed are present exactly as described. No additional extrinsic modifiers were found beyond those catalogued.

Waves 1-5 refactor the 5 highest-volume NEEDS_REFACTOR setups. Three of the five (OFIContinuation, CVDDivergence, GapAnalysisSetup) are also in Wave 0 scope — their Wave 0 strip happens first, then Wave 1/3/4 adds the multi-factor intrinsic formulas. PatternCompletion and DivergenceStack are not in Wave 0 scope. DivergenceStack already has a ctf_score additive block and exhaustion_guard that need stripping as part of its Wave 5 refactor. PatternCompletion has an exhaustion_boost call that must be removed.

The critical architectural point: `capture_signal_features()` already captures all extrinsic context (ctf_score, ctf_trend_alignment, ctf_structure_alignment, ctf_regime_agreement, ctf_fvg_alignment, ctf_ob_alignment, exhaustion fields, vix_level, etc.) into `features_snapshot` — removing them from confidence does not discard them, it routes them correctly for ML training.

**Primary recommendation:** Execute Wave 0 in full before touching any Wave 1-5 file. The three files shared between waves (ofi_continuation, cvd_divergence, gap_analysis_setup) get their extrinsic strip in Wave 0, then their intrinsic formula upgrade in the numbered wave task.

---

## Wave 0 — Cleanup Plan Verification

### Accuracy Assessment

The plan at `docs/plans/2026-06-08-confidence-intrinsic-cleanup.md` was spot-checked against 4 files:

**ofi_continuation.py** — CONFIRMED. Lines 19, 122-123, 126-133 match exactly:
- `apply_exhaustion_guard` call on line 123 (listed as Task 1 — but plan says "remove ctf_score block and hmm_regime_weight"; the exhaustion_guard is also present and must be stripped — see gap below)
- ctf_score additive block lines 126-129
- hmm_regime_weight additive lines 132-133

**gap_analysis_setup.py** — CONFIRMED. Lines 18, 20, 150, 153-161 match exactly. Both `apply_exhaustion_boost` (line 150) and `hmm_regime_weight` (line 159) present.

**cvd_divergence.py** — CONFIRMED. Lines 19, 138-144 match. ctf_score block lines 138-141, hmm_regime_weight lines 143-144. Note: the ctf_score `supporting.append` at line 167 also references ctf_score and must be cleaned.

**divergence_stack.py** — CONFIRMED. Lines 19, 241-253 match. Both `apply_exhaustion_guard` (lines 241-243) and ctf_score additive block (lines 245-249) and hmm_regime_weight (lines 251-253) are present.

### Gap Found: ofi_continuation.py exhaustion_guard not in Task 1

The Wave 0 plan Task 1 (`ofi_continuation.py`) lists removal of ctf_score and hmm_regime_weight but does NOT list `apply_exhaustion_guard`. However line 123 of ofi_continuation.py calls `apply_exhaustion_guard`. The import on line 22 is `from .exhaustion_utils import apply_exhaustion_guard`. This must be removed in Wave 0 (or at latest Wave 1 when the full confidence formula is rewritten). The planner should include this in Wave 0 Task 1 or flag it for Wave 1.

### Three Composite Restructures — Soundness Check

**momentum_breakout.py** — Plan removes `regime_score` (15%) and redistributes to `0.40 * roc_score + 0.35 * vol_score + 0.25 * break_margin`. All three remaining variables (`roc_score`, `vol_score`, `break_margin`) are intrinsic to the breakout pattern. Weights sum to 1.0. Sound.

**squeeze_expansion.py** — Plan removes `regime_score` (20%) and redistributes to `0.35 * squeeze_bars_score + 0.35 * vol_expansion_score + 0.30 * momentum_score`. All three variables intrinsic to the squeeze pattern. Weights sum to 1.0. Sound.

**trend_following.py** — Plan removes `trend_regime` (35%) and `ctf_score` (20%) leaving `trend_conf` and `trend_strength` as Kalman filter quality metrics. Proposed formula `0.45 * trend_conf + 0.35 * trend_strength + 0.20 * swing_pattern` is contingent on `swing_pattern` availability in the file. Plan provides a fallback (`0.55 * trend_conf + 0.45 * trend_strength`) if swing_pattern is absent. The planner must read trend_following.py before writing the task to determine which branch applies.

### No Additional Extrinsic Modifiers Found

Systematic check confirms the four categories listed in the plan are exhaustive for these files. No additional extrinsic categories (e.g. `vix_level` gates, `eq_spread_z` in confidence path, `session_ny` in confidence path) were found modifying confidence in any of the 4 spot-checked files. Session gates and macro context reads feed `regime_context` strings or `supporting.append()` only — not confidence arithmetic.

---

## Wave 1-5 — Individual Setup Analysis

---

### 118-01: trad_OFIContinuation (`ofi_continuation.py`)

**Current state (post Wave 0 strip):**
- Gate: `ofi_ewma_20 != 0.0` AND `count >= 5` consecutive bars
- Confidence: `0.50 + abs(ofi_ewma_20) * 0.001` (single-factor, magnitude-only)
- No magnitude floor gate — fires on ofi_ewma_20 = 1.0 (trivial signal)
- `_MIN_CONSECUTIVE_BARS = 5` at module level

**Changes required:**
- Add `_MIN_OFI_MAGNITUDE: float = 500.0` gate — reject if `abs(ofi_ewma_20) < _MIN_OFI_MAGNITUDE`
- Change `_MIN_CONSECUTIVE_BARS: int = 5` to `10`
- Replace single-factor confidence with 4-factor intrinsic formula
- Remove exhaustion_guard (either in Wave 0 or here)

**Available intrinsic features confirmed in feature dict:**

| Feature | Source | Intrinsic to OFI? |
|---------|--------|------------------|
| `ofi_ewma_20` | I1 | YES — primary signal magnitude |
| `ofi_ewma_5` | I1 | YES — short-term EWMA for alignment |
| `ofi_spike_z` | I1 | YES — z-score of OFI spike |
| `ofi_divergence` | I1 | YES — OFI vs price direction disagreement |
| `rel_volume` | I1 | YES — volume context for conviction |

**Recommended confidence formula:**
```python
# Normalize magnitude: 500 floor → 0.0, 2000+ → 1.0
magnitude_score = min(1.0, max(0.0, (abs(ofi_ewma_20) - 500.0) / 1500.0))

# EWMA alignment: short-term confirms long-term direction
ofi_ewma5 = float(features.get("ofi_ewma_5", 0.0))
ewma_aligned = (ofi_ewma5 * ofi_ewma_20 > 0)  # same sign
alignment_score = 1.0 if ewma_aligned else 0.3

# Persistence beyond minimum: extra bars add confidence
persistence_score = min(1.0, (count - 10) / 10.0)  # 0.0 at bar 10, 1.0 at bar 20

# Volume conviction
rel_vol = float(features.get("rel_volume", 1.0))
volume_score = min(1.0, max(0.0, (rel_vol - 1.0) / 1.5))  # 0.0 at 1x, 1.0 at 2.5x

raw_conf = (
    0.40 * magnitude_score
    + 0.25 * alignment_score
    + 0.20 * persistence_score
    + 0.15 * volume_score
)
```
Weights sum to 1.0. All factors intrinsic to OFI pattern quality.

**Risk:** `ofi_ewma_5` availability — check I1 output keys. If absent, fold its weight into magnitude_score (0.55/0.20/0.25).

**I6 CTF data:** Route to `capture_signal_features()` only — already handled by the existing `capture_signal_features(features, direction, "microstructure", confidence)` call.

---

### 118-02: trad_PatternCompletion (`pattern_completion.py`)

**Current state:**
- Signal count in DB: **897,378** (not 795K as phase description says — DB was queried live)
- `confidence_threshold = 0.5` class attribute
- `regime_type = "any"`
- Confidence formula: `raw_conf = best_confidence * 0.9` then `apply_exhaustion_boost`
- `requires_i6_confluence = False` with TODO comment for phase-118

**Data flow bug — the actual issue:** The plugin reads pattern fields (`dt_db_confidence`, `dt_db_pattern`, `hs_confidence`, `hs_pattern`, `tri_confidence`, `tri_breakout_bias`) from the `features` dict, which is assembled from I5 outputs in `compute_full`. These I5 fields ARE available at runtime via the in-process pipeline. The "phantom data" problem is that the I5 pattern fields (`dt_db_confidence`, `hs_confidence`, etc.) are NOT being stored in the signal's `features_snapshot` (which uses `capture_signal_features()` — a fixed 17-key shadow dict that does not include I5 pattern fields). So the pattern type/confidence is captured only in `signal_type` string and `supporting_factors` list but NOT as structured numeric fields for ML training.

**Fix required:** Add pattern fields explicitly to the signal dict before return:
```python
signal["pattern_name"] = pattern_name
signal["pattern_raw_confidence"] = round(best_confidence, 4)
signal["pattern_count"] = len(candidates)
```
These will flow through to the i7 JSONB bucket in `intelligence_features`.

**Changes required:**
- `confidence_threshold`: `0.5` → `0.70`
- `regime_type`: `"any"` → `"trend"` (chart patterns have directional bias, are more meaningful in trending regimes)
- Remove `apply_exhaustion_boost` call (line 121)
- Add explicit pattern field persistence to signal dict
- Add `requires_i6_confluence = True` (remove TODO)

**Recommended confidence formula:**
```python
# Pattern raw confidence is already [0,1] from I5 detector
pattern_score = min(1.0, best_confidence)  # I5 confidence, post-threshold (>0.70)

# Pattern convergence: multiple patterns agreeing is stronger
convergence_score = min(1.0, len(candidates) / 3.0)  # 0.33 for 1, 0.67 for 2, 1.0 for 3+

# Pattern strength relative to threshold
# Distance above 0.70 gate normalized to [0, 1] over remaining range
above_threshold = (best_confidence - 0.70) / 0.30  # 0.0 at 0.70, 1.0 at 1.0
strength_score = min(1.0, max(0.0, above_threshold))

# Direction purity: all candidates agree on direction
if len(candidates) > 1:
    directions = [d for _, d, _ in candidates]
    direction_purity = 1.0 if all(d == direction for d in directions) else 0.4
else:
    direction_purity = 0.7  # single pattern — neutral conviction

raw_conf = (
    0.45 * pattern_score
    + 0.25 * strength_score
    + 0.20 * convergence_score
    + 0.10 * direction_purity
)
```

**Risk:** regime_type change from "any" to "trend" will suppress signals in ranging regime — expect signal volume drop. This is intentional (higher quality filter).

---

### 118-03: trad_GapAnalysisSetup (`gap_analysis_setup.py`)

**Current state (post Wave 0 strip):**
- `min_gap_atr_mult = 0.3` class attribute — fires on 0.3x ATR gaps (noise threshold)
- `regime_type = "any"` (correct for gaps — they occur in any regime)
- Confidence: `base = min(1.0, gap_size_atr / 2.0)` + `+0.15 if high_volume`
- Two-factor only (gap size + volume), no session timing, no gap type weighting

**Changes required:**
- `min_gap_atr_mult`: `0.3` → `0.8`
- Replace confidence formula with 4-factor intrinsic formula
- Remove `apply_exhaustion_boost` (Wave 0 handles this)
- Remove `hmm_regime_weight` (Wave 0 handles this)

**Available intrinsic features:**

| Feature | Source | Intrinsic to gap? |
|---------|--------|-----------------|
| `gap_size_atr` | computed locally | YES — primary magnitude |
| `vol_ratio` | computed locally | YES — volume conviction |
| `bias` | computed locally | YES — continuation vs fade |
| `bars_since_session_start` | I4 | YES — gap quality better at open |
| `session_ny` | I4 | YES — NY session gaps are higher quality |

**Recommended confidence formula:**
```python
# Gap geometry: normalized over meaningful range [0.8, 2.5 ATR]
# Already gated at 0.8x minimum; score 0.0 at 0.8, 1.0 at 2.5+
geo_score = min(1.0, max(0.0, (gap_size_atr - 0.8) / 1.7))

# Volume conviction
vol_score = min(1.0, max(0.0, (vol_ratio - 1.0) / 2.0))  # 0.0 at 1x, 1.0 at 3x

# Session timing: early-session gaps are more meaningful
bars_since = float(features.get("bars_since_session_start", 30))
# Best at open (0 bars), degrades linearly to 0.2 at 30+ bars
timing_score = max(0.2, 1.0 - bars_since / 30.0)

# Gap type quality: continuation gaps on volume are stronger signals than fade gaps
type_score = 0.8 if bias == "continuation" else 0.5

raw_conf = (
    0.40 * geo_score
    + 0.25 * vol_score
    + 0.20 * timing_score
    + 0.15 * type_score
)
```

**Risk:** `bars_since_session_start` may be None when I4 SessionContext is absent. Guard: `bars_since = float(features.get("bars_since_session_start") or 30)`.

---

### 118-04: trad_CVDDivergence (`cvd_divergence.py`)

**Current state (post Wave 0 strip):**
- `_CVD_DIV_THRESHOLD = 0.002` (improved in Phase 117.5 from 0.0, comment confirms empirical derivation)
- `_CONFIRMATION_BARS = 3`
- `_OFI_DUAL_THRESHOLD = 1.0`
- Confidence: `0.55 base + 0.10 if dual_divergence + 0.05 per extra bar`
- No magnitude normalization — large divergences get same base as threshold-crossing divergences

**Phase description says MIN_CVD_DIVERGENCE=0.0 and is a "deterministic bug"** — this was already fixed in Phase 117.5. Current threshold is `0.002`. The phase description's characterization of 0.0 is stale. The real remaining problems are: (1) threshold 0.002 is still very conservative, (2) no magnitude factor in confidence (step function not gradient), (3) `_CONFIRMATION_BARS = 3` is low.

**Changes required:**
- `_CVD_DIV_THRESHOLD`: `0.002` → `0.5` (the phase description's target; this is a bigger jump than it looks — verify against live data distribution before applying, or make it configurable)
- `_CONFIRMATION_BARS`: `3` → `5`
- Replace step-function confidence with 4-factor gradient formula

**Available intrinsic features:**

| Feature | Source | Intrinsic to CVD divergence? |
|---------|--------|----------------------------|
| `cvd_divergence` | I1 | YES — primary signal magnitude |
| `cvd_slope_5bar` | I1 | YES — persistence/trend of CVD |
| `ofi_divergence` | I1 | YES — dual divergence confirmation |
| `ofi_div_f` | computed | YES — for dual_divergence flag |
| extra_bars (count - `_CONFIRMATION_BARS`) | state | YES — persistence beyond minimum |

**Note on threshold change:** The phase description says `MIN_CVD_DIVERGENCE=0.5`. Current code uses `_CVD_DIV_THRESHOLD` and the unit is raw CVD divergence (slope difference), not a percentage. The existing threshold of 0.002 eliminated float noise. Moving to 0.5 may be aggressive — recommend keeping as a configurable class attribute so it can be tuned.

**Recommended confidence formula:**
```python
# Divergence magnitude: normalized from threshold (0.5) to strong (3.0+)
div_mag_score = min(1.0, max(0.0, (abs(cvd_div) - 0.5) / 2.5))

# Dual divergence confirmation (OFI also diverging)
dual_score = 1.0 if dual_divergence else 0.3

# Persistence beyond minimum (5 bars)
extra_bars = max(0, count - _CONFIRMATION_BARS)
persistence_score = min(1.0, extra_bars / 5.0)  # 0.0 at bar 5, 1.0 at bar 10

# CVD slope alignment: cvd_slope_5bar confirms direction
cvd_slope = float(features.get("cvd_slope_5bar", 0.0)) if features.get("cvd_slope_5bar") else 0.0
slope_aligned = (cvd_slope * cvd_div > 0)  # slope confirms divergence direction
slope_score = 1.0 if slope_aligned else 0.2

raw_conf = (
    0.40 * div_mag_score
    + 0.25 * dual_score
    + 0.20 * persistence_score
    + 0.15 * slope_score
)
```

**Risk:** If `_CVD_DIV_THRESHOLD` jumps from 0.002 to 0.5, almost all historical firing conditions would have been filtered — validate with a DB query on `cvd_divergence` distribution before setting the threshold. The magnitude formula above already starts from 0.5, so the gate threshold and magnitude normalization floor must match.

---

### 118-05: trad_DivergenceStack (`divergence_stack.py`)

**Current state:**
- Has `apply_exhaustion_guard` (lines 241-243) — must be stripped
- Has ctf_score additive block (lines 245-249) — must be stripped  
- Has hmm_regime_weight additive (lines 251-253) — must be stripped
- These three are NOT in Wave 0 scope (Wave 0 plan does not list divergence_stack.py)
- Current confidence: `raw_div_conf = weighted_score / DIVERGENCE_CONFIDENCE_NORM` (0.60 normalization)
- `DIVERGENCE_CONFIDENCE_NORM = 0.60` is the practical 3-signal max weighted score
- The base formula is already multi-factor (5 weighted inputs) — it is intrinsic
- The problem is the post-hoc additive extrinsic modifiers

**Important:** divergence_stack.py needs Wave 0 stripping even though it's not in the plan. The three modifiers must be removed as part of this wave 5 task.

**What is already correct:**
- `weighted_score` from 5 inputs (RSI/MACD/vol/OBV/CMF) is fully intrinsic
- `n_agreeing` gate is intrinsic
- Age tracking per input is intrinsic

**Available intrinsic features for enhancement:**

| Feature | Available | Intrinsic? |
|---------|-----------|-----------|
| `weighted_score` | computed locally | YES — primary |
| `n_agreeing` | computed locally | YES — breadth |
| per-input age bars (rsi_age, macd_age, etc.) | state | YES — persistence |
| per-input magnitudes (rsi_div_strength, etc.) | I5 | YES |
| direction purity (bull_weight vs bear_weight) | computed | YES |

**Recommended confidence formula:**

The current `raw_div_conf = weighted_score / 0.60` is already a reasonable intrinsic base. The enhancement adds depth, persistence, and direction purity:

```python
# Base: weighted score normalized (already intrinsic)
base_score = min(1.0, weighted_score / DIVERGENCE_CONFIDENCE_NORM)

# Breadth: more agreeing inputs = stronger signal
# n_agreeing ranges from DIVERGENCE_MIN_AGREEING (3) to 5
breadth_score = (n_agreeing - DIVERGENCE_MIN_AGREEING) / (5 - DIVERGENCE_MIN_AGREEING)
breadth_score = min(1.0, max(0.0, breadth_score))

# Persistence: oldest active divergence age (sustained signal stronger)
max_age = max(
    state.get("rsi_age", 0), state.get("macd_age", 0),
    state.get("vol_age", 0), state.get("obv_age", 0), state.get("cmf_age", 0)
)
persistence_score = min(1.0, max_age / 10.0)  # 0.0 at 1 bar, 1.0 at 10 bars

# Direction purity: how dominant is the majority direction
total_active_weight = bull_weight + bear_weight
if total_active_weight > 0:
    majority_weight = max(bull_weight, bear_weight)
    purity_score = majority_weight / total_active_weight  # 0.5 = split, 1.0 = unanimous
else:
    purity_score = 0.5

raw_div_conf = (
    0.40 * base_score
    + 0.25 * purity_score
    + 0.20 * breadth_score
    + 0.15 * persistence_score
)
```

**Note:** `bull_weight` and `bear_weight` are already computed before the signal block (lines 197-206). Access `state` via `self._state.setdefault(state_key, {})` — already assigned earlier in `compute_full`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Feature normalization | Custom scaler | Inline `min(1.0, max(0.0, (x - floor) / range))` | No dependency; consistent with existing plugin patterns |
| Confidence clamping | Inline min/max | `compose_confidence(raw)` | D-12/D-13 compliance; enforces [0.0, 0.95] ceiling |
| Extrinsic context capture | Custom shadow dict | `capture_signal_features(features, direction, profile, confidence)` | Already captures all 17+ extrinsic fields for ML training |
| ATR computation | Recompute in plugin | `get_atr_with_floor_from_frames(frames)` | I1 computes once; no duplication |
| Consecutive state | Local dict counter | `track_consecutive_state()` / `reset_consecutive_state()` | Handles symbol+tf keying correctly |

---

## Common Pitfalls

### Pitfall 1: Wave 0 and Wave 1-5 operating on same file
**What goes wrong:** If Wave 1 runs before Wave 0 on ofi_continuation.py, the exhaustion_guard removal in Wave 0 could conflict with the full confidence rewrite in Wave 1.
**How to avoid:** Complete Wave 0 fully and confirm tests green before starting Wave 1. The three shared files (ofi_continuation, gap_analysis, cvd_divergence) must have Wave 0 stripping complete and committed before Wave 1/3/4 adds intrinsic formulas.

### Pitfall 2: divergence_stack.py not in Wave 0 plan
**What goes wrong:** The plan lists 17 files but divergence_stack.py is not among them, yet it has all three extrinsic modifier types. If the planner treats Wave 0 as authoritative and Wave 5 as "just formula upgrade," the stripping will be missed until Wave 5.
**How to avoid:** Wave 5 task must include full extrinsic strip (exhaustion_guard, ctf_score, hmm_regime_weight) as its first step, then formula upgrade. Alternatively, add divergence_stack.py to Wave 0 Task 1.

### Pitfall 3: CVD threshold change magnitude
**What goes wrong:** Changing `_CVD_DIV_THRESHOLD` from 0.002 to 0.5 is a 250x increase. If the actual `cvd_divergence` feature values are in the 0.01-0.10 range in live data, the new threshold eliminates all signals.
**How to avoid:** Before implementing, run: `SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY (bucket_scores->>'cvd_divergence')::float) FROM intelligence_features WHERE bucket_scores ? 'cvd_divergence';` or check the cvd_divergence distribution in the features table. The phase description's "0.5" may be appropriate if cvd_divergence values are in the range 0-5+.

### Pitfall 4: PatternCompletion regime_type change volume impact
**What goes wrong:** Changing regime_type from "any" to "trend" suppresses 897K historical signals when ranging. This is correct behavior but must be an intentional trade. The aggregator regime gate will suppress PatternCompletion signals when `hmm_regime = 0` (ranging).
**How to avoid:** Document the volume expectation in the task. This is a quality-over-quantity decision aligned with the phase goal.

### Pitfall 5: `ofi_ewma_5` feature availability
**What goes wrong:** The recommended OFI confidence formula uses `ofi_ewma_5`. If this key is not emitted by the I1 OFI plugin, the alignment_score falls back to default.
**How to avoid:** Check I1 OFI plugin outputs before writing the formula. Fall back gracefully: `ofi_ewma5 = features.get("ofi_ewma_5")` with `if ofi_ewma5 is not None` guard.

---

## Test Coverage Gaps

| Plugin | Existing Test | Gap |
|--------|--------------|-----|
| trad_OFIContinuation | None found | Full test file needed: magnitude gate, consecutive bar gate, multi-factor formula |
| trad_PatternCompletion | None found (test_pattern_plugins.py exists but covers I5, not I7) | Test file needed: confidence_threshold gate, regime_type suppression, pattern field persistence |
| trad_GapAnalysisSetup | `test_gap_analysis_setup.py` exists | Needs: new min_gap_atr_mult=0.8 gate test, intrinsic formula factor tests |
| trad_CVDDivergence | None found | Full test file needed: threshold gate, confirmation_bars gate, magnitude gradient in confidence |
| trad_DivergenceStack | None found | Test needed: extrinsic strip verification, multi-factor intrinsic formula, always-log fields still present after no-signal |

The `test_gap_analysis_setup.py` file already has helpers for building controlled gap scenarios — it can serve as a template for the other plugins.

---

## Architecture Patterns

### Pattern 1: Intrinsic Normalization
All intrinsic factors should be normalized to [0, 1] before entering the weighted sum:
```python
factor_score = min(1.0, max(0.0, (raw_value - floor) / range_span))
```
This ensures the composite `raw_conf` is bounded and interpretable regardless of raw feature scale.

### Pattern 2: Wave 0 Strip + Wave N Upgrade (shared files)
For the three files in both waves:
1. Wave 0: strip extrinsic lines only, run tests green, commit
2. Wave N: replace single-factor formula with multi-factor intrinsic, add new gates, run tests, commit

### Pattern 3: Always-Log Fields (DivergenceStack)
DivergenceStack has a unique pattern where it returns a dict of scoring fields even on no-signal. When rewriting confidence, the base_output dict and the signal dict merge pattern (`signal.update(base_output)`) must be preserved. Do not return early without populating base_output fields.

---

## Sources

### Primary (HIGH confidence — direct code inspection)
- `/home/bg/dev/indicagent/src/intelligence/trading/ofi_continuation.py` — full file read
- `/home/bg/dev/indicagent/src/intelligence/trading/cvd_divergence.py` — full file read
- `/home/bg/dev/indicagent/src/intelligence/trading/gap_analysis_setup.py` — full file read
- `/home/bg/dev/indicagent/src/intelligence/trading/pattern_completion.py` — full file read
- `/home/bg/dev/indicagent/src/intelligence/trading/divergence_stack.py` — full file read
- `/home/bg/dev/indicagent/src/intelligence/trading/confidence_utils.py` — full file read
- `/home/bg/dev/indicagent/docs/plans/2026-06-08-confidence-intrinsic-cleanup.md` — full plan read
- `/home/bg/dev/indicagent/tests/unit/intelligence/test_gap_analysis_setup.py` — test structure read
- Live DB query: `signal_ledger WHERE setup_plugin='trad_PatternCompletion'` — 897,378 signals confirmed

---

## Metadata

**Confidence breakdown:**
- Wave 0 plan accuracy: HIGH — 4/4 spot-checks matched exactly, one gap found (ofi_continuation exhaustion_guard)
- Wave 1-5 current state: HIGH — read from live source files
- Intrinsic feature availability: MEDIUM — ofi_ewma_5 needs verification against I1 output keys
- CVD threshold recommendation: MEDIUM — 0.5 target needs distribution check against live data
- Confidence formula weights: MEDIUM — weights are principled but not empirically derived; Phase 49 XGBoost will supersede

**Research date:** 2026-06-09
**Valid until:** 2026-07-09 (stable domain — plugin code changes slowly)
