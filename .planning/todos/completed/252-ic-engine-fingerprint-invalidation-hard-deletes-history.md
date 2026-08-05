---
status: fixed
priority: P0
filed: 2026-08-04
fixed: 2026-08-04
source: user question -- "after we make changes, can we look back and ask what the edge was
  last month" -- while scoping todo 251's edge-summary view. Traced ic_engine.py's fingerprint
  mechanism to answer it precisely; found an active data-loss path, not just a missing feature.
---

# `ic_engine.py`'s fingerprint invalidation hard-deletes `feature_ic_scores` rows on any code/APR change -- no archive, prior measurement is unrecoverable

## What

`feature_ic_scores` only preserves history along one axis: `training_window_end` advancing
because new market data arrived (confirmed while scoping todo 251). It does NOT preserve
history across a code or config change evaluated against the *same* historical window --
which is worse than "no history," because the prior measurement is actively deleted, not
just left unindexed.

Mechanism (`services/ic_engine.py`): `ic_cell_fingerprints` tracks `code_content_key` +
`apr_snapshot_key` + `upstream_watermark` per (symbol, tf, pass_type, training_window_end)
cell. `_classify_fingerprint()` returns `"invalid"` when any of those three components
changed since the cell was last computed (i.e. any feature-logic code change, or any APR
parameter change relevant to that cell). An invalid cell's response is:

```sql
DELETE FROM feature_ic_scores
WHERE symbol = %(symbol)s AND tf = %(tf)s AND regime_scope = %(pass_type)s
  AND training_window_end = %(training_window_end)s
```

(and the cross-sectional variant, same shape, additionally scoped by `regime`) -- a hard
delete, no archive, executed before the cell is recomputed and reinserted at the same key.
The moment a bug fix or APR retune is rerun against an already-computed `training_window_end`,
the pre-change row is gone. There is no snapshot of "what did this feature's IC look like
before we made this change" anywhere in the schema once that delete fires.

## Why this matters now

Not yet triggered for real -- the corpus currently has exactly one `training_window_end`
with a single `computed_at` batch (2026-07-30), meaning every cell so far has hit the
`stored is None` / first-ever-compute path, not a real invalidate-and-delete. But this
project runs on a cadence of frequent code fixes and APR retuning followed by reruns against
already-computed windows (todos 208/210/211/216/229 etc. are exactly this pattern) -- the
next such rerun against an existing `training_window_end` will exercise this path for real,
and whatever was there before is permanently gone. Violates two of this project's own stated
principles directly: "never drop data that could contain signal," and the Concept Registry
doc's own framing that evidence "should be in the database... not in someone's memory."

## What needs to happen (design decision, not mine to make unilaterally)

Two candidate fixes, real tradeoff between them:

1. **Archive-before-delete.** Copy the rows `_FINGERPRINT_INVALIDATE_DELETE_SQL` is about to
   remove into a `feature_ic_scores_history` table (or add a `superseded_at` column and turn
   the hard DELETE into a soft supersede) immediately before the delete executes. Smallest
   schema change; keeps `feature_ic_scores`' current PK/query shape untouched for every
   existing consumer.
2. **Fold the fingerprint into row identity.** Extend `feature_ic_scores`' key to include
   `code_content_key`/`apr_snapshot_key` (or a hash), so a methodology change produces new
   rows alongside old ones instead of overwriting in place -- makes the table a genuine
   append-only ledger, closer to how `concept_transition_log` already works, but touches
   every existing reader (ic_engine's own idempotency checks, ensemble_trainer, all the
   `ops_*` analysis scripts that query `feature_ic_scores` directly).

