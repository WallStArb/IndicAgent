# I7 Setup Confidence Patterns

**Version:** 1.0
**Status:** current
**Last Updated:** 2026-06-10

---

## 1. Purpose

Every I7 setup plugin has exactly one responsibility: assess whether a pattern has sufficient intrinsic signal strength to justify a trade signal at this bar, for this instrument.

Confidence measures intrinsic signal strength. Regime eligibility is a separate concern. I6 cross-timeframe confirmation is a separate concern. Separating these is the core SoC invariant for I7 signal quality.

This doc defines the 6 GOOD patterns that every compliant I7 setup must implement, the gate threshold values, the zone-friction treatment, and the anti-patterns that silently corrupt signal quality. It is the required reading before authoring any new I7 plugin.

---

## 2. The 6 GOOD Patterns

All compliant I7 setups implement every one of these patterns. Deviation from any pattern requires an explicit architectural decision recorded in the phase CONTEXT.md.

### Pattern 1 - Multi-factor intrinsic confidence composite

Confidence is a weighted sum of domain-specific, clamp01-bounded factors that measure signal strength. All factors are intrinsic to the pattern (price/volume/microstructure derived). No external eligibility signals (HMM regime, I6 CTF scores, zone context) appear in the confidence formula.

Canonical structure (from `OFIContinuationPlugin.compute_full`):

```python
# Each factor individually clamped to [0, 1] before weighting
factor_a = clamp01(...)
factor_b = clamp01(...)
factor_c = clamp01(...)
factor_d = clamp01(...)

# Weights sum to 1.0; written explicitly for auditability
raw_conf = (
    0.40 * factor_a
    + 0.25 * factor_b
    + 0.20 * factor_c
    + 0.15 * factor_d
)

confidence = compose_confidence(raw_conf)
```

The 4-factor structure is the target for most plugins. Two exceptions with 3-factor formulas are documented in Section 6 (MomentumBreakout, VWAPDeviation) - their formulas were audited sound per D-04 and were not rewritten.

### Pattern 2 - requires_i6_confluence=True

Every compliant I7 setup declares `requires_i6_confluence: bool = True` as a ClassVar. This is enforced structurally by `validate_tier()` (see Section 7). The `_I7_I6_EXEMPT` carve-out documents the 8 plugins not yet refactored.

### Pattern 3 - Strict dual gate before OHLCV extraction

Before any OHLCV access (`extract_ohlcv`, `df["close"]`, `.to_numpy()`, `get_atr_with_floor_from_frames`, `frame_trade`), two cheap gates run:

```python
# Gate 1 - regime (cheap):
if hmm_regime_weight(features, self.regime_type) < _MIN_REGIME_WEIGHT:
    return no_signal()

# Gate 2 - I6 (cheap):
ctf_score = float(features.get("ctf_score") or 0.0)
if abs(ctf_score) < _MIN_CTF_SCORE:
    return no_signal()

# Only then: OHLCV extraction (expensive)
df, close, high, low, volume = extract_ohlcv(frames, self.min_lookback)
```

This simultaneously implements both the regime eligibility check and the early gate optimization (Pattern 5).

### Pattern 4 - Continuous hmm_regime_weight (not binary)

HMM regime participation is measured as a continuous probability, not a binary regime state comparison. This reads the actual HMM probability outputs, preserving signal quality in edge states.

Per-regime gate shapes:

| regime_type value | Gate function | What it measures |
|---|---|---|
| `"trend"` | `hmm_regime_weight(features, "up")` for long, `hmm_regime_weight(features, "down")` for short | Probability mass on the directional trending state |
| `"mean_reversion"` | `hmm_regime_weight(features, "ranging")` | Probability mass on the ranging state |
| `"any"` | `hmm_trending_weight(features)` | Max of up/down trending probability |

The `"any"` regime rule is critical - see Anti-patterns (Section 8) for what NOT to do.

### Pattern 5 - Early gate optimization

