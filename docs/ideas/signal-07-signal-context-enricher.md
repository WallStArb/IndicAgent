# Signal Context Enricher — Learned Post-Signal Modifier Layer

**Version:** 1.0
**Status:** idea
**Priority:** medium
**Milestone:** post-v2.9
**Last Updated:** 2026-06-08
**Tags:** signal, confidence, enricher, ml, context, shadow-governance, architecture, i7

## Problem

I7 plugins fire with an `intrinsic_confidence` that should reflect only the quality of the detected
pattern. During an audit (2026-06-08), four categories of signal-extrinsic factors were found
hard-coded into confidence calculations across 20+ plugins:

1. **HMM regime weights** — `hmm_regime_weight()` applied as additive trim or composite component
2. **CTF (I6) scores** — `ctf_score`, `ctf_structure_alignment`, `ctf_trend_alignment` baked in
3. **Exhaustion boost/guard** — `apply_exhaustion_boost` / `apply_exhaustion_guard` from I4
4. **Zone friction** — supply/demand zone context as penalty/boost

All were stripped from confidence in the v2.9 signal quality pass. The data itself is preserved —
it travels with every signal in `capture_signal_features()`. What was lost is the *relationship*
between these features and signal quality. That relationship should be learned from outcomes, not
assumed from priors.

## What Signal-Intrinsic Means

Confidence must answer one question: **how strong and clean is this specific pattern right now?**

**Intrinsic — stays in confidence:**
- Pattern magnitude: OFI divergence peak, CVD divergence depth, gap size in ATR multiples, squeeze duration in bars
- Pattern persistence: `extra_bars`, `bars_persistent`, EWMA alignment within the same indicator family
- Level quality: PWH/PWL vs PDH/PDL significance for level-test setups — this IS the quality of the level
- Structural break quality: break margin relative to ATR for breakout setups
- Volume at the pattern when volume is definitionally part of the pattern (e.g., expansion in squeeze_expansion)

**Extrinsic — removed from confidence, travels in features:**
- Regime state: HMM probabilities, `trend_regime`, Kalman regime classification
- CTF confluence: any `ctf_*` score (I6 layer output)
- Exhaustion state: `exhaustion_score`, `exhaustion_side`, `exhaustion_bars` (I4 output)
- Zone context: supply/demand zone membership and strength (separate plugin output)
- SMC events: FVG, order block, CHoCH, BOS (SMC layer output)
- ICT positioning: premium/discount, VWAP deviation — unless the signal IS a VWAP or premium/discount setup

**The test:** if the feature is computed by a separate plugin running in parallel, it is extrinsic. If it is derived from the same raw market data the plugin's own detection logic consumes, it is potentially intrinsic.

## Proposed Solution

A thin `SignalContextEnricher` in-process wave after I7, before aggregator selection. It reads the
raw signal and feature vector, looks up learned `context_multipliers`, and produces an
`adjusted_confidence` alongside the unchanged `intrinsic_confidence`.

```
I7 signals (intrinsic_confidence)
    → SignalContextEnricher
        reads:   signal type + full feature vector
        looks up: context_multipliers (DB-loaded, refreshed every 15 min)
        produces: adjusted_confidence = intrinsic_confidence * f(active_multipliers)
    → Aggregator (ranks on adjusted_confidence)
    → signal_ledger (stores both intrinsic_confidence and adjusted_confidence)
```

ML trains on `intrinsic_confidence` — the feedback loop stays uncontaminated.
Aggregator ranks on `adjusted_confidence` — context benefit is expressed at ranking time.

## Candidate Context Features (from Stripped Modifiers)

These are the exact factors removed during the v2.9 audit. Each is a candidate multiplier input
for the enricher. The enricher discovers empirically which ones actually matter per setup type.

### HMM Regime Probability

| Feature key | Relevant for | Prior modifier removed from |
|---|---|---|
| `hmm_prob_trending_up` | trend-following, momentum, ORB setups | ofi_continuation, gap_analysis, cvd_divergence, momentum_breakout, squeeze_expansion, orb15, orb30, choch_reversal, liquidity_hunt, prev_day_level_test |
| `hmm_prob_trending_down` | same, short direction | same |
| `hmm_prob_ranging` | mean-reversion setups | failed_breakout, supply_demand, liquidity_sweep, ofi_divergence, prev_day_level_test |

Prior modifier pattern: `confidence += K * (regime_w - 0.5)` or `confidence += K * regime_w` or
as a 15–20% composite weight. Maximum distortion: ±0.20 on individual signals.

### CTF (I6) Confluence Scores

