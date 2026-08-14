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
