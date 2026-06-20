# Signal Layer Evolution

**Date:** 2026-06-20
**Status:** Design - pre-implementation
**Milestone:** v3.0
**Companion doc:** `docs/plans/2026-06-20-v30-reference-architecture.md` (the destination architecture)

---

## Purpose

The VIL reference architecture describes what to build: AlphaEngine and AnalogEngine. This document describes what the existing I7 signals tier becomes — what retires, what survives in a different role, and how the transition preserves the Signal Ledger Architecture (SLA) as the measurement substrate.

---

## What a Signal Plugin Currently Does

Each I7 plugin bundles three distinct responsibilities:

1. **Pattern detection** — evaluates whether a set of I1-I6 features satisfies hand-coded criteria
2. **Trade framing** — specifies entry type (`at_close`, `at_pullback`, etc.), stop price, and target price
3. **Emission decision** — decides whether the conditions constitute a tradeable setup

Responsibility 1 is feature computation. Responsibility 2 is risk management. Responsibility 3 is the problem: it is researcher bias encoded as code. A human decided that "RSI divergence + volume confirmation + CTF alignment constitutes a tradeable setup." The IC of that belief is unmeasured.

---

## What Retires

**The emission decision layer.** I7 plugins stop asking "is this a signal?" That question is retired entirely. It is replaced by AlphaEngine's ensemble alpha: a signal is emitted when `ensemble_alpha` crosses the regime-adjusted threshold AND the ensemble confidence interval supports positive expected value. No plugin makes that call. The IC-weighted ensemble does.

**Setup names as first-class concepts.** MomentumContinuation, BreakoutRetest, and similar pattern identifiers lose their role as emission triggers. After IC discovery identifies which plugins carry measured IC > 0 with `IC_CI_lower > 0.0`, those that carry no information regardless of their logical coherence are retired. The glossary's definition of `signal` as "produced by I7 plugins" evolves: signals are emitted by the ensemble, not by individual plugins.

**Correlated redundancy.** IC discovery will surface plugin pairs with near-zero orthogonality. Correlated plugins that respond to the same underlying phenomenon do not multiply information — they amplify noise. When IC discovery identifies a redundant pair, one is retired. The `effective_n` calculation in AlphaEngine makes this explicit: correlated plugins share weight rather than each receiving full ensemble weight.

---

## What Survives

### I7 Plugins as Alpha Scorers

Plugins with measured IC > 0 are not retired — they are converted. Their emission decision logic is removed. Their feature computation and directional conviction remain. Each plugin produces an `alpha_score` every bar: `raw_confidence × direction`, a float in [-1, +1].

This is a narrow change to each plugin. The Intrinsic Confidence Composite (ICC) computation — price structure, volume confirmation, momentum alignment, microstructure — is unchanged. The only removal is the threshold check that decided whether to emit. The plugin now always produces a score; the ensemble decides whether the score crosses an emission threshold.

Plugins below the IC threshold (`IC_CI_lower <= 0.0` at `n >= 100`) are down-weighted to zero in the ensemble automatically via APR (`alpha.weights.*`). They continue running in shadow — their scores accumulate further observations. Shadow Governance (SG) remains the promotion mechanism.

### Zones as Intelligence Vector Features

Supply and demand zones, support and resistance levels — produced by the structure (I3) tier — survive in two roles:

**As features.** Zone proximity, zone strength, and zone freshness are measurable predictors. IC discovery may confirm that signals firing at strong demand zones carry higher IC than signals firing in the middle of a range. Zone features feed into V1 Quant Vector scoring alongside all other I1-I6 features. The ECL boundary invariant holds: zone proximity is an extrinsic confidence vector that annotates signals, not a gate that suppresses them.

**As trade framing references.** Given an `ensemble_alpha` that crosses the emission threshold, stop placement and target selection need a reference price. "Stop below the nearest demand zone or 1.5× ATR, whichever is tighter" is a sound risk management primitive. Zone levels produced by I3 are the natural input. This is pure risk management — it happens after emission, not before.

### Entry Type Logic

`at_close`, `at_pullback`, `at_limit`, `at_reclaim`, `zone_proximal` survive as execution strategies. They answer "given that a signal was emitted, how do we enter?" not "should a signal be emitted?" The `trade_frames` hypothesis layer already accommodates one signal producing multiple entry type rows — this structure remains correct.

---

## The New Pipeline Structure