| Plugin | Feature | Prior formula | Max effect |
|---|---|---|---|
| `ofi_continuation` | `ctf_score` | `+0.15 * min(1.0, ctf/0.7)` if `\|ctf\| > 0.3` | +0.15 |
| `cvd_divergence` | `ctf_score` | same | +0.15 |
| `liquidity_sweep_reclaim` | `ctf_score` | `+0.05 * min(2.0, ctf/0.5)` if `\|ctf\| > 0.3` | +0.10 |
| `supply_demand_setup` | `ctf_score` | `+0.05 * min(2.0, ctf/0.5)` if `\|ctf\| > 0.3` | +0.10 |
| `choch_reversal` | `ctf_structure_alignment` | `+0.08 * min(1.0, ctf_struct/0.7)` if `> 0.3` | +0.08 |
| `choch_reversal` | `ctf_trend_alignment` | `+0.06 * min(1.0, ctf_trend/0.7)` if `> 0.3` | +0.06 |
| `choch_reversal` | `ctf_score` | `+0.05 * min(1.0, ctf/0.7)` if `\|ctf\| > 0.3` and aligned | +0.05 |
| `trend_following` | `ctf_score` | `0.20 * min(1.0, \|ctf\|)` in composite | 20% of raw_conf |
| `liquidity_hunt` | `ctf_score` | `+0.05` if `\|ctf\| > 0.3` and directionally aligned | +0.05 |

`choch_reversal` stacks all three CTF components — maximum combined distortion: +0.19 on a single signal.
`trend_following` is the structural worst case: CTF is 20% of the composite formula, not an additive trim.

### Exhaustion State

| Plugin | Variant | Prior formula | Effect |
|---|---|---|---|
| `supply_demand_setup` | boost | `+0.10` if exhaustion confirms reversal direction | +0.10 |
| `liquidity_sweep_reclaim` | boost | same | +0.10 |
| `liquidity_hunt` | boost | same | +0.10 |
| `prev_day_level_test` | boost | same | +0.10 |
| `momentum_breakout` | guard | `-0.15` if `exhaustion_score > 0.7` and `exhaustion_bars >= 3` | -0.15 |
| `squeeze_expansion` | guard | same | -0.15 |
| `trend_following` | guard | same | -0.15 |

The boost hypothesis (exhaustion confirming reversal direction) and the guard hypothesis (avoid
exhausted trend moves) are both empirically testable. The enricher discovers whether they hold, for
which setups, and whether the effect is regime-conditional. Let outcome data decide.

### Zone Context

| Plugin | Condition | Prior formula | Effect |
|---|---|---|---|
| `momentum_breakout` | long into supply zone | `-0.12 * supply_strength` | up to -0.12 |
| `momentum_breakout` | short into demand zone | `-0.12 * demand_strength` | up to -0.12 |
| `trend_following` | long into supply zone | `-0.12 * supply_strength` | up to -0.12 |
| `trend_following` | short into demand zone | `-0.12 * demand_strength` | up to -0.12 |
| `liquidity_hunt` | directionally aligned zone | `+0.05` | +0.05 |
| `liquidity_hunt` | opposing zone | `-0.10` | -0.10 |

### SMC Layer Outputs in `liquidity_hunt`

A fifth category found only in `liquidity_hunt`: I5/SMC layer event flags used as confidence boosts.
These are outputs from separate SMC plugins (FVG, OB, CHoCH, BOS detectors) — the same tier boundary
violation as CTF, just one layer lower.

| Feature | Condition | Prior formula | Effect |
|---|---|---|---|
| `fvg_type` | equals signal direction | `+0.08` | +0.08 |
| `ob_type` | equals signal direction | `+0.06` | +0.06 |
| `choch_detected` | == 1.0 | `+0.10` | +0.10 |
| `bos_detected` + `bos_direction` | detected and directionally aligned | `+0.05` | +0.05 |
| `price_in_premium` | discount-aligned long or premium-aligned short | `+0.06` | +0.06 |

Combined maximum distortion on a single `liquidity_hunt` signal: +0.35 from SMC alone, on top of the
HMM regime and zone modifiers. These are all candidate enricher inputs — the question is whether
FVG/OB/CHoCH alignment empirically improves stop-run outcomes, not whether it feels like it should.

## What This Buys You

1. The system discovers which context-signal combinations actually matter from outcome data, not from intuition
2. CTF alignment might genuinely improve OFI continuation — you'll find out with a real CI, not a guess
3. Exhaustion might harm trend signals in some regimes but help in others — the bucketed structure captures that interaction; a hard-coded scalar cannot
4. Coefficients update as market conditions change; a context effect that worked in 2024 might not hold in 2026
5. `intrinsic_confidence` stays pure for all other ML consumers regardless of what the enricher does

## Governance Model

Same shadow promotion logic as `setup_performance`:

