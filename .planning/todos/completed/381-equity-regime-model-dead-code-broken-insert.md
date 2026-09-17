---
status: completed
priority: P3
filed: 2026-09-17
closed: 2026-09-17
source: found while scoping todo 379 (Codex + AGY both independently flagged
  equity_regime_model.py as non-live during blast-radius verification)
---

# `equity_regime_model.py` is dead code -- INSERT references a column that no longer exists -- CLOSED (deleted)

## Resolution (2026-09-17)

Deleted `services/equity_regime_model.py` (option 1). Correction to this todo's original
"no test file" claim below: there WAS a test file
(`tests/unit/services/test_equity_regime_model_causal.py`), missed by only grepping
`tests/unit/` top-level and not its `services/` subdirectory. Checked before deleting:
its causal-rank invariant is already covered, more rigorously (independent scipy-oracle
comparison, NaN/tie/scaling coverage), by `tests/unit/test_regime_signals_causal_rank.py`
against the LIVE ported implementation in `causal_rank.py` -- the dead-code test was
exercising a copy nothing calls, not the live code path. Its `_tf_window` coverage is
separately, fully mirrored in `tests/unit/test_regime_signals_breadth_vol.py` against the
live `tf_window.py`. Confirmed zero coverage loss; deleted the redundant test alongside
the module.

Also independently confirmed by two pre-existing CI allow-lists
(`tests/unit/test_no_bare_process_pool_executor.py`, `tests/unit/test_market_data_ohlcv_boundary.py`)
that already carried permanent, deliberate entries documenting this file as dead code --
both entries removed (would otherwise fail as stale references to a deleted file).
Updated all other references (`ensemble_ic_engine.py`'s startup-gate error message,
`ops_ensemble_ic_diagnosis.py`'s diagnostic flag text, `ops_corpus_pipeline_run.sh`'s
pipeline-step comments, and provenance comments in `cross_sectional_regime_model.py`/
`breadth_vol.py`/`tf_window.py`) to point at the live `cross_sectional_regime_model.py`
instead of the deleted file. Full unit suite green after the change.

## Original filing (kept for record)

# `equity_regime_model.py` is dead code -- INSERT references a column that no longer exists

## What

`services/equity_regime_model.py` was deprecated in Phase 144 (`144-04-SUMMARY.md`:
"retained as the emergency single-group rollback path, zero functional changes") and
replaced in the corpus pipeline's step-4 slot by `cross_sectional_regime_model.py`
(`scripts/ops/corpus/ops_corpus_pipeline_run.sh:363`, confirmed via `git log` on both
files -- no systemd unit or cron entry invokes `equity_regime_model.py` anywhere).

Verified live (2026-09-17): it is not just unused, it is broken. Its write path is:

```sql
INSERT INTO market_regimes (asset_class, tf, ts, regime_label, regime_prob_vector)
VALUES ('equity', %(tf)s, %(ts)s, %(regime_label)s, %(regime_prob_vector)s::jsonb)
ON CONFLICT (asset_class, tf, ts) DO UPDATE SET ...
```

The live `market_regimes` schema (checked via `\d market_regimes`) has no `asset_class`
column at all -- only `regime_group, tf, ts, regime_label, regime_prob_vector` (Phase 144
generalized the single hardcoded 'equity' asset class into `regime_group`). Running this
script today would hard-crash with a Postgres "column asset_class does not exist" error
before writing a single row. The "emergency rollback path" framing from Phase 144 is no
longer true -- there is nothing to roll back to.

## Recommended next step

Decide, deliberately (this is a 5-minute call, not a design question):
1. **Delete it.** It has zero live callers, zero systemd/cron references, and its own
   write path is broken against the current schema -- there is no rollback capability to
   preserve. Simplest, matches CLAUDE.md's "ruthlessly eliminate complexity."
2. **Fix and keep it as a real rollback path.** Update the INSERT to the current
   `regime_group` schema, and its `_compute_breadth_fraction`'s tag query was already given
   the todo-379 `source='human'` fix (defense-in-depth) even though this decision was still
   open -- if kept, verify the rest of the file still functions against current schema/APR
   keys before trusting it as an actual rollback option.

Either way, `tests/unit/` has no test file for this module (confirmed empty search) --
consistent with option 1 being the lower-maintenance choice.

## Cross-refs

- Todo 379 (completed) -- where this was found during blast-radius verification.
- `.planning/milestones/v3.1-phases/144-cross-sectional-regime-model-regime-group/144-04-SUMMARY.md`
  -- the original Phase 144 deprecation decision this todo revisits.
