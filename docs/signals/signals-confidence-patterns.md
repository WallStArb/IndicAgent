# Setup Confidence Patterns

**Version:** 2.0
**Status:** current
**Last Updated:** 2026-06-14

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

### Pattern 3 - Single regime gate before OHLCV; ECL annotation after

Before any OHLCV access (`extract_ohlcv`, `df["close"]`, `.to_numpy()`, `get_atr_with_floor_from_frames`, `frame_trade`), the regime gate runs. The I6 CTF score is NOT a gate — it is an ECL annotation carried on the emitted signal (see Section 5 — ECL).

```python
# Gate - regime only (cheap, stateless, no OHLCV):
if hmm_regime_weight(features, self.regime_type) < _MIN_REGIME_WEIGHT:
    return no_signal()

# Only then: OHLCV extraction (expensive)
df, close, high, low, volume = extract_ohlcv(frames, self.min_lookback)

# ... intrinsic factor computation ...

# ECL annotation - never gates, always present on emitted signal:
_ctf_raw = features.get("ctf_score")
ctf_score: float | None = float(_ctf_raw) if _ctf_raw is not None else None
ctf_confirmed: bool | None = (abs(ctf_score) >= _MIN_CTF_SCORE) if ctf_score is not None else None
_zf_raw = features.get("zone_friction_score")
zone_friction_score: float | None = float(_zf_raw) if _zf_raw is not None else None

# factor_scores - intrinsic breakdown before compositing (ML attribution):
factor_scores = {
    "factor_a": round(factor_a, 4),
    "factor_b": round(factor_b, 4),
    ...
}
raw_conf = 0.40 * factor_a + 0.25 * factor_b + ...
```

**None semantics:** `ctf_score = None` means I6 had no data at emit time (cold-start, warm-up window). `ctf_score = 0.0` means genuine neutral alignment — these are different populations. Never use `features.get("ctf_score") or 0.0`; that conflates them.

This simultaneously implements the regime eligibility check (Pattern 5) and the ECL annotation requirement.

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

Cheap gate checks (HMM probability lookup) run before any expensive operations. The regime gate in Pattern 3 is the primary implementation. Additional domain-specific gates (z-score magnitude checks, consecutive bar counts) also run before OHLCV extraction.

Note: `ctf_score float comparison` was a gate in the pre-Phase-123 CTF-gate pattern (now Anti-pattern 1). Post-Phase-123, `ctf_score` is only compared against `_MIN_CTF_SCORE` to compute the `ctf_confirmed` ECL annotation — it is never an emission gate.

### Pattern 6 - shadow_only=True until Phase 120

Every Phase 119 plugin declares `shadow_only: bool = True` as a ClassVar. Plugins run in shadow mode - firing and logging to `shadow_registry` but not contributing to live signal selection. Promotion to `shadow_only=False` happens in Phase 120 after empirical validation (n >= 100, bootstrap_ci_lower(pnl_r) > 0.0).

---

## 3. Gate Thresholds and APR

These constants are defined at module level in each plugin file. By Phase 125 they are loaded from the Adaptive Parameter Registry (APR) via `ConfigService.get_sync()`:

```python
_MIN_REGIME_WEIGHT: float = 0.30   # 30% probability mass on target regime (APR: threshold.global.min_regime_weight)
_MIN_CTF_SCORE: float = 0.25       # I6 cross-timeframe annotation threshold (APR: threshold.global.min_ctf_score)
```

`_MIN_CTF_SCORE` is used only for computing `ctf_confirmed` (the boolean annotation on the emitted signal). It is NOT a gate threshold — no signal returns `no_signal()` because `ctf_score < _MIN_CTF_SCORE`. The bool tells the ML model whether alignment was confirmed, which is different from preventing emission.

**Z-score gates:** For z-score features (`ofi_spike_z`, `cvd_spike_z`, and similar), the gate is `>= 2.0`. This threshold is statistically grounded (2-sigma) and instrument-agnostic.

