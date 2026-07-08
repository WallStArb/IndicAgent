# Regime Transition Early Detection

**Version:** 1.0.0
**Status:** draft
**Priority:** medium
**Milestone:** future (post-v2.8)
**Last Updated:** 2026-03-23
**Tags:** regime, hmm, transition, early-detection, bocpd, signal-gating, intelligence

---

## The Problem

All I7 plugins are regime-gated. Binary gating is correct for mature regimes but creates a blind spot in the transition window — often where the highest-alpha entries live.

**Current state:**

- `hmm_regime_prob` drops below the `prob_min=0.30` floor during transitions
- `regime_gate.py` marks this as `suppression_reason="regime_prob"` — signals suppressed
- `trad_RegimeTransition` exists but requires BOTH BOCPD changepoint AND CHoCH to fire — a late-confirmation plugin, not early detection
- Result: during the consolidation→trend transition, every directional plugin fires zero signals until the regime is mature and the best entries are already gone

The HMM is giving us exactly the right signal — its uncertainty is the signal — but we're discarding it.

---

## What We Already Have (Underused)

The HMM already outputs three per-bar probabilities:

| Field | Meaning |
|-------|---------|
| `hmm_prob_ranging` (derived: `1 - up - down`) | P(market is ranging) |
| `hmm_prob_trending_up` | P(market is trending up) |
| `hmm_prob_trending_down` | P(market is trending down) |
| `hmm_regime_prob` | P of the currently-winning label |
| `hmm_regime_duration` | Bars since last regime switch |

When `hmm_regime_prob` is low (say 0.35–0.55), the HMM is distributing probability mass across multiple states. That is the transition window. We currently throw it away.

---

## The Core Idea

**Add two new I4-layer HMM output fields:**

### 1. `regime_entropy`

Shannon entropy across the three HMM state probabilities:

```
H = -Σ p_i * log2(p_i)   where i ∈ {ranging, trending_up, trending_down}
```

| H value | Interpretation |
|---------|----------------|
| ~0.0 | Deep in a mature regime (one state dominates) |
| ~0.5–1.0 | Transitioning — HMM distributing probability |
| ~1.58 | Maximum uncertainty (equal across all 3 states) |

**This is the "am I in transition?" score** — continuous, no threshold needed.

### 2. `hmm_regime_velocity`

Rate of change of `hmm_regime_prob` over N bars (default N=5):

```
velocity = (hmm_regime_prob[t] - hmm_regime_prob[t-N]) / N
```

- **Negative velocity** (prob declining): regime is destabilizing — transition starting
- **Positive velocity** (prob rising): regime is consolidating — mature regime forming
- **Near-zero**: stable either way

Velocity identifies *which phase* of the transition we're in.

---

## Regime Transition Phases

Using `regime_entropy` + `regime_velocity` together:

```
Phase A: Mature regime
  entropy < 0.4, velocity ~0, hmm_regime_prob > 0.75

Phase B: Destabilizing (early transition signal)
  entropy rising: 0.4 → 0.8
  velocity < -0.05 (prob declining)
  hmm_regime_prob dropping: 0.75 → 0.40

Phase C: Peak uncertainty (transition confirmed but direction unknown)
  entropy > 0.8
  hmm_regime_prob < 0.40
  → suppress directional setups; watch for CHoCH/BOS

Phase D: New regime forming (highest conviction entry window)
  entropy declining: 0.8 → 0.4
  velocity > +0.05 (prob rising for new regime label)
  hmm_prob_trending_up or hmm_prob_trending_down diverging

Phase E: Mature new regime
  entropy < 0.4, velocity ~0 again
  → current binary gate works correctly here
```

Phase D is where the current system fires zero signals but where early trend entries have the best R:R.

---

## Architectural Approach

### Layer 1: Add fields to HMM plugin (I4)

`src/intelligence/smart_money/hmm_regime.py` already tracks `_state` for regime history. Add:

- `regime_entropy`: computed each bar from the three alpha probabilities
- `hmm_regime_velocity`: `(current_prob - prob_N_bars_ago) / N`, maintained in `_state`

Both are cheap — no new data sources, pure computation on existing HMM output.

### Layer 2: Add `"transitioning"` to `_REGIME_MAP` (I7 aggregator)

