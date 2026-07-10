# 092 — Empirical threshold calibration for `equity_regime_model.py`'s vix/breadth cuts (todo 026's P3, split out)

**Source:** Split out of todo 026 (HMM Regime Audit & Optimization, moved to `deferred/`
2026-07-10 since most of its remaining scope — P1b/P2a/P2b/P2c — genuinely batches into Phase
144's `ic_engine` re-run). This one sub-item, P3, is pulled back out as its own standalone
`pending/` todo because it has fresh evidence making it urgent now, unlike the rest of 026.

**Priority:** medium-high — no longer just general hygiene; see the live-path finding below.
**Gate:** none. Runs against the current corpus today.

## What's open

`equity_regime_model.py`'s cut points (`alpha.regime.vix_low_pct`/`vix_high_pct` = 0.33/0.67,
`alpha.regime.breadth_bear`/`breadth_bull` = 0.40/0.60, migration 182) were moved into APR
(tunable) but are still sitting at their original guessed `[initial_estimate]` defaults — no
empirical recalibration has ever actually happened.

## Why this is now live-path relevant, not just hygiene

Todo 026's 2026-07-09 finding: a fresh corpus IC leaderboard review found the top of
`feature_ic_scores` by `|ic_value|` dominated by regime-conditional cells (`high_bear`,
`mid_bull`, etc.) at IC 0.15-0.42. Investigated as a possible HMM parameter-lookahead leak
(P4a) — ruled out (that leak exists in code but currently measures zero live rows; per-symbol
HMM is routed around entirely by the `equity_model_enabled` toggle, which defaults to the
cross-sectional VIX×breadth model this todo's cut points feed).

Two remaining explanations were identified, one of which is this todo:
1. FDR-tail concentration (survivorship bias inherent to "top IC" leaderboard framing — not a
   bug, expected ~48 false discoveries at `fdr_alpha=0.05` across 972 qualifying cells; matches
   the observed count exactly).
2. **These arbitrary, never-recalibrated cut points** — they don't inject look-ahead bias, but
   can produce regime buckets that don't correspond to behaviorally distinct states, adding
   noise that (combined with #1) plausibly concentrates extreme IC values at the tail.

Nothing here proves #2 is the dominant explanation, but it's evidence-flagged as a live-path
suspect now, not merely "would be nice to calibrate someday."

## Proposed approach

Same shape as EM-CAL (todo 065): treat the 4 cut points as a small calibration study against
the current corpus rather than accepting the guessed defaults further. Compare candidate cut
points (e.g. percentile-based on the trailing distribution vs the current fixed 0.33/0.40/0.60/
0.67) via regime-conditional IC separation on POOLED strata, same methodology already
established for other APR threshold calibrations in this codebase.

Full context/history: `.planning/todos/deferred/026-hmm-regime-audit-optimization.md`.