**`"any"` regime rule:** Plugins with `regime_type = "any"` MUST use `hmm_trending_weight(features)` for their regime gate. Do NOT pass `"any"` to `hmm_regime_weight` - that returns the 0.5 neutral fallback because `"any"` is not a key in `_HMM_KEY_MAP`. See Anti-patterns (Section 8).

The per-regime gate shapes table in Section 2 Pattern 4 gives the full mapping.

---

## 4. Pattern Vocabulary

Five distinct concepts appear in I7 plugin code. They must not be confused or merged.

| Concept | Definition | Role in signal | Example |
|---|---|---|---|
| Pre-entry GATE | HMM regime probability threshold. Below threshold: return `no_signal()` before OHLCV extraction. Signal is NOT written to ledger. | Eligibility check only — not in confidence | `hmm_regime_weight < 0.30` |
| CONFIDENCE FACTOR | Intrinsic signal-strength score, clamped [0,1], weighted into the composite. Only price/volume/microstructure inputs. | IS confidence — the only inputs to `raw_conf` | `magnitude_score`, `persistence_score` |
| EXTRINSIC CONFIDENCE VECTOR (ECL) | Observable market-context signal carried as a top-level field on the emitted signal. Never a gate; never in the confidence composite. ML training input. | Top-level signal fields (`ctf_score`, `zone_friction_score`) or `context_features` blob | `ctf_score: float \| None`, `zone_friction_score: float \| None` |
| FACTOR SCORES | Per-plugin intrinsic factor breakdown, collected before compositing. Keys are plugin-specific; values are pre-composite [0,1] scores. | Persisted as `factor_scores: dict` on `signal_events` — enables ML weight optimization via counterfactual_pnl_r regression | `{"ofi_divergence": 0.72, "volume": 0.55}` |
| CONTEXT FEATURES | Full output of `capture_signal_features()` — 30+ market-context keys covering CTF sub-scores, regime, volatility, session. | Persisted as `context_features: dict` on `signal_events` — SignalRanker feature matrix for ML training | All keys from `capture_signal_features()` |

**Extrinsic Confidence Layer (ECL)** is the architectural term for the collection of extrinsic confidence vectors. "Layer" is a docs term only — it does not map to a class. The boundary invariant: if a setup meets its intrinsic detection criteria, it fires. Always. Extrinsic vectors annotate the emitted signal; they are not emission gates. An extrinsic gate is a prior masquerading as a model — it removes training data from the ledger permanently.

See `docs/foundation/glossary.md` for the full ECL definition and regime gate exception.

---

## 5. ECL — Extrinsic Confidence Layer

**ECL boundary invariant:** If a setup meets its intrinsic detection criteria, it fires. Always. No extrinsic vector suppresses signal emission. Only the HMM regime gate may suppress emission; all extrinsic confidence vectors (CTF, zone_friction, exhaustion) are annotations on the emitted signal, never gates.

**Extrinsic confidence vectors (current):**
- `ctf_score: float | None` — I6 cross-timeframe alignment score. `None` = I6 had no data at emit time (cold-start). `0.0` = genuine neutral alignment. These are different populations — never conflate them with `or 0.0`.
- `ctf_confirmed: bool | None` — `abs(ctf_score) >= _MIN_CTF_SCORE`. `None` when `ctf_score` is `None`. This bool tells the ML model whether I6 alignment was present, without suppressing the signal.
- `zone_friction_score: float | None` — zone friction at emit time. `None` = no zone data. An annotation, not a gate.
- HMM regime weight — suppresses signal *activation* (`pending → regime_suppressed`) at the tracker level, post-write. The signal IS written to `signal_events` before regime gating. This is the only permitted post-emission filter.
- Exhaustion score — included in `context_features` via `capture_signal_features()`. Never an emission suppressor.

