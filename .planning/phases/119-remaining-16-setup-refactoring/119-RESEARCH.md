# Phase 119: Remaining 16 Setup Refactoring - Research

**Researched:** 2026-06-10
**Domain:** I7 trading plugin refactoring — confidence integrity, dual gate enforcement, I6 integration
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01: hmm_regime_weight — Pre-entry gate only**
`hmm_regime_weight()` is used as a pre-entry eligibility gate, NOT as a confidence formula factor.
Gate: `if hmm_regime_weight(features, self.regime_type) < _MIN_REGIME_WEIGHT: return no_signal()`
`_MIN_REGIME_WEIGHT = 0.30`

**D-02: validate_tier() Enforcement**
Add exactly one new check to the I7 block:
```python
if not getattr(plugin, "requires_i6_confluence", None):
    raise ArchitectureViolation(
        f"I7 plugin '{name}' must have requires_i6_confluence=True. "
        f"Phase 119 requires all I7 setups consume I6 cross-timeframe data."
    )
```

**D-03: Dual Gate Structure + Threshold Values**
```python
# Gate 1 (regime — cheap):
if hmm_regime_weight(features, self.regime_type) < _MIN_REGIME_WEIGHT:  # 0.30
    return no_signal()
# Gate 2 (I6 — cheap):
ctf_score = float(features.get("ctf_score") or 0.0)
if abs(ctf_score) < _MIN_CTF_SCORE:  # 0.25
    return no_signal()
# Then: OHLCV extraction (expensive)
```
Z-score features (`ofi_spike_z`, `cvd_spike_z`): gate at `>= 2.0` — statistically grounded.

**D-04: MomentumBreakout Scope**
MomentumBreakout 3-factor confidence formula is sound — keep as-is. Add gates only: `shadow_only=True`, regime gate, I6 early gate, `requires_i6_confluence=True`.

### Claude's Discretion
None — discussion stayed within phase scope.

### Deferred Ideas (OUT OF SCOPE)
None.
</user_constraints>

---

## Summary

Phase 119 applies 6 GOOD patterns to all 17 remaining NEEDS_REFACTOR I7 plugins. Phase 118 established the pattern on OFIContinuation, PatternCompletion, GapAnalysisSetup, CVDDivergence, and DivergenceStack. This phase completes the work across two waves: Wave 1 (8 setups) and Wave 2 (9 setups including MomentumBreakout).

All 17 target plugins currently have `requires_i6_confluence: bool = False` with `# TODO(phase-118)` comments, except LiquidityHunt which already has `requires_i6_confluence: bool = True` (but still needs `shadow_only=True` and the dual gate). The `validate_tier()` function currently checks that `requires_i6_confluence` attribute EXISTS but does NOT enforce that it equals `True` — adding that enforcement check is a key deliverable of this phase.

The OFISpike and CVDSpike plugins delegate entirely to `detect_spike_signal()` in `microstructure_utils.py`. That shared function already assembles a `features` dict from all frame tiers including `i6`, already checks `ctf_score`, and already calls `hmm_regime_weight` in confidence (additive pattern — which must be moved to a gate). Refactoring these two plugins therefore means refactoring `detect_spike_signal()` directly to add the dual gate before OHLCV extraction and strip the hmm/ctf additive confidence contributions.

**Primary recommendation:** Wave 1 and Wave 2 are independent and can proceed in parallel. OFISpike + CVDSpike share a helper function (`detect_spike_signal`) that needs its own targeted refactor rather than plugin-level changes. All other plugins are standalone and can be batched into task groups by structural similarity.

---

## Per-Plugin State Audit

### Wave 1: 8 Plugins