Cheap gate checks (HMM probability lookup, ctf_score float comparison) run before any expensive operations. The dual gate in Pattern 3 is the primary implementation. Additional domain-specific gates (z-score magnitude checks, consecutive bar counts) also run before OHLCV extraction.

### Pattern 6 - shadow_only=True until Phase 120

Every Phase 119 plugin declares `shadow_only: bool = True` as a ClassVar. Plugins run in shadow mode - firing and logging to `shadow_registry` but not contributing to live signal selection. Promotion to `shadow_only=False` happens in Phase 120 after empirical validation (n >= 100, bootstrap_ci_lower(pnl_r) > 0.0).

---

## 3. Gate Thresholds

These constants are defined at module level in each plugin file for DB-tuneability:

```python
_MIN_REGIME_WEIGHT: float = 0.30   # 30% probability mass on target regime
_MIN_CTF_SCORE: float = 0.25       # I6 cross-timeframe confirmation floor
```

**Z-score gates:** For z-score features (`ofi_spike_z`, `cvd_spike_z`, and similar), the gate is `>= 2.0`. This threshold is statistically grounded (2-sigma) and instrument-agnostic.

**`"any"` regime rule:** Plugins with `regime_type = "any"` MUST use `hmm_trending_weight(features)` for their regime gate. Do NOT pass `"any"` to `hmm_regime_weight` - that returns the 0.5 neutral fallback because `"any"` is not a key in `_HMM_KEY_MAP`. See Anti-patterns (Section 8).

The per-regime gate shapes table in Section 2 Pattern 4 gives the full mapping.

---

## 4. Pattern Vocabulary

Four distinct concepts appear in I7 plugin code. They must not be confused or merged.

| Concept | Definition | Role in confidence | Example |
|---|---|---|---|
| Pre-entry GATE | Continuous probability or score threshold. Below threshold returns `no_signal()`. | Eligibility check - not in confidence | `hmm_regime_weight < 0.30` returns no_signal() |
| CONFIDENCE FACTOR | Intrinsic signal-strength score, clamped to [0,1], weighted into the composite | IS confidence - the only inputs to `raw_conf` | `magnitude_score`, `persistence_score` |
| CAPTURED EXTRINSIC FIELD | Written to `features_snapshot` via `capture_signal_features()` for ML training. Zero confidence modification. | Not in confidence - captured for Phase 49 XGBoost training | `ctf_score`, `vix_level`, `exhaustion_score` in snapshot |
| ZONE FRICTION PENALTY | Zone context from supply/demand proximity. Stripped from confidence in Phase 118 for trend/momentum/liquidity_hunt setups; retained as an intrinsic structural gate only for `SupplyDemandSetup`. | Not one of the 6 GOOD patterns. For `supply_demand_setup`: gates the entry zone, not a confidence factor. For all others: zone context is captured as extrinsic, not scored. | `supply_demand_setup.py` zone gate; captured but not scored in `trend_following.py` |

Zone friction is NOT one of the 6 GOOD patterns. It is a separate architectural concern handled differently per plugin family, documented separately in `test_i7_extrinsic_contract.py`.

---

## 5. Canonical Reference

The primary reference implementation is `src/intelligence/trading/ofi_continuation.py`, class `OFIContinuationPlugin`.

Key symbols to study:

- `OFIContinuationPlugin.shadow_only` - ClassVar declaration, `True`
- `OFIContinuationPlugin.requires_i6_confluence` - ClassVar declaration, `True`
- `OFIContinuationPlugin.regime_type` - `"trend"`, used in the regime gate
- `OFIContinuationPlugin.compute_full` - the 4-factor confidence composite (`magnitude_score`, `alignment_score`, `persistence_score`, `volume_score`) with weights summing to 1.0, wrapped by `compose_confidence()`

Do NOT cite line numbers - line numbers drift after refactors. Reference class names, method names, and ClassVar identifiers.

Secondary references:

