# 313 - Audit remaining bulk_update_by_key/raw-UPDATE callers for col_types type drift

**Filed:** 2026-08-14
**Source:** Fixing todo 312 (regime_writer HMM probability underflow). Root cause was
`col_types` metadata drift: migrations 201/312 narrowed columns from `double precision` to
`real`, but `bulk_update_by_key` callers' `col_types` dicts kept declaring `double
precision`, undetected because `col_types` was, until this fix, only used for the temp
table's DDL (a `double precision` temp column silently absorbs any value, and the mismatch
only surfaces at the final implicit-cast UPDATE). Fixed the two callers confirmed stale
(`regime_writer.py`'s `_regime_family_col_types`, `ops_ctf_columns_recompute_15m.py`) and
added a systemic float-range clamp keyed off `col_types` to `bulk_update_by_key` itself, but
only checked all 4 known `bulk_update_by_key` callers, not every raw `UPDATE`/`execute_batch`
call site independently, nor cross-referenced migration 312's full 303-column list against
every writer that touches those columns.
**Status:** pending, P2 -- the systemic clamp fix already protects any caller whose
`col_types` IS correct; this is about finding any caller whose `col_types` is still wrong
(same drift, just not yet triggered by an extreme-enough value to surface as a failure).

## Scope

1. Cross-reference migration 312's full `ALTER COLUMN ... TYPE real` column list (303
   columns) against every writer of each column -- not just `bulk_update_by_key` callers,
   any `UPDATE`/`execute_batch`/`executemany` that sets one of these columns with a
   hand-typed value (Python literal, not from `col_types`).
2. For each writer found, confirm whether it's exposed to the same class of extreme value
   (near-zero from a probability/ratio computation, or unboundedly large from an
   accumulator) -- most of the 303 columns are z-scores/ratios/ATR-distances/trig
   encodings that structurally can't approach float4's boundary, so this is a filtering
   pass, not "fix all 303."
3. `ops_ic_shrinkage.py` checked and confirmed clean (writes to `feature_ic_scores`, whose
   `ic_shrunk`/`shrinkage_weight` were never touched by migration 312) -- don't re-check.

## Where

- `services/_batch_utils.py`'s `_clamp_to_real_range`/`bulk_update_by_key` -- the fix this
  audit extends coverage for
- `production/migrations/312_feature_vectors_float32_drift_fix.sql` -- the column list to
  cross-reference
- `grep -rn "bulk_update_by_key(" --include="*.py" .` -- the 4 known call sites (2 already
  fixed, 2 already confirmed clean); this todo is about finding call sites NOT using
  `bulk_update_by_key` at all

## Closed 2026-08-21: CLEAN, no follow-up fix needed

Cross-referenced migration 312's full 303-column list against every `feature_vectors`
writer outside the 4 known `bulk_update_by_key` call sites.

**`bulk_update_by_key` call sites confirmed unchanged since 2026-08-14 (4 total):**
`regime_writer.py` (2 sites, already fixed) and `ops_ctf_columns_recompute_15m.py`
(already fixed) both touch `feature_vectors`; `ic_engine.py`/`ops_ic_shrinkage.py` both
write `feature_ic_scores`, untouched by migration 312, already confirmed clean, not
re-checked. No new call sites added.

**Every non-`bulk_update_by_key` `feature_vectors` writer found is structurally immune to
this specific bug class, not just currently correct:**
- `backfill_feature_factory.py`'s `_batch_insert` and
  `feature_vector_persistence.py`'s tuple-builder INSERT path -- direct parameterized
  `executemany` INSERT/UPSERT, no temp table involved at all. The silent-drift mechanism
  this bug class depends on (a stale `col_types` dict producing a mismatched temp-table
  DDL that silently absorbs an out-of-range value, which only fails later at an implicit
  CAST) structurally cannot occur without a temp table -- Postgres enforces the real
  `real`-typed column immediately on a direct INSERT; an out-of-range value fails loudly
  at insert time. (`feature_vector_persistence.py` separately guards `math.isfinite()`
  pre-write -- a different, already-loud failure mode, not this one.)
- `ops_stale_k3_hmm_fields_cleanup.py`, `ops_regime_null_out_and_verify.py` -- both
  NULL-only `UPDATE`s (`col = NULL` for every owned column). No value written, no range
  concern possible.
- Every other batch writer checked (`ensemble_trainer.py`, `cross_sectional_spread_tracker.py`,
  `alpha_frame_writer.py`, `forward_return_writer.py`, `feature_vector_writer.py`,
  `ops_interaction_primitives_pilot.py`) writes to its own table
  (`ensemble_alpha`/`construction_spreads`/`alpha_frames`/`forward_returns`/
  `feature_ic_scores`), never `feature_vectors` -- out of migration 312's scope entirely.

No fix needed -- the systemic `col_types`-based clamp in `bulk_update_by_key` already
covers every writer capable of hitting this bug class; nothing was found outside it.