- **Table**: `context_multipliers(setup_type, context_feature, bucket, multiplier, pnl_r_mean, n, bootstrap_ci_lower, bootstrap_ci_upper, active)`
- **Bucket examples**: `ctf_score` → `[LOW <0.3, MED 0.3–0.6, HIGH >0.6]`; `hmm_prob_trending_up` → decile buckets
- **Promotion gate**: `n >= 50 AND bootstrap_ci_lower(multiplier) > 1.0` (or `< 1.0` for penalty multipliers)
- **Cold start**: all multipliers = 1.0; `adjusted_confidence = intrinsic_confidence`
- **Update cadence**: nightly by `ml-training` re-runs regression on `signal_ledger_full`, updates table, promotes/demotes buckets
- **Demotion**: multiplier CI crosses 1.0 for 3 consecutive cycles

## Architecture Notes

- `adjusted_confidence = intrinsic_confidence * product(active_multipliers for this signal + context)`
- Multipliers are capped: `max(0.5, min(1.5, multiplier))` — no modifier halves or doubles confidence
- `intrinsic_confidence` is immutable after I7 fires; enricher only writes `adjusted_confidence`
- Both values stored in `signal_ledger`; all ML training uses `intrinsic_confidence`

## Risk: perf_multiplier Compounding

The existing `perf_multiplier` already reweights signals at the aggregator level by setup performance.
A context modifier adds a second layer. If both are active simultaneously, multipliers compound and the
combined effect becomes opaque.

**Resolution:** one layer must own contextual adjustment. Two options:
- Extend `setup_performance` to include context bucketing (regime, CTF tier, exhaustion state) — enricher
  becomes an enhancement of the existing system
- Build enricher as a full replacement, deprecating `perf_multiplier` regime-segmentation once mature

Do not run both independently. Coordinate before the enricher phase begins.

## Structural Defects to Fix Before Building the Enricher

Two plugins have problems deeper than additive extrinsic modifiers. They must be fixed during the
v2.9 strip pass — the enricher cannot compensate for them.

### `trend_following` — 60% of confidence is extrinsic

```python
raw_conf = (
    0.35 * min(1.0, abs(trend_regime))   # extrinsic: I4 regime classifier
  + 0.25 * min(1.0, trend_conf)          # borderline: Kalman trend quality
  + 0.20 * min(1.0, abs(trend_strength)) # borderline: Kalman trend magnitude
  + 0.20 * min(1.0, abs(ctf_score))      # extrinsic: I6 output
)
```

`trend_regime` and `ctf_score` together account for 55% of `raw_conf`. Then zone friction
(`-0.12`) and exhaustion guard (`-0.15`) apply on top. The confidence value is primarily a
market-context score, not a pattern-quality score.

Fix: remove `trend_regime` and `ctf_score` from the composite. Redesign around `trend_strength`
(how strong is the Kalman-estimated trend), `trend_conf` (Kalman filter quality), and
`swing_pattern` (structural confirmation). Redistribute weights to intrinsic factors only.

### `choch_reversal` — regime boost is semantically inverted

```python
# Bullish CHoCH: rewards trending-up probability
raw_conf += 0.2 * hmm_regime_weight(features, "up")
# Bearish CHoCH: rewards trending-down probability
raw_conf += 0.2 * hmm_regime_weight(features, "down")
```

CHoCH (Change of Character) is a structural reversal signal — it fires when price breaks a key
level in the opposite direction of the prior trend. A bullish CHoCH is most significant when the
prior regime was bearish (genuine character change). Rewarding `hmm_prob_trending_up` for a
bullish CHoCH inflates confidence when the market was already trending up — making the signal
behave like a continuation indicator rather than the reversal it detects.

This is not just extrinsic; it is directionally wrong. A high trending-up probability at the time
of a bullish CHoCH means less structural change, not more. When the enricher later learns a CHoCH
multiplier, the direction of the HMM feature must be inverted relative to what was hard-coded here.

Fix: remove the HMM boost entirely. CHoCH quality is intrinsic to the structural break,
`ctf_structure_alignment`, `ctf_trend_alignment`, and exhaustion state — all of which are
separately handled.

## Phase Scope (when ready to build)

1. Add `intrinsic_confidence` column to `signal_ledger` (migration); populate from existing `confidence`
2. Create `context_multipliers` table (migration)
3. Implement `SignalContextEnricher` as an in-process I7-post wave (no new service)
4. Wire `adjusted_confidence` into aggregator ranking; store both in signal_ledger
5. Add nightly `context_multipliers` update to `ml-training` batch
6. Shadow governance: promote first multipliers once n >= 50 per bucket

Prerequisite: v2.9 signal quality pass must be complete (intrinsic confidence must be clean before
this layer learns anything meaningful from it).
