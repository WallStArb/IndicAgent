# Evidence-Graded Signals

**Version:** 1.0
**Status:** stale (v2.x, see banner)
**Last Updated:** 2026-05-30
**Tags:** signal-quality, confluence, multi-factor, evidence

> A signal requires agreement from multiple independent evidence sources — no single indicator can produce a tradeable signal.

> **Staleness note (2026-08-01):** This doc describes the Composite Intelligence Score (CIS)
> gating I7 setup plugins — the ARCHIVED v2.x signal-quality system, with no live consumer as
> of 2026-07-02 per CLAUDE.md. Not yet rewritten for v3.0 -- tracked for a future doc pass, not
> fixed here.

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

The Composite Intelligence Score (CIS) aggregates 6 independent buckets into a directional score in [-1.0, +1.0]:

| Bucket | Weight | Evidence Source |
|--------|--------|----------------|
| Trend | 0.20 | Kalman slope, trend regime, SMC trend direction, CTF alignment |
| Momentum | 0.20 | RSI, MACD histogram, ROC, momentum bias, divergence |
| Structure | 0.15 | Swing pattern, BOS/CHoCH detected and direction |
| Pattern | 0.05 | Chart patterns (double top/bottom, H&S, triangle breakout) |
| Institutional | 0.25 | Order blocks, FVGs, supply/demand zone position |
| Regime | 0.15 | HMM state probabilities, BOCPD changepoint stability, CTF regime agreement |

**Gate:** A signal requires `|cis_score| > 0.35` AND 3+ buckets agreeing with the signal direction. A high-magnitude score from only 2 buckets fails the gate.

**Independence design:** Each bucket reads from a different analytical dimension — trend (statistical), momentum (oscillator consensus), structure (price geometry), pattern (visual formations), institutional (order flow), regime. Correlation between buckets is monitored; high inter-bucket correlation reduces the gate threshold benefit.

**Adaptive weights:** Bootstrap weights (version 0) are manually tuned. The architecture supports learned weights from the `cis_weights` DB table — logistic regression over historical signal outcomes per bucket. Every `CISResult` carries `weights_version`; all signals in `signal_ledger` are traceable to the exact weight set that produced them.

**`active` signals:** Always derived as `[s for s in all_ranked if s.get("regime_eligible", True)]` — never from the raw `signals` list. The aggregator's `active` field reflects both CIS gating and regime suppression.

## Invariants

- No signal may fire from a single indicator or bucket alone. CIS gate is `|score| > 0.35` AND `agreeing_buckets >= 3`.
- CIS buckets must read from statistically independent evidence sources. Two buckets reading the same indicator family reduce the gate's statistical value.
- The `active` list must derive from `all_ranked`, not from raw `signals`.
- All signals in `signal_ledger` carry `bucket_scores` (JSONB) and `weights_version` (INTEGER) for full audit.
- `calibrated_confidence` in Kafka signal payloads may be null — gate on `raw_signal.get("confidence")` or `raw_signal.get("pre_quality_confidence")`.

## Recipe

When designing a multi-source confirmation system:

1. **Test bucket independence.** Compute pairwise correlations between your candidate evidence sources. Remove or merge sources with correlation > 0.7 — they provide no additional information.
2. **Calibrate gate threshold empirically.** Too low = too many false positives. Too high = too few signals, insufficient data for learning. Start with the threshold that produces 10-15 signals per instrument per week.
3. **Require both magnitude AND breadth.** A single strong bucket score does not equal confirmation. Require a minimum number of agreeing buckets separately from the score magnitude.
4. **Design for adaptive weights from day one.** Store which bucket produced which score with every signal. You will want to learn weights — you cannot if you did not capture the intermediate scores.
5. **Version your weight sets.** When weights change, signals produced under old weights should not be compared against signals under new weights without version-stratified analysis.
6. **Calibrate, do not just score.** Raw confidence scores are biased. Isotonic regression calibration maps them to empirically-correct probabilities. Uncalibrated scores mislead position sizing.

## See Also

- Implementation: `docs/intelligence/intelligence-foundation.md` — CIS architecture, 6-bucket detail, adaptive weights, calibration chain
- Code: `src/intelligence/trading/cis_scorer.py`
- Related concept: `docs/concepts/regime-awareness.md` — how I4 regime feeds the CIS regime bucket
- Related concept: `docs/concepts/adaptive-intelligence.md` — how CIS weights are learned from outcomes