| Plugin | `shadow_only` | `requires_i6_confluence` | Regime gate type | I6 gate | Confidence formula | OHLCV order |
|--------|-----------|---------------------|-----------------|---------|-------------------|-------------|
| OFIDivergence | MISSING | `False` + TODO | Binary `hmm_regime` comparison for regime_ctx string only; no gate | None | `0.42 + 0.25*tanh(peak) + 0.08 + 0.06 + 0.06` — additive, not intrinsic composite | Features first, no OHLCV extraction |
| OFISpike | MISSING | `False` + TODO | `hmm_regime_weight` additive in confidence (+0.10*(w-0.5)) | `ctf_score` additive in confidence (+0.15*...) | Single-factor z-score: `0.50 + abs(z)*0.05` + additive hmm/ctf | Delegated to `detect_spike_signal()` |
| CVDSpike | MISSING | `False` + TODO | Same as OFISpike (shared `detect_spike_signal`) | Same as OFISpike | Same as OFISpike | Delegated to `detect_spike_signal()` |
| CandlestickPatternSetup | MISSING | `False` + TODO | `trend_regime` binary string gate (`abs >= 0.5`) — NOT hmm_regime_weight | None | `base_conf + 0.10 + 0.10 + exhaustion_boost` — pattern-weight + additive | OHLCV extracted FIRST (line 118), before any gate |
| FailedBreakout | MISSING | `False` + TODO | Binary `hmm_regime == 0.0` check for confidence modifier only; no gate | None | `0.55 + 0.15 if ranging` — single-factor binary | Features first, no OHLCV extraction |
| LiquidityHunt | MISSING | `True` (already!) | None | None (ctf_score not checked) | `0.55 + tiered significance boost` — single-factor | `extract_ohlcv` FIRST (line 53), before any gate |
| DeltaExhaustion | MISSING | `False` + TODO | None | None | `0.45 + abs(z)*0.05 + (1-pfr)*0.10` — two-factor | `df` access for close before regime check |
| SessionExtremesSetup | MISSING | `False` + TODO | `trend_regime` directional check for supporting factor only; no gate | None | `0.45 + 0.15*len(supporting)` — count-based | `df.close` accessed before any cheap gate |

### Wave 2: 9 Plugins

| Plugin | `shadow_only` | `requires_i6_confluence` | Regime gate type | I6 gate | Confidence formula | OHLCV order |
|--------|-----------|---------------------|-----------------|---------|-------------------|-------------|
| LVNBreakout | MISSING | `False` + TODO | Binary `hmm_regime in (1, 2)` — integer equality check | None | 4-factor composite: `0.30*vol_score + 0.25*trend_clarity + 0.25*lvn_inverse + 0.20*close_strength` — ALREADY COMPLIANT in structure, weights sum to 1.0 | `df` accessed for volume/OHLCV inside the regime gate |
| ORB15 | MISSING | `False` + TODO | None (regime is informational only) | None | `0.50 + gap_boost` — single-factor | `df.close` extracted before any regime check |
| ORB30 | MISSING | `False` + TODO | None (same as ORB15) | None | `0.50 + gap_boost` — single-factor | Same as ORB15 |
| SecondLegContinuation | MISSING | `False` + TODO | Binary `hmm_regime not in (1.0, 2.0)` gate — integer equality | None | `0.55 + 0.10 if hmm_prob>0.75 + 0.05 if near 50%` — partially intrinsic but uses binary hmm | `df` accessed for close AFTER regime gate |
| VCP | MISSING | `False` + TODO | Binary `hmm_regime not in (1.0, 2.0)` + `hmm_regime_prob < 0.60` gate | None | `0.50 + 0.08 + 0.07` — single-factor with binary bonus | State/regime gates before OHLCV |
| VWAPReclaim | MISSING | `False` + TODO | Binary `hmm` check for confidence scoring (trend_align) | None | 4-factor composite: `0.30*vol_score + 0.30*duration_score + 0.20*trend_align + 0.20*sr_prox` — ALREADY COMPLIANT in structure | VWAP feature check before OHLCV extraction |
| DualDivergence | MISSING | `False` + TODO | None (binary `hmm_regime` for regime_context string only) | None | `0.60 + abs(ofi_div)*0.05 + abs(cvd_div)*0.05` — single-factor additive | Features first, no OHLCV extraction |
| VWAPDeviation | MISSING | `False` + TODO | `garch_vol_regime` gate + `vwap_std` gate but no hmm gate | None | 3-factor: `0.40*dev_score + 0.35*regime_compat + 0.25*vol_contraction` — ALREADY COMPLIANT in structure | `extract_ohlcv` FIRST (line 60), before any gate |
| MomentumBreakout | MISSING | `False` + TODO | None | None | 3-factor: `0.40*roc_score + 0.35*vol_score + 0.25*break_margin` — ALREADY COMPLIANT per D-04 | `extract_ohlcv` FIRST (line 58), before gates |

