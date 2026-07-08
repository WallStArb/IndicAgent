# 155 — Measurement diagnostics: empirical null calibration + IC hit-rate/magnitude decomposition

**Source:** `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §7 (L4-2, L4-4).
**Priority:** medium — cheap, standalone, no schema dependency; good candidates to run against
the current corpus once the ic_engine incident (todo 151) is resolved and a fresh rerun completes.
**Gate:** none structurally; practically wants a healthy `feature_ic_scores` table to run against.

## L4-2 — Empirical null calibration via circular-shift permutation

The analytic inference chain (stride subsampling → Spearman → Fisher-z CI → HAC Sharpe) rests on
assumptions (post-stride independence, Fisher-z normality at these Ns) never validated end-to-end
on this data. Diagnostic: circularly shift the forward-return series by a random large offset
(preserves autocorrelation structure, destroys alignment), recompute the full IC pipeline, repeat
~200 times for a sample of cells, compare the empirical null IC distribution against what the
analytic p-values assume.

Related dead weight this settles either way: `alpha.ic.bootstrap_*` APR keys exist with zero
readers (bottomup audit §2.3). If analytic and empirical nulls agree, delete the keys with
evidence; if not, implement the block bootstrap in the kernel and the keys finally get their
reader.

**Mechanics:** one-off script over the existing corpus + kernel functions; CPU-bound, the
existing `ProcessPoolExecutor` pattern handles it.

## L4-4 — IC decomposition: hit-rate × magnitude

A single Spearman IC conflates directional accuracy (sign agreement fraction) and magnitude
alignment (are the big predictions the big moves). Two predictors with identical IC can have
opposite profiles and decay differently (magnitude alignment usually dies first as an edge
crowds). Report both as diagnostic columns (no gate change): `sign_hit_rate` and
IC-conditional-on-large-`|prediction|`. Cheap kernel additions; sharpens Phase 143's decay
monitors for free.