**In code:** `ctf_score`, `ctf_confirmed`, `zone_friction_score` are top-level fields on the signal dict and `signal_events` table. `factor_scores` carries the intrinsic factor breakdown. `context_features` is the full `capture_signal_features()` blob — the ML training feature matrix for SignalRanker.

**Why the ECL boundary matters:** Any extrinsic gate is a prior masquerading as a model. It removes training data from `signal_events` permanently. The ML model then fits on a biased sample — it never sees the cases where the pattern fired but the extrinsic context was unfavorable. The model cannot learn whether those cases are actually bad; it is simply denied the evidence. The counterfactual outcome (`counterfactual_pnl_r` on `trade_frames`, populated by CounterfactualTracker in Phase 130) is how the model learns the value of each extrinsic vector — but only if the signal was written.

**Regime gate exception:** The HMM regime gate suppresses activation, not emission. Signal written first, then regime gate applied by `SignalTracker`. The `signal_events` row has `status = 'regime_suppressed'` — visible to the ML model, with a counterfactual outcome measurable by CounterfactualTracker.

---

## 6. Canonical Reference

The primary reference implementation is `src/intelligence/trading/ofi_continuation.py`, class `OFIContinuationPlugin`.

Key symbols to study:

- `OFIContinuationPlugin.shadow_only` - ClassVar declaration, `True`
- `OFIContinuationPlugin.requires_i6_confluence` - ClassVar declaration, `True`
- `OFIContinuationPlugin.regime_type` - `"trend"`, used in the regime gate
- `OFIContinuationPlugin.compute_full` - the 4-factor confidence composite (`magnitude_score`, `alignment_score`, `persistence_score`, `volume_score`) with weights summing to 1.0, wrapped by `compose_confidence()`; ECL annotation and `factor_scores` collection follow.

Do NOT cite line numbers - line numbers drift after refactors. Reference class names, method names, and ClassVar identifiers.

Secondary references:

- `src/intelligence/trading/liquidity_sweep_reclaim.py` - regime gate + ECL annotation + continuous regime weighting
- `src/intelligence/trading/ofi_divergence.py` - factor_scores collection pattern

---

## 7. Compliant Setups (22 total)

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

Wave 1 (8 plugins) and Wave 2 (9 plugins) refactored in Phase 119. These plugins originally had a dual HMM+CTF gate (regime gate plus a `ctf_score < threshold → no_signal()` emission suppressor). Phase 123 dissolved that category: the CTF gate was removed from all 17 plugins. They now follow the uniform pattern — single HMM regime gate before OHLCV, with `ctf_score`/`ctf_confirmed` as ECL annotations on the emitted signal. No structural difference remains between Phase 118 and Phase 119 plugins.

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

These 8 plugins are in `_I7_I6_EXEMPT` in `register_plugins.py`. They have `requires_i6_confluence = False` and do not yet have the single regime gate + I6 CTF ECL annotation or 4-factor confidence composite. They are deferred to a follow-up phase. `validate_tier()` exempts them explicitly.

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

## 8. Enforcement

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

## 9. Anti-patterns

These patterns appear in legacy code and MUST NOT appear in any new or refactored I7 plugin.

### 1. CTF score as emission gate (ECL boundary violation)

```python
# WRONG - CTF is an extrinsic vector; calling no_signal() on low CTF removes training data
ctf_score = float(features.get("ctf_score") or 0.0)
if abs(ctf_score) < _MIN_CTF_SCORE:
    return no_signal()
```

```python
# CORRECT - annotate, never gate
_ctf_raw = features.get("ctf_score")
ctf_score: float | None = float(_ctf_raw) if _ctf_raw is not None else None
ctf_confirmed: bool | None = (abs(ctf_score) >= _MIN_CTF_SCORE) if ctf_score is not None else None
# pass ctf_score=ctf_score, ctf_confirmed=ctf_confirmed to emit_signal
```

### 2. Zone friction as emission gate (ECL boundary violation)

