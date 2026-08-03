---
status: completed
priority: P3
filed: 2026-08-03
closed: 2026-08-03
source: nonlinear_interaction_combiner-at-5m float16 downcast overflow investigation
---

## What

Diagnosing a `RuntimeWarning: overflow encountered in cast` while trying to run nonlinear_interaction_combiner's non-linear
combiner replication at 5m with `feature_dtype=np.float16` (a memory necessity at that row
count, see `docs/research/data-edge-source-thesis.md`'s nonlinear_interaction_combiner section), a full-corpus scan
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
(`scripts/analysis/_nonlinear_interaction_combiner_shared.py`) now treats these two cases differently
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

## nonlinear_interaction_combiner-training-integrity check (2026-08-03, same session) -- closes the concern for nonlinear_interaction_combiner specifically

Raised because `hmm_duration` was NOT in `_nonlinear_interaction_combiner_shared.py`'s universal
`EXCLUDE_COLS` -- only excluded from the float16-scoped 5m fetch, meaning the already-completed
1h/15m nonlinear_interaction_combiner runs (this session's headline "substantial at 1h/15m" finding) trained on it. Checked
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
  meaningful driver -- the published nonlinear_interaction_combiner 1h/15m results are not an artifact of this bug.**

**Fix applied:** moved `hmm_duration` from the float16-scoped `FLOAT16_UNSAFE_COLS` into the
universal `EXCLUDE_COLS` in `_nonlinear_interaction_combiner_shared.py` -- it's excluded from every nonlinear_interaction_combiner tf
now, not just 5m, since it's confirmed broken everywhere and carries no real signal at any of
them. This is a methodology cleanup, not a result change (re-verified the 1h feature set drops
from 248 to 247 columns; nothing else shifts).

**Still open, unaffected by the above:** the actual root cause in whatever computes/writes
`hmm_duration` (likely `regime_writer.py`, given todo 207 already established it's the sole
authoritative writer post-2026-07-30) -- this fix only stops nonlinear_interaction_combiner from training on a known-broken
column, it does not fix the column itself for any other live consumer.

## Root cause found and fixed at the data layer (2026-08-03, `superpowers:systematic-debugging`)

Traced to source rather than left as "likely regime_writer.py": read `regime_writer.py`'s actual
`duration` computation (`_compute_symbol_tf`, lines ~700-709) -- it's a correct, per-(symbol, tf)
reset-on-state-change counter, computed fresh from `smoothed_states` every run, with no
cross-symbol or cross-run state leakage. **Not the source.** Traced further: `regime` was NULL
for 100% of the specific rows carrying implausible `hmm_duration` values (e.g. DBA/5m:
`hmm_duration`=367,391 on a symbol with only 367,208 total rows -- mathematically impossible
under "duration counts consecutive same-state bars within this symbol's own history"). Checked
corpus-wide: **airtight, zero exceptions** -- every single extreme value, at every tf, occurs
exclusively on rows where `regime IS NULL`; every row where `regime IS NOT NULL` has a sane
`hmm_duration` (max 345-2284 bars across all 4 tfs).

This pointed at the pre-todo-207 K3 `FeatureCache` path instead of regime_writer.py. Read the
actual deleted code via `git show f4912816^:src/intelligence/feature_cache.py`:
`advance_bar()` did `self.hmm_duration += 1.0` unconditionally on every bar; the only reset
(`refresh_regime()`) fired exclusively when a separate, periodic K3 forward-pass model's own
label happened to change since the prior check. For any symbol where that K3 model's label
rarely or never changed (a real risk -- todo 207 already documented K3 as "fixed-params,
forward-filter only, never validated by BIC," a cost-driven approximation, not a fitted model),
the counter simply never reset, accumulating "bars processed since cache start" instead of a
meaningful regime duration. Todo 207 (2026-07-30) deleted this entire path outright
(`_hmm_forward_2d`/`_hmm_entropy` removed, `advance_bar()`'s increment removed,
`FeatureFactory.compute()` now writes all 3 fields as `None` unconditionally) -- **the generator
of new bad values has been dead code since 2026-07-30.** What remained was ~10M already-written
stale rows from before that fix, on cells `regime_writer.py`'s K5-authoritative fit had never
successfully labeled (degenerate model / insufficient obs -- so nothing had ever overwritten the
old K3 garbage there).

Also checked whether `hmm_regime_prob`/`hmm_entropy` (written by the identical dead K3 path, same
atomic tuple) share the contamination: **yes, silently** -- both are non-NULL on 100% of rows
regardless of `regime`, meaning wherever `regime IS NULL` they also still carry stale K3-era
values. These didn't surface via an implausibility check the way `hmm_duration` did, since a
probability/entropy value has no natural "too large" signature -- arguably a worse case of
"silent wrong answer" than the one that got noticed.

**Fix applied:** `scripts/ops/corpus/ops_stale_k3_hmm_fields_cleanup.py` (dry-run by default,
`--apply` required, same safety convention as `ops_known_corrupt_print_cleanup.py`) -- nulls
`hmm_duration`/`hmm_regime_prob`/`hmm_entropy` specifically where `regime IS NULL`, batched per
(symbol, tf) pair with an `integrity_monitor` audit record per pair. Per this project's
Renaissance data-retention discipline: no row deleted, `regime` and every other column
untouched, only the 3 confirmed-stale fields nulled. **Applied and verified live:** 10,062,758
rows cleaned across 77 (symbol, tf) pairs; post-apply query confirms zero non-NULL values remain
on any `regime IS NULL` row across all 4 tfs, and every `regime IS NOT NULL` row is untouched
(same 345-2284 max `hmm_duration` as before). Audit trail sums to exactly 10,062,758, matching
the applied count. Full unit suite green before and after.

`_nonlinear_interaction_combiner_shared.py`'s `EXCLUDE_COLS` comment updated to reflect the column is now
data-clean, not still broken -- `hmm_duration` stays excluded from nonlinear_interaction_combiner training as a deliberate,
conservative choice (never a meaningful driver of already-published results, re-including it now
would require re-running every number for no demonstrated benefit), not because the data is bad
anymore.

**Split into two todos going forward:** this todo (`hmm_duration`/`hmm_regime_prob`/
`hmm_entropy`, the airtight, fully-root-caused half) is CLOSED. The `weekly_r1_dist_atr`/
`weekly_r2_dist_atr` ATR-floor half turned out to be a much bigger, shared-helper design question
(affects 15+ ATR-normalized distance columns, not just these two) that deserves its own scoping
rather than a rushed patch -- filed as [237](../pending/237-atr-distance-features-no-floor-guard-shared-helper.md).
