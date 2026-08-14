# 312 - regime_writer HMM probability underflow against real (float4) columns

**Filed:** 2026-08-14
**Source:** Found live while babysitting todo 306's regime_writer relaunch (the one with the
statement_timeout fix). The `regime` pass is alive and progressing (12 workers, real CPU,
walking through the corpus normally) but is failing to write 54/151 symbols across all 4
timeframes (195 `regime_writer.write_failed` events as of this filing) with:
```
{"error": "value out of range: underflow", "event": "regime_writer.write_failed"}
```
**Status:** pending, P1 -- real, reproducible data-integrity gap affecting a third of the
corpus's `regime` writes on this run; not blocking (the run itself is not crashing, todos
303/304 depend on `regime_volatility` not `regime`), but should be fixed before the NEXT full
`regime` relabel, not left to keep silently dropping ~1/3 of symbols every run.

## Root cause (confirmed, not hypothesized)

`REGIME_WRITER_OWNED_COLUMN_NAMES` (`src/intelligence/features/feature_vector_persistence.py:467`)
includes `hmm_prob_trending_up`, `hmm_prob_ranging`, `hmm_prob_trending_down`, `hmm_regime_prob`,
`hmm_entropy`. Migrations 201 and 312 (`production/migrations/201_feature_vectors_float32.sql`,
`312_feature_vectors_float32_drift_fix.sql`) both narrowed `hmm_entropy`/`hmm_prob_trending_up`/
`hmm_regime_prob` from `double precision` (float8) to `real` (float4) as a disk-space
optimization. `real`'s minimum representable positive magnitude is ~1.18e-38 (or ~1.4e-45 as a
subnormal, depending on the parser's tolerance) -- the HMM's computed probabilities are Python
float64 and can legitimately produce a residual state probability smaller than that for a highly
confident/near-degenerate posterior (e.g. `1e-50`), which is a scientifically meaningless
distinction (indistinguishable from exactly 0 for any downstream use) but which Postgres's
`real` text-format input parser rejects outright rather than rounding to zero.
`bulk_update_by_key`'s COPY-based bulk write (`services/_batch_utils.py`) is what surfaces the
error -- COPY's text format goes through the same strict float4 parser as a literal `SET x = 'val'`.

This is the first time `regime_writer` has written at scale since migrations 201/312 landed
(the run they'd have hit was the one derailed by the disk-full incident/second write-session
bug), so this is the first time the interaction surfaced.

## Fix

Clamp any of the 5 probability/entropy values to `real`'s representable range (or simpler: round
anything with `abs(x) < 1e-30` to `0.0`) in `regime_writer.py`'s write path, before the values
reach `_write_regime_results`/`_bulk_update_by_key`. Cheap, bounded, no schema change needed.
Check whether `_write_regime_volatility_results` (the `regime_volatility` sibling, K=3) writes
the same column family or a different one -- if it shares any of the 5 narrowed columns, it
needs the same clamp before its own pass runs.

## Where

- `services/regime_writer.py:1826` (`_write_regime_results`) -- the write call this error
  originates from
- `src/intelligence/features/feature_vector_persistence.py:467` -- `REGIME_WRITER_OWNED_COLUMN_NAMES`
- `production/migrations/312_feature_vectors_float32_drift_fix.sql`,
  `201_feature_vectors_float32.sql` -- the type narrowing that introduced the range gap
- `logs/regime_writer.log` -- 195 `write_failed` events as of 2026-08-14, `grep underflow` to
  find current affected-symbol count (will grow as the run continues)