Recommend (1) as the smaller, lower-risk fix unless there's a reason the fingerprint itself
needs to be a first-class query dimension (e.g., "show me every version of this feature's IC
across every methodology change," not just "show me the one right before this one").

**Whichever fix lands, reuse `ic_cell_fingerprints`' existing (code_content_key,
apr_snapshot_key, upstream_watermark) tuple as the provenance/version key for the archived
rows -- don't invent a second, parallel "what changed" convention alongside the one that
already exists and is already well-engineered.** This is also the natural shared key for todo
118's `concept_transition_log` fold-in: a feature's measurement history (this todo) and its
governance transition history (118) should be traceable through the same fingerprint identity,
not two independently-versioned schemes that happen to describe the same underlying event.

## Fix -- DONE 2026-08-04: archive-before-delete (option 1)

Migration 285 (`production/migrations/285_feature_ic_scores_history_archive.sql`, applied):
`feature_ic_scores_history` -- append-only archive, mirrors `feature_ic_scores`' 40 columns
exactly plus `archived_at` and the `ic_cell_fingerprints` provenance tuple
(`archived_code_content_key`/`archived_apr_snapshot_key`/`archived_upstream_watermark`, per this
file's own recommendation to reuse the existing convention rather than inventing a second one).
No FK to `feature_ic_scores` (same precedent as `alpha_frames`/`construction_spreads`). No
unique constraint -- genuinely append-only, multiple invalidate-recompute cycles for the same
cell each add a new snapshot.

`services/ic_engine.py`: both DELETE call sites (per-symbol batch loop, cross-sectional per-cell
loop) now run a new `_ARCHIVE_BEFORE_DELETE_SQL`/`_ARCHIVE_BEFORE_DELETE_CROSS_SECTIONAL_SQL`
INSERT immediately before the existing DELETE, in the same transaction/cursor -- archive and
delete are atomic (a crash between the two can only leave the pre-delete row still live, never a
silently-lost row with nothing archived). The archive query LEFT JOINs `ic_cell_fingerprints` to
capture the OLD fingerprint (about to be overwritten by the same run's post-compute UPSERT)
before it's gone.

**Real correctness subtlety found and handled**: `feature_ic_scores.symbol` and
`ic_cell_fingerprints.symbol` use DIFFERENT conventions for cross-sectional cells --
`feature_ic_scores.symbol` is always the `'POOLED'` sentinel there, while
`ic_cell_fingerprints.symbol` is the real per-cell key `f"{group_name}:{regime_label}"`
(`cs_symbol_key`). A naive same-column JOIN would have silently produced NULL fingerprint
provenance for every cross-sectional archived row. Fixed by binding `fp.symbol` to its own
`%(fp_symbol)s` parameter, distinct from `%(symbol)s` -- the per-symbol call site passes the
same value for both (real instrument symbol matches on both tables there), the cross-sectional
call site passes `cs_symbol_key` for `fp_symbol` and `_CROSS_SECTIONAL_SYMBOL` for `symbol`.

Verified end-to-end against the live schema before writing tests: ran both the per-symbol and
cross-sectional archive+delete sequences with synthetic rows inside a rolled-back transaction,
confirmed the archived row lands with the correct fingerprint attached and the live table
correctly empties -- for both paths, including the cross-sectional `fp_symbol` case. 5 new unit
tests (`tests/unit/test_ic_engine_fingerprint.py`, matching this file's existing DB-free
structural-SQL-shape convention). Full `tests/unit/` suite green, ruff/black clean.

## References

- `services/ic_engine.py`: `_classify_fingerprint`, `_fingerprint_is_computationally_valid`,
  `_FINGERPRINT_INVALIDATE_DELETE_SQL`, `_FINGERPRINT_INVALIDATE_DELETE_CROSS_SECTIONAL_SQL`
- Related but distinct: [250](250-feature-ic-scores-not-a-hypertable-no-retention.md) (no
  hypertable/compression -- an unbounded-growth risk, the opposite failure mode from this
  todo's unwanted-shrinkage risk), [251](251-feature-edge-summary-view.md) (the summary view
  this todo's fix would make trustworthy for cross-change comparisons)