---

## Architecture Patterns

### The 6 GOOD Patterns (Required for All 17)

**Pattern 1: `shadow_only=True`**
Add as explicit ClassVar. Not inherited — must be explicitly declared per plugin.
```python
shadow_only: bool = True  # shadow mode until Phase 120 promotes
```

**Pattern 2: `requires_i6_confluence=True`**
Replace `requires_i6_confluence: bool = False  # TODO(phase-118): integrate I6 confluence`
with:
```python
requires_i6_confluence: bool = True
```

**Pattern 3: Dual gate before OHLCV extraction**

For plugins whose `regime_type` is `"trend"`:
```python
from ..utils.gradient_utils import hmm_regime_weight

_MIN_REGIME_WEIGHT: float = 0.30
_MIN_CTF_SCORE: float = 0.25

# Gate 1 (regime — cheap):
if hmm_regime_weight(features, "up") < _MIN_REGIME_WEIGHT and \
   hmm_regime_weight(features, "down") < _MIN_REGIME_WEIGHT:
    return no_signal()
```

For `"mean_reversion"`:
```python
if hmm_regime_weight(features, "ranging") < _MIN_REGIME_WEIGHT:
    return no_signal()
```

For `"any"` regime:
```python
# Any regime — use trending probability for either direction
from ..utils.gradient_utils import hmm_trending_weight
if hmm_trending_weight(features) < _MIN_REGIME_WEIGHT:
    # For "any" regime, also accept ranging
    if hmm_regime_weight(features, "ranging") < _MIN_REGIME_WEIGHT:
        return no_signal()
```

Gate 2 (I6 — cheap, applies to all):
```python
ctf_score = float(features.get("ctf_score") or 0.0)
if abs(ctf_score) < _MIN_CTF_SCORE:
    return no_signal()
```

Then: expensive OHLCV extraction.

**Note on "any" regime plugins:** OFISpike, CVDSpike, OFIDivergence, VWAPReclaim, DualDivergence have `regime_type="any"`. The D-01 gate is `hmm_regime_weight(features, self.regime_type) >= 0.30`. For `"any"`, the mapping in `_HMM_KEY_MAP` has no key for `"any"` — `hmm_regime_weight(features, "any")` returns the 0.5 neutral fallback. The planner must decide the correct direction string. Options: use `hmm_trending_weight()` (max of up/down) for trend-biased "any" setups, or skip regime gate for truly regime-agnostic setups and rely on I6 gate alone. This is a planning decision; document below in Open Questions.

**Pattern 4: Multi-factor intrinsic confidence**
4 named score variables, explicit weights summing to 1.0, all factors clamped to [0,1] before weighting.
See OFIContinuation lines 138-162 as the canonical template.

**Pattern 5: Named `_MIN_*` constants**
All feature-scale thresholds named at module level (not inline literals):
```python
_MIN_REGIME_WEIGHT: float = 0.30
_MIN_CTF_SCORE: float = 0.25
_MIN_DIVERGENCE: float = 1.5  # existing — keep
```

**Pattern 6: `compose_confidence()` wraps final value**
Already present in all 17 plugins. No change needed.

---

### Reference Implementations

**`ofi_continuation.py`** — Primary reference. 4-factor intrinsic composite, `shadow_only=True`, `requires_i6_confluence=True`, named constants, no regime gate (uses magnitude gate instead — but dual gate should be modeled from D-03 decisions).

**`microstructure_utils.detect_spike_signal()`** — Contains the current `hmm_regime_weight` additive confidence pattern that needs to become a gate. The refactor: remove `regime_w` additive term from `raw`, add dual gate before ATR/OHLCV extraction.

**`liquidity_sweep_reclaim.py`** — Shows `requires_i6_confluence=True` but does NOT have the dual gate yet (it uses `sweep_detected/sweep_reclaimed` gates which are domain-specific cheap checks). Can use as reference for I6-aware confidence boosts.

---

## Plugin Batching by Structural Similarity

