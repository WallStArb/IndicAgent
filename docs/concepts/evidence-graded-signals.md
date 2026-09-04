# Evidence-Graded Signals

**Version:** 2.0
**Status:** current
**Last Updated:** 2026-09-04
**Tags:** signal-quality, confluence, multi-factor, evidence

> A signal requires agreement from multiple independent evidence sources — no single indicator can produce a tradeable signal.

> **v2.x → v3.0 note:** The Composite Intelligence Score (CIS) described below gated I7 setup
> plugins in the v2.x typed-bus pipeline. That pipeline has no live consumer since 2026-07-02;
> `cis_scorer.py` and its callers (`aggregator.py`, `signal_processor.py`, `weight_updater.py`,
> `confidence_calibrator.py`) still exist in the tree but are dormant code, not a running path.
> The principle — require statistically independent evidence sources to agree, gated on both
> magnitude and breadth, before a signal is trusted — carries forward unchanged into v3.0's
> **ensemble alpha** mechanism (`services/ensemble_trainer.py` / `services/ensemble_ic_engine.py`),
> described in "The v3.0 Successor" below. The CIS section is kept for its worked example of the
> principle at plugin granularity; it does not describe live behavior.

## The Problem It Solves

A single indicator firing is noise. Any individual technical signal (RSI oversold, MACD crossover, support level touch) has a false positive rate high enough to make it unusable as a standalone trading rule. The naive approach — "if RSI < 30, buy" — might have a 35% win rate globally, which is negative edge after costs. The problem compounds: running 36 setup plugins per bar means at least a few will always fire on any bar just by chance.

Majority voting does not solve this — it ignores signal quality. A hand-tuned priority ordering goes stale as market regimes shift. Highest-confidence-wins is fragile: a confident signal in the wrong regime is still a bad trade.

## The Principle

Require agreement from multiple statistically independent evidence sources before acting. Independence is critical: correlated sources add no information. RSI and Stochastic are both momentum oscillators — their agreement is less valuable than RSI and BOS (price structure) agreeing, because BOS is capturing something RSI cannot.

The confirmation system must be:
1. **Multi-dimensional** — evidence from different parts of the intelligence pipeline
2. **Independence-gated** — buckets must read from different indicator families
3. **Directionally consistent** — a bullish signal requires bullish evidence across buckets
4. **Threshold-gated** — weak agreement is insufficient; a minimum score AND minimum bucket count are both required
5. **Adaptive** — bucket weights should learn from outcomes, not remain static

## How IndicAgent Applies It

### The v3.0 Successor (live)

Instead of hand-designed indicator buckets voting on a single bar, v3.0 combines statistically-validated *features* (each independently measured for predictive power) into one ensemble alpha score:

- **Evidence source = a feature's measured IC**, not a hand-picked technical indicator. Only cross-sectional, statistically significant (CI + BH-FDR), walk-forward-confirmed features feed the ensemble — significance alone isn't sufficient (it doesn't distinguish real signal from the tail of expected false discoveries BH-FDR budgets for); `passes_walkforward=true` requires the same effect to reproduce out-of-sample across independent time folds.
- **Independence is enforced statistically, not by category design.** Ledoit-Wolf cluster deflation (`cluster_deflate_weights`) downweights correlated features after IC-based weight derivation — the direct v3.0 analog of CIS's "independence-gated buckets."
- **Threshold-gated emission:** `alpha_publisher` only emits when the ensemble score crosses `alpha.quant.threshold.{tf}` (APR key) AND the effective-N gate (`alpha.ensemble.effective_n_gate`) is met — magnitude and evidence-mass are both required, same shape as CIS's `|score| > 0.35 AND agreeing_buckets >= 3`.
- **Adaptive, version-tracked weights:** `ensemble_weights` carries one row per `(tf, regime, weight_version, feature_name)` — every `ensemble_alpha` score is traceable to the exact weight set that produced it, same traceability requirement CIS's `weights_version` enforced.
- **Promotion is gated, not automatic:** which features are even eligible to enter the ensemble is governed by the Unified Concept Registry (`docs/foundation/unified-concept-registry.md`) — a feature must clear its `concept_gate` before it can contribute evidence at all. See `docs/concepts/adaptive-intelligence.md`.

### The CIS Mechanism (historical, v2.x, kept as worked example)

The Composite Intelligence Score (CIS) aggregated 6 independent buckets into a directional score in [-1.0, +1.0]:

| Bucket | Weight | Evidence Source |
|--------|--------|----------------|
| Trend | 0.20 | Kalman slope, trend regime, SMC trend direction, CTF alignment |
| Momentum | 0.20 | RSI, MACD histogram, ROC, momentum bias, divergence |
| Structure | 0.15 | Swing pattern, BOS/CHoCH detected and direction |
| Pattern | 0.05 | Chart patterns (double top/bottom, H&S, triangle breakout) |
| Institutional | 0.25 | Order blocks, FVGs, supply/demand zone position |
| Regime | 0.15 | HMM state probabilities, BOCPD changepoint stability, CTF regime agreement |

**Gate:** A signal required `|cis_score| > 0.35` AND 3+ buckets agreeing with the signal direction. A high-magnitude score from only 2 buckets failed the gate.

**Independence design:** Each bucket read from a different analytical dimension — trend (statistical), momentum (oscillator consensus), structure (price geometry), pattern (visual formations), institutional (order flow), regime. Correlation between buckets was monitored; high inter-bucket correlation reduced the gate threshold benefit.

**Adaptive weights:** Bootstrap weights (version 0) were manually tuned. The architecture supported learned weights from the `cis_weights` DB table — logistic regression over historical signal outcomes per bucket. Every `CISResult` carried `weights_version`; all signals in `signal_ledger` were traceable to the exact weight set that produced them.

**`active` signals:** Always derived as `[s for s in all_ranked if s.get("regime_eligible", True)]` — never from the raw `signals` list. The aggregator's `active` field reflected both CIS gating and regime suppression.

## Invariants

**Live (v3.0 ensemble):**
- No feature enters the ensemble without clearing IC significance (CI + BH-FDR), cluster-deflation, and walk-forward confirmation.
- `alpha_publisher` is the sole writer to `alpha_events` — emission requires both the score threshold and the effective-N gate.
- Every `ensemble_alpha` row is traceable to its `weight_version`.
- IC measurement is executable-returns-only (`return_type = 'executable_open_to_open'`) — see `docs/foundation/adaptive-parameter-registry.md` and CLAUDE.md's Invariant 1.

**Historical (v2.x CIS, no live consumer):**
- No signal fired from a single indicator or bucket alone. CIS gate was `|score| > 0.35` AND `agreeing_buckets >= 3`.
- CIS buckets read from statistically independent evidence sources.
- All signals in `signal_ledger` carried `bucket_scores` (JSONB) and `weights_version` (INTEGER) for full audit.
- `calibrated_confidence` in Kafka signal payloads could be null — gate on `raw_signal.get("confidence")` or `raw_signal.get("pre_quality_confidence")` (this specific gotcha is still live guidance per CLAUDE.md's Swarm raw signal confidence note, for whichever future consumer reads that payload shape again).

## Recipe

When designing a multi-source confirmation system:

1. **Test bucket independence.** Compute pairwise correlations between your candidate evidence sources. Remove or merge sources with correlation > 0.7 — they provide no additional information.
2. **Calibrate gate threshold empirically.** Too low = too many false positives. Too high = too few signals, insufficient data for learning. Start with the threshold that produces 10-15 signals per instrument per week.
3. **Require both magnitude AND breadth.** A single strong bucket score does not equal confirmation. Require a minimum number of agreeing buckets separately from the score magnitude.
4. **Design for adaptive weights from day one.** Store which bucket produced which score with every signal. You will want to learn weights — you cannot if you did not capture the intermediate scores.
5. **Version your weight sets.** When weights change, signals produced under old weights should not be compared against signals under new weights without version-stratified analysis.
6. **Calibrate, do not just score.** Raw confidence scores are biased. Isotonic regression calibration maps them to empirically-correct probabilities. Uncalibrated scores mislead position sizing.

## See Also

- Live substrate: `services/ensemble_trainer.py`, `services/ensemble_ic_engine.py` — IC-weighted ensemble, BH-FDR, walk-forward gating
- Live substrate: `docs/foundation/unified-concept-registry.md` — feature promotion gating that feeds the ensemble
- Historical implementation: `docs/intelligence/intelligence-foundation.md` — CIS architecture, 6-bucket detail, adaptive weights, calibration chain
- Historical code: `src/intelligence/trading/cis_scorer.py` (dormant, no live caller path)
- Related concept: `docs/concepts/regime-awareness.md`
- Related concept: `docs/concepts/adaptive-intelligence.md` — evidence-gated promotion lifecycle (UCR)
