# 033 — Refine 7 Zero-IC Features

**Status:** superseded 2026-07-19, see below.

## Features

**Correction (2026-07-01):** `momentum_rank_z`, `volume_rank_z`, `volatility_rank_z` are NOT
zero-IC — they are `NULL` for every row, never computed. Cross-reference updated 2026-07-12: the
todo that implements them was originally 013, deleted 2026-07-09 when merged into
`.planning/todos/deferred/073-cross-sectional-relative-value-feature-family.md`. Not this todo's
scope; re-add here only if IC comes back at/near zero on real (non-null) data once 073 ships.

**Remaining 4 features (`poc_dist_atr`, `va_position`, `sr_support_dist`, `sr_resist_dist`) —
re-verified 2026-07-19 against the post-143.1-07 corpus: also NOT zero-IC.** Same failure mode
as the rank features above — exactly `NULL` for all 36.7M `feature_vectors` rows, by deliberate
design (`compute_batch`'s VP/SR branch requires I3 intraday injection unavailable in the batch
backfill path; see `feature_factory.py:3722`, `backfill_feature_factory.py:1009`). The
`feature_ic_scores` rows showing `ic_value = 0` are a rank-correlation-over-all-NULL artifact,
not a measured weak signal. **Full writeup and options: [todo 153](153-vp-sr-features-null-in-batch-corpus.md).**

## Disposition

This todo's entire remaining scope (both the 3 rank features and the 4 VP/SR features) turned
out to be "never actually computed," not "computed and weak." There is nothing left to refine
under the original premise. Closing this todo; work continues under:
- Rank features → todo 073 (deferred, batched into v3.15/Phase 151 corpus rerun)
- VP/SR features → todo 153 (new, needs an operator call on backfill-replay vs. exclude-from-IC)

The two ideas originally filed against VP/SR features (session-phase normalization, sr_strength
multiplier, interaction terms) are preserved here for whoever picks up 153's option 1
(intraday-replay backfill), since they'd only become actionable once real IC data exists:

1. Session-phase normalization — proximity to POC has different predictive value at open vs.
   close.
2. sr_strength multiplier — weight S/R distance by number of prior tests at that level.
3. Interaction terms — poc_dist_atr × hmm_regime_prob may capture regime-conditional
   mean-reversion better than raw distance.