```python
# WRONG - zone_friction is an extrinsic vector; gating on it removes training data
zone_friction = float(features.get("zone_friction_score", 0.0))
if zone_friction > _MAX_ZONE_FRICTION:
    return no_signal()
```

```python
# CORRECT - annotate
_zf_raw = features.get("zone_friction_score")
zone_friction_score: float | None = float(_zf_raw) if _zf_raw is not None else None
# pass zone_friction_score=zone_friction_score to emit_signal
```

### 3. `or 0.0` fallback for CTF score (conflates cold-start with neutral)

```python
# WRONG - treats "no I6 data" as 0.0 (neutral); biases cold-start signals
ctf_score = float(features.get("ctf_score") or 0.0)
```

```python
# CORRECT - None means no data; 0.0 means genuine neutral alignment
_ctf_raw = features.get("ctf_score")
ctf_score: float | None = float(_ctf_raw) if _ctf_raw is not None else None
```

### 4. `hmm_regime_weight(features, "any")` - silent 0.5 pass

```python
# WRONG - "any" is not in _HMM_KEY_MAP; returns 0.5 unconditionally
if hmm_regime_weight(features, "any") < _MIN_REGIME_WEIGHT:
    return no_signal()
```

```python
# CORRECT for regime_type="any" plugins
if hmm_trending_weight(features) < _MIN_REGIME_WEIGHT:
    return no_signal()
```

### 5. Binary HMM regime equality checks

```python
# WRONG - binary check loses probability information
if hmm_regime in (1, 2):  # trending
    ...
```

```python
# CORRECT - continuous probability gate
if hmm_regime_weight(features, "up") < _MIN_REGIME_WEIGHT:
    return no_signal()
```

### 6. OHLCV access before the regime gate

```python
# WRONG - expensive ops before cheap eligibility gate
df, close, high, low, volume = extract_ohlcv(frames, self.min_lookback)
if hmm_regime_weight(features, self.regime_type) < _MIN_REGIME_WEIGHT:
    return no_signal()
```

```python
# CORRECT - regime gate first, OHLCV after
if hmm_regime_weight(features, self.regime_type) < _MIN_REGIME_WEIGHT:
    return no_signal()
df, close, high, low, volume = extract_ohlcv(frames, self.min_lookback)
```

### 7. HMM probability or CTF score as a confidence factor

```python
# WRONG - extrinsic vectors in the intrinsic composite
ctf_factor = clamp01((abs(ctf_score) - _MIN_CTF_SCORE) / (1.0 - _MIN_CTF_SCORE))
raw_conf = 0.35 * signal_strength + 0.15 * ctf_factor + ...
```

Confidence = intrinsic signal strength only. ECL vectors inform the ML attribution layer; they are not composited with intrinsic factors. Any extrinsic term in the composite produces a biased `raw_confidence` that the ML model cannot decompose.

---

## 10. See Also

- `src/intelligence/trading/ofi_continuation.py` - canonical reference implementation
- `src/intelligence/trading/confidence_utils.py` - `compose_confidence()`, `clamp01()`, `capture_signal_features()`
- `src/intelligence/utils/gradient_utils.py` - `hmm_regime_weight()`, `hmm_trending_weight()`
- `src/intelligence/register_plugins.py` - `TIER_I7`, `_I7_I6_EXEMPT`
- `src/intelligence/plugins/base.py` - `validate_tier()`, `ArchitectureViolation`
- `tests/unit/intelligence/test_i7_extrinsic_contract.py` - extrinsic vs intrinsic contract tests
- `docs/foundation/glossary.md` - ECL, APR, signal_events, counterfactual_pnl_r full definitions
- `docs/foundation/parameter-store.md` - APR full specification; ECL-APR relationship
- `docs/architecture/signal-trade-separation-ADR.md` - 3-table architecture decision record (Phase 127+)
- `.planning/phases/119-remaining-16-setup-refactoring/119-CONTEXT.md` - D-01, D-02, D-03, D-04 decisions
