# Extrinsic Confidence Layer (ECL)

**Version:** 1.0
**Status:** current
**Last Updated:** 2026-06-16
**Tags:** ecl, signal-quality, survivorship-bias, ml-training, emission, annotation

> Extrinsic market context is a feature for the ML model to learn from, not a gate for the system to filter on. Annotate; never suppress.

---

## What ECL Is

The **Extrinsic Confidence Layer** is the collection of market-context vectors that travel on every emitted signal as observable metadata. Current vectors: CTF score (I6 cross-timeframe alignment), HMM regime weight, zone friction, exhaustion state.

"Extrinsic" means external to the pattern that fired — these vectors describe the regime and market context at fire time, not the internal evidence quality of the setup itself. They are the inputs the ML model uses to learn *which market contexts produce better outcomes*, after observing enough outcomes to make that inference.

"Layer" is a documentation concept, not a code class. There is no `ECLLayer` object. The ECL is a contract about what must appear on every emitted signal and what must never happen to those vectors before emission.

---

## The Boundary Invariant

**If a setup meets its intrinsic detection criteria, it fires. Always.**

Extrinsic vectors are attached to the emitted signal as observable fields. They are never consulted in the emission decision. An extrinsic gate is a prior masquerading as a model — it removes a data point from the training set permanently before the model has had any chance to learn the value of that context.

This is not a heuristic or a guideline. It is a hard architectural invariant enforced by `tests/unit/intelligence/test_i7_extrinsic_contract.py` across all compliant I7 plugins.
<!-- src: tests/unit/intelligence/test_i7_extrinsic_contract.py -->

### The Regime Gate Exception

One post-emission filter is permitted: the HMM regime gate. It suppresses signal **activation** (the `pending → regime_suppressed` transition), not emission. The sequence:

```
I7 plugin fires
  → signal written to signal_events (status = 'pending')
  → SignalTracker applies regime gate
  → if regime mismatch: status → 'regime_suppressed'
```

The signal exists in `signal_events` before the gate runs. The ML model sees it. Once `counterfactual_pnl_r` is populated by CounterfactualTracker, the model can measure whether regime suppression adds value — it is no longer a blind prior.

This is the only permitted post-emission filter. Every other filter (CTF, zone friction, exhaustion) must be an annotation on the signal, not a gate.
<!-- src: src/intelligence/pipeline/signal_processor.py -->

---

## Why This Design Was Chosen

### The Gate Problem

Before Phase 123, several I7 plugins used CTF score and zone friction as emission gates — `if ctf_score < threshold: return no_signal()`. The rationale was intuitive: why fire a signal into unfavorable extrinsic conditions?

The answer is that "unfavorable" is precisely what needs to be learned, not assumed. Gating on CTF score creates a training set where the model only sees signals that fired with high CTF alignment. It cannot distinguish between:
1. The pattern is good AND CTF alignment was present
2. The pattern fires with positive expected value regardless of CTF alignment

The model assumes (1) because (2) is absent from its training data. If the pattern is actually strong enough to be profitable regardless of alignment, the gate is destroying value while appearing to help.

### What Was Rejected: Extrinsic Confidence Compositing

An early design combined extrinsic vectors into the confidence composite alongside intrinsic factors. This was rejected for a more fundamental reason than gating: it makes `raw_confidence` undecomposable by the ML model.

The ICC (Intrinsic Confidence Composite) must be pattern-internal only. If extrinsic terms enter `raw_confidence`, the model cannot tell whether a high-confidence score reflects strong pattern evidence or favorable market context. It cannot learn the independent contribution of each extrinsic vector. The decomposition problem becomes intractable at scale.

**The clean separation:**
- `raw_confidence` = intrinsic pattern evidence only (ICC)
- Extrinsic vectors = separate observable fields on `signal_events`
- ML model learns the interaction between them against `counterfactual_pnl_r`

---

## The Two Survivorship Bias Layers

ECL was designed in response to a precise survivorship bias taxonomy.

### Bias Layer 1 — Emission Suppression

**Mechanism:** Extrinsic gates calling `no_signal()` before the signal is written. The suppressed case disappears from `signal_events` entirely.