### Batch A: Pure refactor, no helpers (Wave 1)
**OFIDivergence, FailedBreakout** — standalone, direct feature dict access, no OHLCV extraction, simple state machines. New confidence formula needed. OFIDivergence: tanh-based `peak_abs` + persistence + ewma_alignment + volume. FailedBreakout: reversal_magnitude + bars_since_bos + hmm_ranging_alignment + volume.

### Batch B: Session plugins with similar gate structure (Wave 1 + Wave 2)
**CandlestickPatternSetup, SessionExtremesSetup, ORB15, ORB30** — all use `extract_ohlcv` or direct `df["close"]` access BEFORE any regime check. Must move dual gate before OHLCV. Session plugins already have domain-specific gates (session timing, proximity) that remain after the new dual gate.

### Batch C: Spike plugins via shared helper (Wave 1)
**OFISpike, CVDSpike** — both delegate entirely to `detect_spike_signal()`. The refactor target is the helper function, not the plugin classes. After fixing `detect_spike_signal`, both plugins get the fix for free. The helper must: (1) add dual gate before ATR access, (2) move ctf_score check to gate, (3) remove hmm_regime_weight additive from confidence, (4) build 4-factor intrinsic confidence.

### Batch D: LiquidityHunt (special case, Wave 1)
Already has `requires_i6_confluence=True`. Needs: `shadow_only=True`, add dual gate before `extract_ohlcv` (currently line 53 is OHLCV-first), replace confidence formula with 4-factor intrinsic.

### Batch E: DeltaExhaustion (special case, Wave 1)
Uses `profile_name="exempt_exhaustion"` — preserves this in `capture_signal_features`. Confidence is z-score based (cvd_spike_z magnitude + price_follow_ratio). New 4-factor: `cvd_z_score` + `price_fail_score` + `hmm_mean_reversion_score` (regime alignment factor) + `ctf_score_factor`. Note: DeltaExhaustion IS the exhaustion detector — does not use `apply_exhaustion_boost/guard`.

### Batch F: LVNBreakout (Wave 2 — already 4-factor)
Confidence formula is ALREADY a 4-factor weighted composite (lines 186-188, weights sum to 1.0). Needs: `shadow_only=True`, `requires_i6_confluence=True`, dual gate before OHLCV (currently accesses `df` for volume INSIDE the regime gate). Regime gate already binary; replace with `hmm_regime_weight`.

### Batch G: VWAPReclaim, VWAPDeviation (Wave 2 — already 4-factor)
Both have compliant confidence formulas. Need: `shadow_only=True`, `requires_i6_confluence=True`, dual gate (VWAPDeviation has `extract_ohlcv` FIRST — must move gate before it).

### Batch H: VCP, SecondLegContinuation (Wave 2 — partially compliant gates)
VCP already has binary regime gate + HMM prob check; replace with `hmm_regime_weight`. SecondLegContinuation has binary regime gate. Both need new 4-factor confidence.

### Batch I: DualDivergence (Wave 2)
Confidence is additive magnitudes. New 4-factor: ofi_divergence_score + cvd_divergence_score + confirmation_bars_score + volume_score.

### Batch J: MomentumBreakout (Wave 2 — gates only, D-04)
3-factor confidence unchanged. Only adds: `shadow_only=True`, `requires_i6_confluence=True`, dual gate before `extract_ohlcv` (currently OHLCV-first at line 58).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| Regime probability extraction | Custom HMM key lookup | `hmm_regime_weight(features, direction)` from `gradient_utils.py` |
| Trending regime in either direction | `max(up, down)` inline | `hmm_trending_weight(features)` from `gradient_utils.py` |
| Confidence ceiling | `min(0.95, raw)` inline | `compose_confidence(raw)` from `confidence_utils.py` |
| Per-factor clamping | `min(1.0, max(0.0, x))` inline | `clamp01(x)` from `confidence_utils.py` |
| Feature snapshot for ML | Custom dict building | `capture_signal_features(features, direction, profile, confidence)` |
| OHLCV array extraction | `df["close"].to_numpy()` repeated | `extract_ohlcv(frames, min_lookback)` from `plugin_utils.py` |

---

## Common Pitfalls

