---
status: pending
priority: P0
filed: 2026-07-29
source: shortlist bootstrap-CI recheck of todo 146's horizon-response diagnostic
  (scripts/ops/alpha/ops_lookahead_horizon_response.py --bootstrap), this session
---

# `canary_noise_gaussian`/`canary_noise_uniform`/`canary_near_constant` are seeded by
# `(bar_ts, canary_rng_seed)` only -- identical across every symbol at a given
# timestamp -- silently defeating their purpose as cross-sectional negative controls,
# and exposing a broader bug class: any market-wide/broadcast feature pooled
# cross-sectionally has an unreliable significance test under BOTH Fisher-z and the
# per-symbol circular block bootstrap CI

## Problem

`src/intelligence/feature_factory.py`'s `_canary_sub_seed(bar_ts, base_seed, offset)`
(~line 1780) derives its RNG seed from `bar_ts` and the global `alpha.ic.canary_rng_seed`
APR key ONLY -- no `symbol` component. `_canary_noise_gaussian`/`_canary_noise_uniform`/
`_canary_near_constant` (lines 1791-1811) all route through it. Confirmed live against
`feature_vectors`: every symbol has bit-identical `canary_noise_gaussian`/
`canary_noise_uniform`/`canary_near_constant` values at the same `bar_ts`, corpus-wide
(query in this todo's References). `canary_constant` is a fixed literal (unaffected,
correctly degenerate). `canary_acausal_placebo` uses `closes[]`/`i` directly, not this
seed path (also unaffected, and correctly SHOULD fire ~always -- it's a positive control).

These 3 canaries exist specifically to catch calibration problems in cross-sectional IC
measurement (`feature_registry` docs them as `status='candidate'`, never promoted,
`group_name='control'`). Because they're duplicated identically across every pooled
symbol at a timestamp, their true independent draw count per bar_ts is 1, not
n_symbols -- severe pseudo-replication.

**Correction (2026-07-29):** the original filing's claim that this control was "not
wired into any live check" was wrong -- it only checked `ic_engine.py`/
`ensemble_ic_engine.py` directly. `scripts/ops/alpha/ops_canary_integrity_assert.py`
(todo 068, Phase 143.1-02) already exists, is wired into
`ops_corpus_pipeline_run.sh` immediately after the ic_engine step, and IS already
firing today -- though for a different, independently-diagnosed reason
(`canary_acausal_placebo` not clearing its POOLED gate, split out to todo 204, NOT
caused by this todo's seeding bug). This todo's Fix item 2 ("wire canaries into a
live check") is therefore already satisfied by existing infrastructure and is
REMOVED below -- nothing new needs to be built there.

**Empirical confirmation this session:** ran `ops_lookahead_horizon_response.py`'s new
`--bootstrap` per-feature recheck (circular block bootstrap CI, the same method
`ic_engine.py`'s real promotion gate uses) on tf=1h, `--allow-overnight`, 8 horizons.
Canary raw-CI-excludes-zero rate stayed ~35-40% under the CORRECTED bootstrap CI --
essentially unchanged from the already-known ~38% Fisher-z SUSPECT rate
(`ops_ic_null_calibration.py`, referenced in `ic_math.py`'s docstring) that motivated
switching production to the bootstrap CI in the first place. Switching CI methods did
NOT fix it, because the bootstrap's per-symbol block resampling only corrects for
WITHIN-symbol serial dependence -- it has no mechanism to detect or correct a value that
is duplicated ACROSS symbols at a fixed timestamp.

**Broader bug class, same root cause:** `vix_z` and `yield_slope_z` (2 of the 6
shortlisted candidate-signal features from this session's horizon-response follow-up)
are ALSO confirmed bit-identical across every symbol at a given `bar_ts` (they're
legitimately macro/single-series features, correctly broadcast -- that part is not a
bug). But that means their cross-sectional significance test has the EXACT SAME
pseudo-replication exposure as the broken canaries: a per-symbol block bootstrap (or
Fisher-z) run on the pooled (symbol, bar_ts) sample overstates their effective N by
~n_symbols, so a "CI excludes zero" result for either of these two features, from any
diagnostic or production measurement that pools symbols without special-casing
broadcast features, cannot currently be trusted at face value -- even though the
underlying VIX/yield-curve-vs-return relationship is economically plausible, unlike
the canaries. The other 4 shortlisted features (`range_pct_slow`, `garch_ratio`,
`hmm_regime_prob`, `hmm_entropy`) are confirmed genuinely per-symbol/idiosyncratic
(varies by symbol at the same `bar_ts`) -- the per-symbol block bootstrap IS the
statistically correct tool for those, no exposure.

## Fix

1. **Canary seeding -- DONE 2026-07-29** (`docs/superpowers/plans/2026-07-29-canary-seed-and-broadcast-feature-audit.md`
   Task 1): `symbol` added into `_canary_sub_seed`'s hash input, mirroring
   `ic_engine.py`'s own `_derive_worker_rng_seed(cell_key, bootstrap_seed)` pattern.
   No historical backfill triggered -- these 3 columns have zero live consumers today
   (`status='candidate'`, only read via `feature_ic_scores`, which is already gated
   on todo 202's rebuild for an unrelated reason); the next scheduled corpus rebuild
   produces correct values with no dedicated backfill needed.

2. ~~Wire canaries into a live check~~ -- REMOVED, already existed
   (`ops_canary_integrity_assert.py`, todo 068) before this todo was filed; the
   original claim otherwise was a research error, corrected above.

3. **Broadcast-feature significance testing -- AUDITED, not yet fixed** (same plan,
   Task 2): `scripts/ops/alpha/ops_broadcast_feature_audit.py` empirically classifies
   which of the 244 active features are symbol-invariant (broadcast) vs idiosyncratic,
   confirming `vix_z`/`yield_slope_z`/`flight_quality` (group='macro') plus every
   session/calendar-derived feature share this exposure. Building the actual
   broadcast-aware significance test (collapse to one row per bar_ts before
   bootstrapping, or a dedicated time-series-only test for that feature subset) is a
   real methodology decision, not mechanical implementation -- remains open, to be
   scoped as its own todo once someone is ready to design it, not bundled here.

## References

- `src/intelligence/feature_factory.py:1780-1811` (`_canary_sub_seed` and the 3 broken canaries)
- `services/ic_engine.py`, `services/ensemble_ic_engine.py` -- zero "canary" references, confirmed via grep
- Verification query: `SELECT bar_ts, symbol, canary_noise_gaussian, canary_noise_uniform, canary_near_constant FROM feature_vectors WHERE tf='1h' AND bar_ts = <any timestamp> ORDER BY symbol` -- bit-identical values across symbols
- `scripts/ops/alpha/ops_lookahead_horizon_response.py`'s new `--features`/`--bootstrap` flags (this session) -- the shortlist recheck that surfaced this
- `src/intelligence/statistics/ic_math.py`'s `_circular_block_bootstrap_ic`/`ops_ic_null_calibration.py` -- the already-known ~38% Fisher-z SUSPECT rate this todo's finding is NOT explained by (bootstrap CI shows the same elevated rate, isolating the real cause to seeding, not CI method choice)