**Effect:** The training set contains only signals that fired with favorable extrinsic context. The model fits to a selection-biased population. Apparent quality is inflated because the unfavorable cases were never measured.

**Fix:** Phase 123 (ECL boundary restoration). All emission gates except the HMM regime gate were removed from I7 plugins. Every signal that meets intrinsic criteria now enters `signal_events`.

### Bias Layer 2 — Null Outcome Variable

**Mechanism:** Regime-suppressed signals have `status = 'regime_suppressed'` but no trade was executed, so `actual_pnl_r` is NULL. ML models trained on `WHERE actual_pnl_r IS NOT NULL` silently exclude all suppressed signals.

**Effect:** The model has measured what high-quality patterns produce *when the regime gate allows them*. It has never measured what they produce *when the regime gate blocks them*. It cannot evaluate the gate's actual value.

**Fix:** `counterfactual_pnl_r` on `trade_frames`, populated by the CounterfactualTracker daemon (Phase 130). Every signal hypothesis gets a measured outcome regardless of execution status. The model trains on `counterfactual_pnl_r` rather than `actual_pnl_r`, eliminating execution selection bias.

Bias Layer 1 and Bias Layer 2 are independent. Fixing Layer 1 does not fix Layer 2. Both must be addressed for the training set to be unbiased.
<!-- src: docs/foundation/glossary.md — survivorship bias entry -->

---

## Design Decisions That Were Non-Obvious

**Why is HMM regime suppression at the activation layer, not pre-emission?**

The HMM regime gate was the hardest case. Intuitively it seems like a pure filter — a trend setup in a ranging regime should not fire. Keeping it at the activation layer (not removing it, but moving it post-write) was a deliberate design choice that preserves two things:

1. The suppressed signal is observable by ML, with a counterfactual outcome measurable by CounterfactualTracker.
2. The activation-layer suppression is itself observable in the `status` field — an analyst can measure how often the regime gate fires and whether the regime-suppressed signals would have been profitable.

The gate remains, but it is now *auditable*. This is the correct architecture for any prior that has not been empirically validated: make it observable rather than hiding it in the emission decision.

**Why are extrinsic vectors top-level fields rather than embedded in `context_features`?**

`ctf_score`, `ctf_confirmed`, and `zone_friction_score` are first-class columns on `signal_events`. `context_features` is the full `capture_signal_features()` blob for the ML feature matrix. The vectors are promoted to top-level because:

- ML feature importance analysis can isolate them without parsing JSONB
- The `ctf_confirmed` boolean is the clearest categorical feature for regime-specific attribution
- Dashboard and analytics queries can filter on them without JSONB extraction
<!-- src: signal_events table — signal_events DDL in production/migrations/137_3table_schema.sql -->

---

## Relationship to Other Systems

**ECL and APR:** The threshold used to compute `ctf_confirmed` (`_MIN_CTF_SCORE = 0.25`) is an APR parameter (`threshold.global.min_ctf_score`). The threshold does not gate emission — it computes a boolean annotation. The ML model learns whether `ctf_confirmed = TRUE` predicts better outcomes, and ML discovery can refine the threshold by measuring its information value.

**ECL and SLA:** The ECL boundary invariant is what makes the SLA training set unbiased at the emission layer. Without the ECL invariant, `signal_events` would be a selection-biased sample even before the Bias Layer 2 problem arises. The two systems are designed together.

**ECL and ICC:** The ICC (Intrinsic Confidence Composite) is the complement of ECL — the pattern-internal evidence only. The clean boundary between ICC (`raw_confidence`) and ECL (top-level extrinsic fields) is what allows the ML model to attribute outcomes to the right cause.

---

## See Also

- `docs/signals/signals-ecl.md` — code surfaces, field reference, plugin implementation contract
- `docs/signals/signals-confidence-patterns.md` — Section 5: ECL; anti-patterns for I7 plugin authors
- `docs/concepts/signal-ledger-architecture.md` — SLA design; why counterfactual_pnl_r closes Bias Layer 2
- `docs/foundation/glossary.md` — ECL, ICC, SLA, survivorship bias canonical definitions
