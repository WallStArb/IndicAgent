# AlphaEngine — Alternative Data Extension

**Date:** 2026-06-23
**Status:** idea
**Milestone:** post-v3.0 Phase A/B

---

## Core Insight

AlphaEngine is data-agnostic by design. The IC methodology has one requirement: a numeric feature value at time T with a causally-known forward return at T+N. The measurement apparatus - Spearman IC, IC Sharpe, FDR correction, regime conditioning, effective-N - operates on a matrix of `(symbol, tf, ts, feature_value)` rows. The source is irrelevant.

The question per data type is not "can AlphaEngine handle it" but "what are the ingestion and alignment constraints."

---

## Data Types

### Flows

Options net delta, dark pool %, institutional order imbalance. Already intraday numeric values. Slot directly into `feature_vectors` as new columns. IC measured at 5m/15m TF same as existing features. Lowest-friction extension and almost certainly has measurable IC on rate-sensitive ETFs.

### Fundamentals

EPS surprises, P/B, earnings revision ratios. IC framework is exactly how Barra and Axioma measure factor quality - this is the canonical use case. Constraint: fundamentals update quarterly, so IC is only meaningful at daily TF with fill-forward "as-of" values. Requires a `fundamental_snapshots` table keyed on `(symbol, report_date)` and a fill-forward join to `feature_vectors` at daily resolution.

### Qualitative

News sentiment, transcript tone, analyst language. Requires a conversion step first: NLP pipeline produces a numeric score per event (VADER, FinBERT, or LLM-graded tone score). Once numeric, IC measurement is identical. Hard problem: look-ahead in timestamps - news published after-hours must not bleed into the bar it followed. Timestamp discipline is more important than the NLP choice.

### Kalshi

Prediction market probabilities. Already bounded [0,1] and update continuously. Two uses:

1. **Direct IC** - measure IC between Kalshi event probability and corresponding ETF forward returns (e.g., "Fed +50bps" probability vs. TLT 5d return).
2. **Regime conditioning** - Kalshi probability defines a regime stratum; compute IC per stratum separately. "Momentum IC in low-Fed-risk regimes vs. high-Fed-risk regimes" is a testable stratification that price-only features cannot provide. Arguably more powerful than direct IC use.

---

## Architectural Implication

The Feature Factory and `feature_vectors` currently assume all features derive from `market_data_ohlcv`. Clean extension: a second table `alt_feature_vectors` (or additional nullable columns) keyed on `(symbol, ts, data_source)`. The IC engine joins both. Effective-N handles redundancy between price-derived and alt-data features automatically.

**Key risk:** alternative data with shorter history than price. IC Sharpe requires minimum N=20,000 bars (Phase 138's gate). Daily fundamentals at 20 years = ~5,000 rows per symbol. Kalshi history is shorter still. This requires a separate IC gate per data source calibrated to its available N, and alt-data IC estimates should not be blended with price IC estimates until each is independently validated.

---

## Recommended Order

1. **Flows** - highest signal, same cadence as price, lowest infrastructure delta
2. **Kalshi as regime conditioning** - not return prediction; stratifies existing price IC estimates by macro event probability
3. **Fundamentals** - after corpus depth is established; needs fill-forward infrastructure
4. **Qualitative** - infrastructure is right but timestamp discipline in news ingestion is a meaningful operational risk worth isolating last

---

## See Also

- `docs/intelligence/intelligence-alphaengine.md` - AlphaEngine concept doc
- `docs/ideas/vision-06-flowagent.md` - FlowAgent vision (flows ingestion)
- `docs/ideas/vision-07-fundagent.md` - FundAgent vision (fundamentals ingestion)
- `docs/ideas/ai-10-qualitative-intelligence-layer.md` - qualitative layer design
