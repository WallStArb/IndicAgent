# North Star — Intelligence Vectors Concept (v3.0 origin)

**Version:** 1.4
**Status:** Canonical for the North Star philosophy (blockquote below) only. The AlphaEngine
combination and emission machinery this doc originally described (IC-weighted ensemble,
admission gates, `alpha_events`, I7 score producers, PrecedentEngine mechanics, ECL annotator)
is superseded by `docs/plans/2026-09-26-unified-research-to-production-design.md` (adopted,
E18) and was deleted in phase 186; the book is the unit and there is no per-feature admission
gate. Condensed 2026-10-31 (todo 568); the full mechanics text stands at commit `8883924cb`.
**Tags:** intelligence-vectors, ic, renaissance

---

## North Star

> **The researcher proposes feature dimensions. The data validates or rejects each. No human defines which combinations matter — ensemble IC discovers confluence. Stability matters as much as magnitude. If IC decays, weight decays with it. Walk-forward validation is the only gate. In-sample IC is noise.**

This is the design principle that governs every architectural decision. When a design choice
requires a human to define what feature combinations are predictive - which patterns "confirm"
a setup, which conditions make a signal "higher conviction," what confluence looks like - it
violates this principle and must be rejected or reconceived.

Every component, every schema decision is evaluated against this statement. If the answer to
"who decides what matters here?" is "the researcher," that is a red flag. The answer must
always be "the measurement, on the data."

## Against the v3.5 pipeline

The principle now lives in the unified design's pipeline, not in an ensemble: features are
hypotheses proposed into `feature_vectors`; the research runner measures every candidate
through a recorded, reproducible run (E15); verdicts are counted in the research ledger with
the current N_tested; selection is StepM, promotion needs positive net expectation, and a
book is confirmed once on its own unsearched forward span (E15-E18). Confluence is discovered
by the S7 combiner over measured members, never defined by a researcher's rule. What the old
text called the ensemble's empirical discovery is now split across the measure and research
layers; the researcher's role is unchanged and narrow: generate candidate features across
orthogonal domains and let the measurement layer decide what is worth combining.

## Renaissance invariants (methodology, kept)

These were v3.0's non-negotiable measurement constraints; each has a current home in v3.5.

1. **Executable returns, not theoretical.** Targets are `ln(open[T+N+1] / open[T+1])`;
   `ln(close[T+N] / close[T])` captures untradeable overnight gaps and overstates IC. Now the
   kernel `panel.forward_returns` (`src/intelligence/research/panel.py`); new code never
   reads a target table.
2. **Walk-forward before promotion.** In-sample IC is noise; the holdout is read once, last;
   reusing it after a disappointment is p-hacking. Now E15-E18's promotion and confirmation
   rules.
3. **Stability over magnitude.** A volatile IC is intermittent luck; stability statistics
   (IC Sharpe, consistency) weigh more than raw level. Now the E17 battery and S3 guards.
4. **Regime-stratified, not pooled.** Averaging across regimes discards regime-dependent
   signal. Now `market_regimes` and regime-group stratification.
5. **Automated decay, no human gates.** Decay responds to sustained failure on independent
   evidence, with hysteresis against oscillation. Now per-member monitoring and the decay
   alarm (phase 188) and the feature lifecycle's consecutive-window rules.
6. **Causal labels only.** Measurement may use only facts knowable at time t; smoothed or
   refit labels overstate live performance. Now `temporal_integrity` and the point-in-time
   registries.
7. **Non-overlapping windows.** Overlapping return windows inflate effective N and
   understate standard errors. Now the battery and kernel target conventions.

## Intelligence vectors (future taxonomy, kept)

The system aggregates independent views of the same market; each view is a vector. The
canonical eight-vector table lives in `docs/foundation/business-requirements.md`, which cites
this doc for the bar-aligned/ambient split. V1 quant
(price/volume features), V2 microstructure, V3 macro, V4 calendar are bar-aligned: a score
per bar, directly composable with a book. V5 flow/positioning, V6 derivatives/gamma, V7
qualitative, V8 fundamental are ambient: a score per symbol at their own cadence, acting as
context that tilts conviction rather than firing anything. Ambient scores expire to neutral,
not to their last value. The measurement gate applies to all: no vector earns data spend
until its score demonstrates positive out-of-sample IC.

## Related docs

- `docs/plans/2026-09-26-unified-research-to-production-design.md` - the v3.5 pipeline that
  superseded this doc's mechanics (adopted, E18)
- `docs/foundation/principles.md` - the Renaissance working principles
- `docs/foundation/business-requirements.md` - the eight-vector taxonomy and requirements
- `docs/research/construction-verdict-ledger.md` - where hypotheses get counted
