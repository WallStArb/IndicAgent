---
status: pending
priority: P3
filed: 2026-08-03
source: T5-at-5m float16 downcast overflow investigation
---

## What

Diagnosing a `RuntimeWarning: overflow encountered in cast` while trying to run T5's non-linear
combiner replication at 5m with `feature_dtype=np.float16` (a memory necessity at that row
count, see `docs/research/data-edge-source-thesis.md`'s T5 section), a full-corpus scan
(`MAX(ABS(col))` across all 253 `feature_vectors` float columns, 5m equity rows only) found
exactly 3 columns exceed float16's ~65504 max magnitude:

| Column | max_abs |
|---|---|
| `hmm_duration` | 367,391 |
| `weekly_r2_dist_atr` | 96,513 |
| `weekly_r1_dist_atr` | 77,210 |

These magnitudes look like a genuine upstream anomaly, not legitimate large-but-valid feature
values:

- **`hmm_duration`**: presumably a per-regime bar-count duration counter. 367,391 bars at 5m
  spacing is ~3.5 years of continuous, uninterrupted 5m bars in one regime state without a
  reset -- implausible for any real regime-detection HMM, which should transition states far
  more often than once every 3+ years. Worth checking whether this counter has a reset bug (not
  clearing on a real regime transition) or is accumulating across some boundary it shouldn't
  (e.g., across symbol changes in a shared computation, or never resetting after a corpus
  rebuild/backfill).
- **`weekly_r1_dist_atr`/`weekly_r2_dist_atr`**: ATR-normalized distance features. The classic
  cause of an extreme normalized-distance blowup is dividing by a near-zero ATR (a genuinely
  flat/illiquid period) -- worth checking whether these features have any ATR floor/guard
  against near-zero denominators, the same class of numerical-stability issue other
  ATR-normalized features in this codebase may already guard against (check for a precedent
  pattern before deciding on a fix).

## Row-count follow-up (2026-08-03, same session)

Ran a `COUNT(*) FILTER (WHERE abs(col) > 65504)` against the same 25,443,790-row 5m equity
corpus to answer "Next step (2)" below directly rather than guess from the max alone:

| Column | rows over threshold | % of corpus | p50 | p90 | p99 |
|---|---|---|---|---|---|
| `hmm_duration` | 3,881,319 | 15.25% | 19 | 107,882 | 298,963 |
| `weekly_r2_dist_atr` | 6 | 0.00002% | -- | -- | -- |
| `weekly_r1_dist_atr` | 3 | 0.00001% | -- | -- | -- |

This changes the read on both:

- **`hmm_duration` is broad, not a rare edge case** -- even the p90 (107,882 bars, ~374 days of
  continuous same-regime at 5m) is already implausible, and 1 in 7 rows exceeds the float16
  threshold. Strengthens the "accumulation/reset bug" hypothesis over "legitimate large outlier."
- **`weekly_r1_dist_atr`/`weekly_r2_dist_atr` are a genuine rare tail** -- 3 and 6 rows
  respectively out of 25.4M. Consistent with the near-zero-ATR-denominator hypothesis for a
  small number of genuinely flat/illiquid bars, not a systemic computation problem.

## Impact and current workaround (updated 2026-08-03)

Because of the row-count split above, the float16-scoped 5m fetch path
(`scripts/analysis/_t5_nonlinear_combiner_shared.py`) now treats these two cases differently
instead of excluding all three columns uniformly:

- `hmm_duration` stays fully excluded (`FLOAT16_UNSAFE_COLS`) -- clipping a distribution that's
  broken for 15% of rows would fabricate a fake ceiling spike rather than recover real signal.
- `weekly_r1_dist_atr`/`weekly_r2_dist_atr` are no longer excluded -- the ~9 offending cells are
  clipped to `_FLOAT16_CLIP_MAGNITUDE` (60,000) before the float16 cast instead, preserving the
  feature for the other ~25.4M rows. Excluding the whole column to guard 9 cells was needlessly
  discarding signal once the row counts were known.

This still doesn't answer whether `hmm_duration`'s values are correct for live consumers
(`ic_engine`, `ensemble_trainer`, anything reading `feature_vectors` at float32/float64, where
this would never surface as an overflow but could still be silently wrong) -- that root-cause
work is still open.

## Next step

Not urgent, not blocking any current work. When picked up: (1) find `hmm_duration`'s computation
in `feature_factory.py` or wherever it lives and check for a reset-on-transition bug or an
accumulation boundary it shouldn't cross (e.g. across symbols or a corpus rebuild), given the
broad 15.25%-of-rows incidence now confirmed above; (2) `weekly_r1_dist_atr`/`weekly_r2_dist_atr`
are lower priority given the confirmed-rare (3-6 row) incidence -- worth a quick check for an
ATR floor/guard against near-zero denominators if picked up alongside `hmm_duration`, but not
worth a dedicated pass on its own.

## T5-training-integrity check (2026-08-03, same session) -- closes the concern for T5 specifically

Raised because `hmm_duration` was NOT in `_t5_nonlinear_combiner_shared.py`'s universal
`EXCLUDE_COLS` -- only excluded from the float16-scoped 5m fetch, meaning the already-completed
1h/15m T5 runs (this session's headline "substantial at 1h/15m" finding) trained on it. Checked
whether it's tf-specific before assuming urgency:

- **The bug is present at every tf, not just 5m** -- `max(abs(hmm_duration))` is
  4,819/30,077/130,242/367,391 bars at 1d/1h/15m/5m respectively. 1d/1h just happen to stay under
  float16's ~65504 ceiling, so this investigation's overflow trigger never fired for them; the
  underlying implausibility (1h's 30,077 bars ≈ 12.5 years of continuous same-regime) is
  identical in kind.
- **Raw correlation with the target is negligible** (-0.0008 at 15m, -0.0018 at 1h, both Pearson
  vs `return_fast`).
- **Confirmed via actual `LGBMRegressor.feature_importances_` on the real, already-fitted 1h
  walk-forward models** (not inferred from correlation alone, since a tree can exploit
  interaction structure a pairwise correlation wouldn't show): `hmm_duration` ranked 89-233 out
  of 248 features across all 5 folds, importance 0-3 vs `ctf_momentum`'s 400+. **It was never a
  meaningful driver -- the published T5 1h/15m results are not an artifact of this bug.**

**Fix applied:** moved `hmm_duration` from the float16-scoped `FLOAT16_UNSAFE_COLS` into the
universal `EXCLUDE_COLS` in `_t5_nonlinear_combiner_shared.py` -- it's excluded from every T5 tf
now, not just 5m, since it's confirmed broken everywhere and carries no real signal at any of
them. This is a methodology cleanup, not a result change (re-verified the 1h feature set drops
from 248 to 247 columns; nothing else shifts).

**Still open, unaffected by the above:** the actual root cause in whatever computes/writes
`hmm_duration` (likely `regime_writer.py`, given todo 207 already established it's the sole
authoritative writer post-2026-07-30) -- this fix only stops T5 from training on a known-broken
column, it does not fix the column itself for any other live consumer.
