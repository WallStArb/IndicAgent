# 037 — Pilot IC Test on Hand-Picked Interaction Primitives

**Status:** COMPLETE (2026-07-10) — **PASS**, triggers Phase 150 planning
**Priority:** P2 — cheap, high information value, settles a real open question with existing infrastructure
**Gate:** Phase B corpus re-run complete (need a clean, corrected corpus and IC Engine to measure against)
**Concept doc:** `docs/research/interaction-factory.md` — this todo is the evidence-gathering step that doc's "Build Trigger" now requires before Interaction Factory itself is built

## Result (2026-07-10)

Ran `scripts/ops/alpha/ops_interaction_primitives_pilot.py` against the live corpus
(implemented in `docs/plans/2026-07-09-interaction-primitives-partial-ic-pilot-plan.md`,
executed via subagent-driven development on branch
`worktree-interaction-primitives-partial-ic-pilot`). Two real bugs were found and fixed
during execution (not scope changes — both preserved the plan's exact measurement design):
a redundant-scan bug (864 independent full-tf-partition scans instead of 4, ~80hr runtime)
and a memory blowup on the largest tf partition (unbounded Python-list accumulation for the
25M-row `tf='5m'` fetch). Both fixed, reviewed, and validated live before this final run.

**864/864 cells measured, all numerically valid. 192/864 (22.2%) pass BH-FDR
(alpha=0.05).**

Per-feature breakdown (all 8 of the 8 already-live interaction primitives, `n_cells=108`
each — 9 regimes x tf/lookahead combinations):

| feature | n_pass | pct_pass | min partial_ic | max partial_ic |
|---|---|---|---|---|
| `vol_body_product` | 33 | 30.6% | -0.1274 | +0.1292 |
| `ret_vol_ratio_fast` | 31 | 28.7% | -0.1415 | +0.1927 |
| `ret_vol_product_fast` | 29 | 26.9% | -0.2177 | +0.2585 |
| `price_vol_corr_fast` | 28 | 25.9% | -0.0833 | +0.1940 |
| `price_vol_corr_slow` | 26 | 24.1% | -0.1727 | +0.1980 |
| `vol_skew_product` | 22 | 20.4% | -0.0998 | +0.1710 |
| `range_vol_product` | 16 | 14.8% | -0.1593 | +0.0697 |
| `up_vol_body_diff` | 7 | 6.5% | -0.1277 | +0.1753 |

**Verdict: PASS.** 22.2% overall pass rate is well above the plan's own pre-registered
"single digits to low tens of survivors" calibration anchor for a real signal (that anchor
implied roughly 1-10% of an 864-cell population; 192 survivors is 2-20x that). Critically,
the signal is broad-based, not a fluke concentrated in one feature: every one of the 8
interaction primitives clears a non-trivial pass rate (weakest at 6.5%, not near-zero),
and both magnitude extremes (partial_ic up to |0.26|) occur on the smaller, longer-lookahead
`tf=1d` cells where N is naturally lower but the effect size is largest — consistent with a
real, not noise-driven, interaction effect that the parent atomics do not already explain.

This is genuine evidence that atomic features are NOT fully IC-saturated and second-order
interaction effects carry real incremental signal in this dataset. **Triggers Phase 150
(Feature Primitives Expansion + Theory-Motivated Interaction Layer) planning** — per this
todo's own guidance, planning is a `/gsd-discuss-phase` decision, not auto-created by this
result.

Caveat carried forward from the plan's Global Constraints: this is a decision-gate
measurement, not a promotion-grade one (approximates, not byte-for-byte replays,
`ic_engine.py`'s exact per-symbol subsampling chunk boundaries) — cite the PASS verdict as
the trigger to plan Phase 150, not as a promotion-ready number for any of these 8 features
individually without re-deriving through the full walk-forward apparatus.

## Why

Interaction Factory (systematic combinatorial generation of ~30,000 feature-pair candidates) has an unproven premise: that atomic features are IC-saturated and second-order interaction effects are where the next real signal lives. Nothing currently establishes this. Building the full 30K-candidate sweep before checking this would risk spending significant compute on an unproven hypothesis, and a council review (2026-07-01) concluded the honest yield estimate after proper batch-FDR + partial-correlation control is likely single digits to low tens of survivors, not hundreds.

There's a cheap, already-available way to get a real empirical answer: `renaissance-primitives-ohlcv.md` already specifies ~20-30 hand-picked "Interaction Primitives" (`vol_body_product`, `price_vol_corr`, etc.) as a "reasonable starting point and sanity check." Nobody has actually measured them.

## What

1. Add the ~20-30 hand-picked interaction primitives from `renaissance-primitives-ohlcv.md` as ordinary Feature Factory columns (`domain='feature'` equivalent, same as any atomic feature) — trivial backfill cost at this scale, zero new infrastructure (no generator, no `compound_ic_scores` table, no `CompoundPrimitiveEvaluator` needed for a pilot this small).
2. Run them through the existing, already-live IC Engine — same corpus, same methodology (Spearman IC, Fisher-z CI, BH-FDR, walk-forward embargo) already applied to every atomic feature.
3. **Critical: measure incremental IC after controlling for parent atomics (partial correlation), not naive IC.** A product or ratio of two features shares substantial variance with its parents by construction — naive IC on the compound will be inflated. The real question is whether it explains variance its parents don't already explain.

## Decision rule

- **If the pilot cohort shows genuine incremental IC** (survives FDR, non-trivial after partial-correlation control) for a meaningful fraction of the ~20-30 candidates → real evidence that interaction effects carry signal in this dataset. That's the trigger condition to plan Interaction Factory's full systematic build.
- **If the pilot cohort shows near-zero incremental IC** → strong evidence against the premise. Shelve Interaction Factory outright rather than leaving it as a permanently deferred "someday" idea — a null result on the cheap, favorably-selected (hand-picked, domain-intuition-backed) cohort is a stronger signal than a null result would be on randomly-generated pairs.

## Effort

Small — 1-2 days. Mostly Feature Factory column additions + backfill; the measurement step reuses IC Engine as-is.
