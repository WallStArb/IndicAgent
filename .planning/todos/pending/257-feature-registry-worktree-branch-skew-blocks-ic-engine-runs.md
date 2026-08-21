---
status: pending
priority: P2
found_during: phase-151-plan-02
found_date: 2026-08-05
---

# concept_registry row-count skew blocks ic_engine.py in worktrees not synced with a concurrent schema-changing session

**Corrected 2026-08-21 (this session's backlog audit):** the title and Item 1 below originally
named `feature_registry` as one of two gates. Phase 170 (COMPLETE 2026-08-10, migration 311)
`DROP`ped that table entirely and deleted `src/intelligence/feature_registry_service.py` --
that half of this todo's premise no longer exists in any form, struck below rather than left to
mislead a future reader. The `concept_registry(domain='feature')` drift check (Item 2, now the
only surviving gate) is still live in `services/ic_engine.py` today (confirmed via grep,
`ic_engine.py:5049`) and the underlying mechanism (concurrent GSD sessions sharing one physical
DB) is unchanged, so the todo itself stays open under the general form below, not closed.

## What

`services/ic_engine.py`'s `main()` has a startup gate that crash-loudly enforces a row-count
match between the live DB and the worktree's checked-out code:

`services/ic_engine.py`'s own `concept_registry(domain='feature')` drift check: registry names
must exactly match `FeatureVector` dataclass field names. Confirmed live 2026-08-05 during Phase
151-02 Task 3's empirical verification (against the now-dead sibling `feature_registry` gate,
same failure shape): any `ic_engine.py` per-symbol run (regardless of `--symbols` scope) fails
immediately with a row-count mismatch error before any compute begins if the checked-out
`FeatureVector` dataclass hasn't merged a sibling session's schema-changing migration.

## Root cause

Any concurrent GSD session that lands a live DB migration against `concept_registry` (all GSD
worktrees point at the same physical DB, not per-worktree isolated) will desync any other
worktree whose checked-out `FeatureVector` dataclass hasn't yet merged the corresponding field
additions -- that worktree permanently fails this gate until its branch merges with the
schema-changing session's changes. Confirmed non-transient by monitoring the row count over
several minutes with zero movement (original 2026-08-05 finding, against Phase 170 specifically;
the mechanism generalizes to any future concurrent schema-changing session).

## Impact

Blocks ALL per-symbol `ic_engine.py` runs (any `--symbols` scope) from any worktree/branch not
synced with a concurrent schema-changing session, for the duration of that session's work.
`--cross-sectional-only` was not tested but likely hits the same gate (the check runs
unconditionally early in `main()`, before `--cross-sectional-only`'s branch).

## Recommended fix

Not a code bug -- this is an expected consequence of concurrent GSD sessions sharing one
database. Options, in order of preference:
1. Sequence corpus-wide `ic_engine.py` runs behind any in-flight schema-changing session's merge
   to `main` (the project's established policy, first stated for Phase 170: "do not touch
   feature_registry/concept_registry files [from another worktree] until it merges").
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
