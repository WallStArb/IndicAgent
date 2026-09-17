---
status: pending
priority: P3
filed: 2026-09-17
source: found while scoping todo 379 (Codex + AGY both independently flagged
  equity_regime_model.py as non-live during blast-radius verification)
---

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