`src/intelligence/trading/aggregator.py` `_REGIME_MAP` currently has:

```python
"trend":           [1, 2],
"mean_reversion":  [0],
"any":             [0, 1, 2],
```

Transition-specific plugins need a fourth gate label:

```python
"transitioning":   [],   # regime label irrelevant — entropy/velocity gate instead
```

With a companion check: plugin fires when `regime_entropy > 0.5 AND hmm_regime_velocity < -0.03`.

### Layer 3: Upgrade `trad_RegimeTransition` (Phase D detection)

Current plugin fires late: requires BOCPD changepoint + CHoCH (both confirmation events). Add a lower-confidence "early" path:

- **Early path** (Phase B/D): `regime_entropy > 0.5 AND hmm_regime_velocity` sign flip + ADX slope positive → fires at reduced confidence (0.3–0.5), `regime_context = "early_transition"`
- **Confirmation path** (existing): BOCPD + CHoCH → fires at full confidence (0.6–0.9), `regime_context = "confirmed_transition"`

The ML scoring layer (Phase 54) will learn which path has real alpha — the architecture just needs to not discard the signal.

### Layer 4: Soft gate for existing directional plugins (stretch goal)

The binary gate is correct for `hmm_regime_prob < 0.30` (garbage-tier confidence). But the 0.30–0.55 band currently suppresses everything. Instead:

```
confidence_multiplier = lerp(0.5, 1.0, (hmm_regime_prob - 0.30) / (0.55 - 0.30))
```

Apply this multiplier to `calibrated_confidence` for any signal in the 0.30–0.55 band. The signal fires at reduced conviction rather than being dropped. Phase 54 ML layer then discovers whether transition-period signals of a given type actually have edge.

This is a Renaissance principle: **never drop a data point that might contain signal**. A suppressed signal produces zero training data. A low-confidence signal is a labeled sample.

---

## What This Unlocks

| Scenario | Current Behavior | With This Change |
|----------|-----------------|------------------|
| Consolidation tightening (Phase B) | All signals suppressed | Early transition plugin fires at 0.35 confidence |
| HMM flipping from ranging→trending (Phase D) | Suppressed until CHoCH | Reduced-confidence trend setup fires, labeled as `early_transition` |
| CHoCH confirmed + entropy dropping (Phase D→E) | `trad_RegimeTransition` fires | Same, but we also have earlier Phase D samples for ML |
| Deep mature trend (Phase A/E) | Works fine | No change — binary gate unchanged above 0.55 |

---

## What This Is NOT

- Not an HMM retraining effort — existing model, new derived outputs only
- Not removing the binary gate — the gate still protects all mature-regime plugins
- Not a new data source — entropy and velocity are pure computation on existing HMM state

---

## Implementation Scope (when ready to plan)

**Small slice (Phase-sized):**
1. Add `regime_entropy` + `hmm_regime_velocity` to `hmm_regime.py` outputs
2. Add both fields to `IntelligenceEvent` schema (non-breaking — new optional fields)
3. Wire as inputs to `trad_RegimeTransition` — use entropy in confidence calculation
4. Add early-path logic to `RegimeTransitionPlugin` (no new plugin needed initially)
5. Update `_REGIME_MAP` with `"transitioning"` label

**Stretch (separate phase):**
- Soft gate multiplier for signals in the 0.30–0.55 `hmm_regime_prob` band
- New `trad_RegimeBreakout` plugin designed specifically for Phase D window

**Dependency:** Requires clean, stable HMM output from the live pipeline. Should not be planned until Phase 49 DB performance work is complete (stable `intelligence_features` pipeline is a prerequisite for measuring transition signal quality).

---

## Open Questions

1. **What N for velocity?** N=5 bars at 1m TF = 5 minutes. Should be TF-adaptive: `{1m: 5, 5m: 5, 15m: 4, 1h: 3}`.
2. **Entropy threshold calibration**: 0.5 as the "transition" cutoff is a starting assumption. Needs backtesting on historical `hmm_regime_prob` distributions from `intelligence_features`.
3. **Does Phase D even have edge?** Renaissance answer: ship it at low confidence, let the ML layer measure. Don't guess — instrument and find out.
