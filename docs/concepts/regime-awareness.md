# Regime Awareness

**Version:** 2.0
**Status:** current
**Last Updated:** 2026-09-04
**Tags:** market-regime, non-stationarity, context-classification, conditioning-not-gating

> Market behavior is non-stationary — a feature's predictive power in a trending market and a ranging one are different numbers, not the same number applied differently. Every measurement must know what kind of market it was taken in.

> **Rewritten for v3.0 (2026-09-04):** The original version of this doc described the archived
> I4 regime tier and I7 hard regime gate (v2.x, no live consumer since 2026-07-02) and
> prescribed "gate, don't adjust" as the recipe. That recipe is now explicitly rejected —
> v3.0's regime layer is a **conditioning** variable for IC measurement, not a gate. Gating
> discards the ranging-regime data instead of measuring it. This is a deliberate reversal, not
> a rename; see `docs/architecture/architecture-v3-alphaengine-pipeline.md` Layer 2 for the
> full argument.

## The Problem It Solves

A trend-following feature that predicts well in a trending market will show weak or negative IC in a ranging one. A model that measures IC globally — "this feature's average IC is 0.03" — buries the regime-conditional structure inside a single number, and worse, a hard gate that only trades the feature "when trending" throws away every ranging-regime observation and never lets you learn what actually happens to the feature there. The fix isn't a smarter threshold — it's treating regime as something IC is measured *against*, not something that decides whether IC gets measured at all.

## The Principle

Classify regime continuously, at more than one scope. Condition every IC estimate on regime state. Never discard an observation because its regime looks "wrong" for a feature.

This requires:
1. **Independent regime scopes, not just dimensions** — a per-instrument state and a market-wide state answer genuinely different questions and must not be collapsed into one label
2. **Causal classification only** — a regime label assigned to bar T must never be informed by information from bars after T; full-sequence decoding (Viterbi) is look-ahead bias, not a convenience
3. **Conditioning, not gating** — every IC estimate is computed per regime state, so a feature's ranging-regime behavior is measured and kept, and the ensemble applies regime-appropriate weights at inference time rather than an on/off switch
4. **A closed evidence bar for new regime candidates** — a proposed regime dimension must clear a null-arm (scrambled-data) control and demonstrate it sharpens IC beyond what the existing regime axis already captures before being added

## How IndicAgent Applies It

Two independent HMM systems, answering different questions, feeding IC as stratification variables — not signal gates:

| System | Scope | Question answered | Method |
|--------|-------|--------------------|--------|
| Idiosyncratic regime (`regime_writer.py`) | Per `(symbol, timeframe)` | What state is *this instrument* in? | Gaussian HMM, K=5 states (`trending_up`/`transition_up`/`ranging`/`transition_down`/`trending_down`), K chosen via BIC study |
| Systematic regime (`cross_sectional_regime_model.py`) | Cross-sectional, market-wide | What's the market-wide backdrop right now? | VIX and breadth-style signals across the peer group, independent of any single symbol's own price history |

A symbol can be in its own idiosyncratic uptrend while the systematic regime reads risk-off — both facts are kept, not collapsed into one number, because a broad selloff and an idiosyncratic single-name breakdown are different phenomena that may carry different forward-return implications.

**Causal-correctness discipline:** `regime_writer` uses forward-filter (alpha-pass) decoding only, never `model.predict()` (Viterbi) — the schema enforces this structurally, since `feature_vectors.regime_label_source` only accepts `{'filtered', 'unknown'}`. This is a direct lesson from V2's `intelligence_features` table, whose Viterbi-decoded regime labels are a documented reason that table is not reused in V3.0.

**IC stratification, not gating:** `ic_engine` measures IC per feature × symbol × timeframe × regime × lookahead. There is no plugin-level "valid regime" declaration and no hard suppression — a feature's IC in every regime state is measured and passed to the ensemble, which learns regime-appropriate weighting rather than having a human pre-decide which regimes a feature is "allowed" to fire in. `regime_volatility` is currently the active regime dimension the ensemble conditions on.

**Evidence bar in practice:** per-symbol trend and percentile-rank regime candidates (a proposed third and fourth regime axis) were measured against this bar in 2026-09 and closed dead — neither sharpened IC beyond what `regime_volatility` already captures. A walk-forward HMM refit (closing the parameter-level lookahead where per-symbol HMM parameters are fit on the full training window before causal decoding) was built and unit-tested, but the Gate 4 measurement on live SPY/1h data did not show a clear prediction-quality improvement — it's parked behind an APR flag, not wired into production, and not re-litigated without new evidence.

## Invariants

- Regime is a stratification variable for IC — never a hard gate that discards observations.
- Regime decoding is causal only — no Viterbi, no full-sequence decode feeding a live label.
- `feature_vectors.regime_label_source` accepts only `{'filtered', 'unknown'}` — no code path can write a look-ahead-biased label.
- A new regime dimension must clear a null-arm (scrambled-data) control and beat the existing regime axis's IC contribution before being added — a regime candidate that doesn't sharpen IC beyond `regime_volatility` stays closed, not re-proposed under a different name.
- Idiosyncratic and systematic regime are measured and kept separately — never collapsed into one label.

## Recipe

When designing regime awareness for a new system:

1. **Separate scope from dimension.** "What state is this instrument in" and "what's the market-wide backdrop" are different questions even before you get to volatility vs. trend vs. momentum — decide scope first.
2. **Classify causally.** A regime label must only ever depend on information available at decode time. Full-sequence or globally-fit decoding is look-ahead bias, even when it looks like "just a smoother label."
3. **Condition, don't gate.** Measure a feature's behavior in every regime state and let a downstream combiner weight accordingly. A hard gate that skips measurement in the "wrong" regime destroys the exact data you'd need to find out you were wrong about which regime the feature works in.
4. **Require a null-arm control before adding a dimension.** More regime dimensions without evidence is overfitting with a market-structure narrative attached. A new axis must beat existing conditioning on a held-out measurement, against a scrambled-data control, before it's kept.
5. **Track performance per regime cell, but expect thin cells.** More regime granularity means less data per cell and less statistical power — this is exactly why the evidence bar in (4) exists, not an argument against conditioning itself.

## See Also

- Implementation: `docs/architecture/architecture-v3-alphaengine-pipeline.md` — Layer 2, full regime-layer detail and the gating-vs-conditioning argument
- Superseded: `docs/architecture/architecture-v2-event-driven-pipeline.md` — the archived I4 tier / I7 hard gate this doc previously described
- Related concept: `docs/concepts/progressive-intelligence-extraction.md` — regime's place in the layer stack
- Related concept: `docs/concepts/evidence-graded-signals.md` — the evidence bar a regime candidate (or any feature) must clear