```
I1-I4:  Feature extraction (unchanged)
         Technical indicators, composites, structure, context
         Zones produced here as structure (I3) features

I5-I6:  Pattern detection and confluence (unchanged)
         CTF confluence score annotates the signal; does not gate it

I7:     Alpha scoring (evolved)
         Each plugin produces alpha_score = raw_confidence × direction
         No emission decision; score produced every bar

AlphaEngine (cold batch):
         IC discovery: Spearman(alpha_score_t, return_{t→t+N})
         Ensemble: IC-weighted combination across V1-V4 vectors
         Emission: ensemble_alpha ≥ regime-adjusted threshold → signal emitted

Risk framing (post-emission):
         Stop: nearest I3 zone or ATR-derived level
         Target: R-multiple from APR (signal.target_r)
         Entry type: from active trade_frames entry type set

signal_events: emission recorded with ensemble_alpha, ICC, ECL vectors
trade_frames:  one row per entry_type; counterfactual_pnl_r populated by CounterfactualTracker
```

The DAG invariant holds. I1-I7 runs in-process in IntelligencePipeline. AlphaEngine runs in the cold batch layer. The hot path never reads from `plugin_ic_scores` or `ensemble_alpha` tables directly — APR is the only feedback channel from cold batch to the live pipeline.

---

## I7 Transition Protocol

For each I7 plugin, after IC discovery on the Phase 133 corpus:

| IC result | Action |
|-----------|--------|
| `IC_CI_lower > 0.0` at `n >= 100` | Convert: remove emission decision, add `alpha_score` field |
| `IC_CI_lower <= 0.0` at `n >= 100` | Down-weight to zero in APR; continue accumulating observations |
| Insufficient `n` | No change; continue in shadow; re-evaluate after Phase 133 corpus grows |
| Correlated duplicate (pairwise IC overlap) | Merge into surviving plugin or retire the weaker one |

Conversion is backward-compatible with the SLA. `signal_events` gains an `alpha_score` column (Phase B from VIL reference doc). Existing rows have `alpha_score = NULL`, populated on rebuild when Phase 133 corpus is regenerated.

---

## Relationship to ECL

Nothing in this evolution changes the ECL boundary invariant. CTF score, zone friction score, and HMM regime weight remain extrinsic confidence vectors — annotations on emitted signals, not emission gates.

The addition from AlphaEngine: `alpha_ensemble_alpha` and `iv_ci_lower` are added as cold-path enrichment to `signal_events`. These join the existing ECL vectors as features in the ML training matrix. The ML model learns which combinations of intrinsic quality (ICC), ensemble conviction (`alpha_ensemble_alpha`), and extrinsic context (CTF, regime, zones) produce favorable `counterfactual_pnl_r` outcomes. No human encodes that relationship.

---

## Glossary Terms Applied

| Term | How used here |
|------|--------------|
| `alpha score` | Continuous [-1,+1] directional conviction score per plugin per bar |
| `ensemble alpha` | IC-weighted combination across active plugins; emission trigger |
| `IC discovery` | Empirical measurement of plugin predictive power on Phase 133 corpus |
| `Information Coefficient (IC)` | Spearman(alpha_score, forward_return); primary plugin quality measure |
| `intelligence vector` | Orthogonal alpha source dimension (V1 Quant, V2 Microstructure, V3 Macro, V4 Calendar) |
| `Intrinsic Confidence Composite (ICC)` | Unchanged 4-factor plugin-internal score; maps to alpha_score via direction |
| `Extrinsic Confidence Layer (ECL)` | Unchanged annotation system; CTF/zone/regime vectors remain extrinsic |
| `Shadow Governance (SG)` | Unchanged promotion mechanism; IC threshold replaces binary P&L gate |
| `AlphaEngine` | System 1 (parametric IC); replaces hand-coded emission decisions in I7 |
| `Signal Ledger Architecture (SLA)` | Unchanged 3-table schema; additive columns only |
| `counterfactual_pnl_r` | Unchanged ML training target on `trade_frames` |

---

## What Does Not Change

- I1-I6 feature extraction is unchanged
- HMM regime detection is unchanged; regime conditioning of IC weights is additive
- SLA (signal_events / trade_frames / trade_executions) schema is additive only
- ECL boundary invariant is unchanged
- APR governs all thresholds and weights
- DAG invariants hold — hot path remains DB-ignorant
- Shadow Governance governs all promotions