### Pitfall 1: OHLCV extraction before dual gate
**What goes wrong:** `extract_ohlcv()` or `df["close"].to_numpy()` called at the TOP of `compute_full()` before the dual gate. The dual gate provides "early gate optimization" — this is lost if OHLCV extraction happens first.
**Plugins affected:** CandlestickPatternSetup (line 118), VWAPDeviation (line 60), MomentumBreakout (line 58), LiquidityHunt (line 53), SessionExtremesSetup (close access before session check — but session gate IS a cheap check at the top).
**Fix:** Move dual gate insertion to BEFORE the first OHLCV/expensive access, AFTER the cheap feature reads.

### Pitfall 2: `features` dict assembled too late
**What goes wrong:** Some plugins read `df` first, then assemble the `features` dict from frames. The features dict must be assembled BEFORE the dual gate runs.
**Affected:** Multiple plugins build features dict after checking `df is None`.
**Fix:** Assemble features dict immediately after `frames.get("main")` null check, then run dual gate on features, then extract OHLCV.

### Pitfall 3: `hmm_regime_weight` for `"any"` regime
**What goes wrong:** `hmm_regime_weight(features, "any")` returns 0.5 (neutral fallback) because `"any"` is not in `_HMM_KEY_MAP` (`{"up", "down", "ranging"}`). Using `self.regime_type` directly for "any" plugins will always pass the gate.
**Affected:** OFISpike, CVDSpike (`regime_type="any"`), OFIDivergence (`regime_type="any"`), VWAPReclaim (`regime_type="any"`), DualDivergence (`regime_type="mean_reversion"`), SessionExtremesSetup (`regime_type="mean_reversion"`), CandlestickPatternSetup (`regime_type="any"`).
**Fix:** For `"any"` regime plugins, use `hmm_trending_weight(features)` as the regime gate (checks max of up/down). This gates out genuinely low-probability regime bars while allowing any direction.

### Pitfall 4: `detect_spike_signal` is a shared function, not a class
**What goes wrong:** OFISpike and CVDSpike can't be refactored without touching the shared helper. Changing only the plugin classes leaves the helper unchanged and both plugins still use the old pattern.
**Fix:** Refactor `detect_spike_signal()` directly. Both plugin classes will pick up the fix without any changes to their own code (they delegate entirely).

### Pitfall 5: LiquidityHunt already has `requires_i6_confluence=True` but misses `shadow_only`
**What goes wrong:** If `shadow_only` is assumed to follow `requires_i6_confluence`, LiquidityHunt gets missed.
**Fix:** Treat LiquidityHunt explicitly as needing `shadow_only=True` added plus dual gate — do not skip it due to partial compliance.

### Pitfall 6: `validate_tier()` currently checks attribute EXISTENCE, not value
**Current code (line 148-153):**
```python
if not hasattr(plugin, "requires_i6_confluence"):
    raise ArchitectureViolation(...)
```
This only catches MISSING attribute, not `requires_i6_confluence=False`.
**Fix per D-02:** Change to `if not getattr(plugin, "requires_i6_confluence", None)` — catches both missing attribute AND False value.

### Pitfall 7: DeltaExhaustion uses `exempt_exhaustion` profile
**What goes wrong:** If `apply_exhaustion_boost` is accidentally added to DeltaExhaustion, it creates circular logic (signal is the detector).
**Fix:** DeltaExhaustion must NOT call `apply_exhaustion_boost` or `apply_exhaustion_guard`. Profile stays `"exempt_exhaustion"`. This is already correct in the current code but must be preserved.

### Pitfall 8: Confidence now lower — gates reduce fire rate
**What goes wrong:** After adding dual gate, some plugins will rarely fire in backtests because `hmm_prob_*` fields may not be populated in historical data.
**This is expected behavior:** Shadow mode captures near-misses. All 17 plugins are `shadow_only=True` — they don't affect live trading until Phase 120 promotes them.

---

## Code Examples