- `src/intelligence/trading/liquidity_sweep_reclaim.py` - dual gates + I6 integration + continuous regime weighting
- `src/intelligence/trading/choch_reversal.py` - I6 confluence + zone penalties

---

## 6. Compliant Setups (22 total)

### Phase 118 (5 plugins)

These plugins were refactored in Phase 118 and serve as reference implementations:

| Plugin | File | regime_type | Notes |
|---|---|---|---|
| OFIContinuation | `ofi_continuation.py` | trend | Primary canonical reference |
| PatternCompletion | `pattern_completion.py` | any | |
| GapAnalysisSetup | `gap_analysis_setup.py` | any | |
| CVDDivergence | `cvd_divergence.py` | any | |
| DivergenceStack | `divergence_stack.py` | any | |

### Phase 119 (17 plugins)

Wave 1 (8 plugins) and Wave 2 (9 plugins) refactored in Phase 119:

| Plugin | File | regime_type | Notes |
|---|---|---|---|
| OFISpike | `ofi_spike.py` | any | Wave 1 |
| CVDSpike | `cvd_spike.py` | any | Wave 1 |
| OFIDivergence | `ofi_divergence.py` | any | Wave 1 |
| FailedBreakout | `failed_breakout.py` | any | Wave 1 |
| CandlestickPatternSetup | `candlestick_pattern_setup.py` | any | Wave 1 |
| SessionExtremesSetup | `session_extremes_setup.py` | any | Wave 1 |
| LiquidityHunt | `liquidity_hunt.py` | trend | Wave 1 |
| DeltaExhaustion | `delta_exhaustion.py` | any | Wave 1 |
| LVNBreakout | `lvn_breakout.py` | trend | Wave 2 |
| VWAPReclaim | `vwap_reclaim.py` | any | Wave 2 |
| VWAPDeviation | `vwap_deviation.py` | mean_reversion | Wave 2; 3-factor formula kept per D-04 (sound formula) |
| MomentumBreakout | `momentum_breakout.py` | trend | Wave 2; 3-factor formula kept per D-04 (sound formula) |
| ORB15 | `orb15.py` | any | Wave 2 |
| ORB30 | `orb30.py` | any | Wave 2 |
| SecondLegContinuation | `second_leg_continuation.py` | trend | Wave 2 |
| VCP | `vcp.py` | trend | Wave 2 |
| DualDivergence | `dual_divergence.py` | any | Wave 2 |

### Not yet I6-integrated (deferred)

These 8 plugins are in `_I7_I6_EXEMPT` in `register_plugins.py`. They have `requires_i6_confluence = False` and do not have the dual gate or 4-factor confidence composite. They are deferred to a follow-up phase. `validate_tier()` exempts them explicitly.

| Plugin | File |
|---|---|
| RegimeTransition | `regime_transition.py` |
| PrevDayLevelTest | `prev_day_level_test.py` |
| AnchoredVWAPReversion | `anchored_vwap_reversion.py` |
| POCRejection | `poc_rejection.py` |
| HVNRejection | `hvn_rejection.py` |
| CrossAssetDivergence | `cross_asset_divergence.py` |
| MeanReversion | `mean_reversion.py` |
| SqueezeExpansion | `squeeze_expansion.py` |

The compliant count is 22, not all 37 TIER_I7 plugins. The remaining 7 are the 2 aggregators (`SignalAggregator`, `WeightedSignalAggregator`) plus 5 other non-setup plugins not subject to the confidence integrity requirements.

---

## 7. Enforcement

`validate_tier()` in `src/intelligence/plugins/base.py` enforces the I6 confluence requirement:

```python
# In the I7 block of validate_tier():
if not getattr(plugin, "requires_i6_confluence", None):
    raise ArchitectureViolation(
        f"I7 plugin '{name}' must have requires_i6_confluence=True."
    )
```

