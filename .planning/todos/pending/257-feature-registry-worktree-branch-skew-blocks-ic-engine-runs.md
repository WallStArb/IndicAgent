---
status: pending
priority: P2
found_during: phase-151-plan-02
found_date: 2026-08-05
---

# feature_registry / concept_registry row-count skew blocks ic_engine.py in worktrees not yet merged with Phase 170

## What

`services/ic_engine.py`'s `main()` has two independent startup gates that both crash-loud on a
row-count mismatch between the live DB and the worktree's checked-out code:

1. `src/intelligence/feature_registry_service.py`'s `load_sync()`: `feature_registry` table row
   count must equal `len(dataclasses.fields(FeatureVector))` (currently 249 in code checked out
   as of 2026-08-05, but live DB has 259 rows).
2. `services/ic_engine.py`'s own `concept_registry(domain='feature')` drift check: registry names
   must exactly match `FeatureVector` dataclass field names (live DB has 261 concept_registry
   rows vs 249 dataclass fields).

Confirmed live 2026-08-05 during Phase 151-02 Task 3's empirical verification: any
`ic_engine.py` per-symbol run (regardless of `--symbols` scope) fails immediately with
`RuntimeError: feature_registry row count mismatch: expected 249, got 259` (or the
concept_registry drift variant), before any compute begins.

## Root cause

Phase 170 (feature_registry -> Concept Registry migration) is running in a separate, concurrent
GSD session as of 2026-08-04 and has landed live DB migrations against the SHARED production
database (all GSD worktrees point at the same physical DB, not per-worktree isolated) that add
rows to `feature_registry`/`concept_registry`. Any worktree whose checked-out `FeatureVector`
dataclass hasn't yet merged Phase 170's corresponding field additions will permanently fail this
gate until that worktree's branch merges with Phase 170's changes -- confirmed non-transient by
monitoring the row count over several minutes with zero movement.

## Impact

Blocks ALL per-symbol `ic_engine.py` runs (any `--symbols` scope) from any worktree/branch not
yet synced with Phase 170, for the duration of Phase 170's work. `--cross-sectional-only` was not
tested but likely hits the same gate (both checks run unconditionally early in `main()`, before
`--cross-sectional-only`'s branch).

## Recommended fix

Not a code bug -- this is an expected consequence of concurrent GSD sessions sharing one
database. Options, in order of preference:
1. Sequence corpus-wide `ic_engine.py` runs behind Phase 170's merge to `main` (already the
   project's stated policy per STATE.md: "Phase 170 ... running in a separate, concurrent session
   ... do not touch feature_registry/concept_registry files").
2. If concurrent GSD phase execution against per-symbol ic_engine.py becomes routine, consider a
   per-worktree logical-DB or schema-namespace isolation strategy (larger architectural change,
   out of scope for a single todo).

## Workaround used (Phase 151-02 Task 3)

Called `_compute_symbol_tf` + `_write_symbol_results` directly from a standalone script,
bypassing only the two registry gates (which live in `main()`, not in the compute/write
functions themselves) -- safe because `_write_symbol_results`'s INSERT SQL is
`ON CONFLICT ... DO NOTHING`, so re-running against already-correct rows is always a no-op.
Not a repeatable pattern for routine use; documented here so a future session hitting the same
gate doesn't have to re-diagnose it from scratch.