### Dual gate insertion template (for standalone plugins)
```python
# Source: D-03 decision from 119-CONTEXT.md
from ..utils.gradient_utils import hmm_regime_weight, hmm_trending_weight

_MIN_REGIME_WEIGHT: float = 0.30
_MIN_CTF_SCORE: float = 0.25

def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
    df = frames.get("main")
    features = {
        **(frames.get("i1") or {}),
        # ... all tiers including i6
        **(frames.get("i6") or {}),
    }
    if df is None or len(df) < self.min_lookback:
        return no_signal()

    # Gate 1 (regime — cheap):
    if hmm_regime_weight(features, self.regime_type) < _MIN_REGIME_WEIGHT:
        return no_signal()

    # Gate 2 (I6 — cheap):
    ctf_score = float(features.get("ctf_score") or 0.0)
    if abs(ctf_score) < _MIN_CTF_SCORE:
        return no_signal()

    # Expensive: OHLCV extraction here
    atr = get_atr_with_floor_from_frames(frames)
    ...
```

### For `regime_type="any"` plugins (use hmm_trending_weight)
```python
# For plugins where regime_type="any" — gate on any trending probability
if hmm_trending_weight(features) < _MIN_REGIME_WEIGHT:
    return no_signal()
```

### 4-factor confidence template
```python
# Source: ofi_continuation.py lines 138-162
factor_a_score = clamp01((raw_value - threshold) / scale)
factor_b_score = clamp01(...)  # 0.0-1.0
factor_c_score = clamp01(...)
factor_d_score = clamp01(...)

raw_conf = (
    0.40 * factor_a_score
    + 0.25 * factor_b_score
    + 0.20 * factor_c_score
    + 0.15 * factor_d_score
)
confidence = compose_confidence(raw_conf)
```