Plugins in `_I7_I6_EXEMPT` are explicitly skipped by this check. The exempt set is a documented temporary carve-out - when those 8 plugins are refactored, their names are removed from `_I7_I6_EXEMPT` and the check covers them automatically.

`shadow_only=True` is NOT enforced by `validate_tier()`. Truth lives in the `shadow_registry` DB table (Phase 120 promotions update DB, not plugin ClassVar). Enforcing `shadow_only` in `validate_tier` would create two competing sources of truth.

Test coverage: `tests/unit/intelligence/test_i7_extrinsic_contract.py` asserts the confidence integrity invariants across all compliant I7 plugins.

---

## 8. Anti-patterns

These patterns appear in legacy code and MUST NOT appear in any new or refactored I7 plugin.

### 1. `hmm_regime_weight(features, "any")` - silent 0.5 pass

```python
# WRONG - "any" is not in _HMM_KEY_MAP; returns 0.5 unconditionally
if hmm_regime_weight(features, "any") < _MIN_REGIME_WEIGHT:
    return no_signal()
```

With `_MIN_REGIME_WEIGHT = 0.30`, this gate never fires (0.5 >= 0.30 always). Effectively bypasses regime gating.

```python
# CORRECT for regime_type="any" plugins
if hmm_trending_weight(features) < _MIN_REGIME_WEIGHT:
    return no_signal()
```

### 2. Binary HMM regime equality checks

```python
# WRONG - binary check loses probability information
if hmm_regime in (1, 2):  # trending
    ...
if hmm_regime not in (1.0, 2.0):  # not ranging
    ...
if hmm_regime_prob < 0.5:  # threshold on raw probability
    ...
```

```python
# CORRECT - continuous probability gate
if hmm_regime_weight(features, "up") < _MIN_REGIME_WEIGHT:
    return no_signal()
```

### 3. OHLCV/ATR/frame_trade access before the dual gate

```python
# WRONG - expensive ops before cheap eligibility gates
df, close, high, low, volume = extract_ohlcv(frames, self.min_lookback)
atr = get_atr_with_floor_from_frames(frames)
tf_result = frame_trade(...)

if hmm_regime_weight(features, self.regime_type) < _MIN_REGIME_WEIGHT:
    return no_signal()
```

```python
# CORRECT - gates first, OHLCV after
if hmm_regime_weight(features, self.regime_type) < _MIN_REGIME_WEIGHT:
    return no_signal()
ctf_score = float(features.get("ctf_score") or 0.0)
if abs(ctf_score) < _MIN_CTF_SCORE:
    return no_signal()

df, close, high, low, volume = extract_ohlcv(frames, self.min_lookback)  # now safe
```

### 4. HMM probability as a confidence factor

```python
# WRONG - HMM regime is gate-only; putting it in confidence mixes concerns
hmm_prob = features.get("hmm_prob_trending_up", 0.5)
raw_conf = 0.30 * signal_strength + 0.40 * hmm_prob + ...
```

HMM regime is gate-only. Direction selection may read `hmm_regime` (which direction is trending), but the confidence composite must not include any HMM probability as a factor. Confidence = intrinsic signal strength only.

---

## 7. See Also

- `src/intelligence/trading/ofi_continuation.py` - canonical reference implementation
- `src/intelligence/trading/confidence_utils.py` - `compose_confidence()`, `clamp01()`, `capture_signal_features()`
- `src/intelligence/utils/gradient_utils.py` - `hmm_regime_weight()`, `hmm_trending_weight()`
- `src/intelligence/register_plugins.py` - `TIER_I7`, `_I7_I6_EXEMPT`, `_PHASE_119_PLUGINS`
- `src/intelligence/plugins/base.py` - `validate_tier()`, `ArchitectureViolation`
- `tests/unit/intelligence/test_i7_extrinsic_contract.py` - extrinsic vs intrinsic contract tests
- `.planning/phases/119-remaining-16-setup-refactoring/119-CONTEXT.md` - D-01, D-02, D-03, D-04 decisions