### detect_spike_signal refactor (OFISpike + CVDSpike)
```python
# Current (BAD): hmm and ctf additive in confidence
raw = 0.50 + abs(spike_z) * 0.05
ctf_score = float(features.get("ctf_score", 0.0))
if abs(ctf_score) > 0.3:
    raw += 0.15 * min(1.0, abs(ctf_score) / 0.7)
regime_w = hmm_regime_weight(features, ...)
raw += 0.10 * (regime_w - 0.5)

# Target (GOOD): dual gate, 4-factor intrinsic
if hmm_trending_weight(features) < _MIN_REGIME_WEIGHT:
    return no_signal()
ctf_score = float(features.get(spike_feature_key + "_ctf_or_whatever") or 0.0)  # use ctf_score
if abs(ctf_score) < _MIN_CTF_SCORE:
    return no_signal()
# then ATR access, then 4-factor confidence
z_score_score = clamp01((abs(spike_z) - 2.0) / 3.0)  # z excess above 2σ gate
...
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|-----------------|--------------|--------|
| Binary `hmm_regime == 0/1/2` checks | `hmm_regime_weight(features, direction)` continuous probability | Phase 118 | Enables probability-based gating |
| Regime weight additive in confidence | Regime weight as pre-entry gate only | Phase 118/119 (D-01) | SoC: confidence = intrinsic signal strength |
| CTF score additive in confidence | CTF score as mandatory gate | Phase 119 (D-03) | Eliminates low-confluence noise signals |
| `requires_i6_confluence=False` + TODO | `requires_i6_confluence=True` enforced by validate_tier | Phase 119 (D-02) | Architectural invariant, not a flag |
| No `shadow_only` declaration | Explicit `shadow_only=True` | Phase 119 | All refactored setups start in shadow mode |

---

## Open Questions

1. **`hmm_regime_weight` for `"any"` regime plugins**
   - What we know: `_HMM_KEY_MAP` has keys `"up"`, `"down"`, `"ranging"` only. `hmm_regime_weight(features, "any")` returns 0.5 always.
   - What's unclear: Should `"any"` regime plugins use `hmm_trending_weight()` (max of up/down), always pass the regime gate (rely on I6 gate only), or use a different strategy?
   - Recommendation: Use `hmm_trending_weight(features)` for trend-biased "any" setups (OFISpike, CVDSpike, OFIDivergence, DualDivergence) — they detect order flow which is directional. For session setups (CandlestickPatternSetup with `regime_type="any"`), use `hmm_trending_weight`. VWAPReclaim uses its own trend_align scoring that already uses HMM internally; use `hmm_trending_weight` for gate consistency.

2. **OFIDivergence `regime_type="any"` with no intrinsic regime bias**
   - The plugin fires in ANY regime per design ("let outcome data decide"). Using `hmm_trending_weight >= 0.30` as gate would block ranging markets. Given the plugin's design intent, the gate could be: accept if EITHER trending OR ranging has probability >= 0.30. This effectively means: `max(hmm_trending_weight(f), hmm_regime_weight(f, "ranging")) >= 0.30`. This is almost always true unless HMM data is missing.
   - Recommendation: For truly regime-agnostic setups, rely on I6 gate (ctf_score >= 0.25) as the primary meaningful gate. Add a minimal regime gate: `hmm_trending_weight(features) < 0.30 AND hmm_regime_weight(features, "ranging") < 0.30` — i.e., only block if ALL regime probabilities are low (HMM data absent or degenerate). Plan can decide.

3. **ORB15/ORB30 confidence formula redesign**
   - Currently `0.50 + gap_boost` (one factor). A 4-factor formula needs intrinsic signal strength factors.
   - Candidates: (1) breakout margin above range (close - orb_high) / ATR, (2) volume expansion ratio, (3) gap alignment score, (4) range width score (tighter range = cleaner breakout). Planner derives weights.

4. **VCP confidence redesign**
   - Currently `0.50 + binary bonuses`. Contraction count and HMM prob are already meaningful factors.
   - 4-factor candidates: contraction_count_score, hmm_prob_score, volume_expansion_score, breakout_margin_score.

---

## Infrastructure Verified

### `validate_tier()` line numbers
- **File:** `src/intelligence/plugins/base.py`
- **Existing `requires_i6_confluence` check:** lines 148-153
- **New enforcement check location:** After line 153 (add `requires_i6_confluence=True` value check)
- **Current code checks attribute EXISTS — new code checks attribute exists AND is True**

### `hmm_regime_weight` import path
```python
from ..utils.gradient_utils import hmm_regime_weight, hmm_trending_weight
```
Already used in `microstructure_utils.py` via this path.

### Confidence utils imports
```python
from .confidence_utils import capture_signal_features, clamp01, compose_confidence
```

### Test file location
`tests/unit/intelligence/test_i7_extrinsic_contract.py`
- Currently covers 15 plugins (Wave 0 blast radius from Phase 118)
- Skips ORB15, ORB30 (session timing gate), FailedBreakout (BOS state machine)
- Must add: `shadow_only=True` and `requires_i6_confluence=True` assertion for all 17 plugins
- Must add: new scenario factories for the 17 Wave 1/2 plugins that can fire
- The extrinsic perturbation test will need updating: after Phase 119, the dual gate means `ctf_score` IS now a gate (not just captured). The test must NOT perturb ctf_score for Phase 119 plugins since that would block the signal.

### TIER_I7 membership
All 17 target plugins are in `TIER_I7` in `register_plugins.py` — no changes needed there.

---

## Sources

### Primary (HIGH confidence)
- `src/intelligence/trading/ofi_continuation.py` — reference implementation (Phase 118 GOOD pattern)
- `src/intelligence/trading/microstructure_utils.py` — detect_spike_signal shared helper
- `src/intelligence/plugins/base.py` — validate_tier() current implementation
- `src/intelligence/utils/gradient_utils.py` — hmm_regime_weight, hmm_trending_weight
- `src/intelligence/trading/confidence_utils.py` — compose_confidence, clamp01, capture_signal_features
- `.planning/phases/119-remaining-16-setup-refactoring/119-CONTEXT.md` — D-01, D-02, D-03, D-04

### Secondary (MEDIUM confidence)
- All 17 target plugin files — current state audited directly

---

## Metadata

**Confidence breakdown:**
- Per-plugin state audit: HIGH — directly read from source files
- Gate patterns: HIGH — verified against Context decisions and reference implementations
- Confidence formula redesign for ORB15/ORB30/VCP: MEDIUM — candidates identified, weights are planner decisions
- "any" regime gate strategy: MEDIUM — one open question, recommendation provided

**Research date:** 2026-06-10
**Valid until:** Stable — plugin code does not change frequently; valid until Phase 119 planning is complete
