# 337 - `concept_gate` counter-advance writes have no optimistic lock; active-side advance now does one write+log per active concept per corpus run

**Filed:** 2026-08-20
**Source:** `/code-review high` pass on commit `d7d2a6951` (todo 323, active->shadow_only demotion
hysteresis), findings 3 and 4. Findings 1/2 (missing APR `min_value`/`max_value` bounds and
`ON CONFLICT DO NOTHING` on migration 321's new key, vs. its own stated analog migration 209)
were fixed directly in the same session, migration hadn't been applied to the live DB yet.

## Finding 3 - no optimistic lock on counter-advance UPDATEs

`_ADVANCE_ACTIVE_COUNTERS_SYNC_SQL` and its pre-existing sibling `_ADVANCE_SHADOW_COUNTERS_SYNC_SQL`
(`src/intelligence/concept_registry_service.py:351-373`) both filter only on
`r.domain = %s AND r.name = %s` — no `AND status = %s` optimistic lock, unlike
`record_transition_sync`'s `_CAS_TRANSITION_SYNC_SQL`, which does carry one and documents why
(`concept_registry_service.py:706-712`: "a rerun against an already-transitioned concept is a safe
no-op, never a duplicate transition or orphan log row").

If a concurrent writer (a second in-flight corpus run, or `ops_concept_registry_override.py`) flips
a concept's status between `_apply_feature_transitions`'s in-memory status read
(`concept_svc.get_all_concepts()`) and the `advance_active_counters_sync`/`advance_shadow_counters_sync`
call, the counter still gets mutated on a `concept_gate` row whose live status no longer matches
what triggered the call — corrupting whichever streak the concept is actually accumulating next.

**Not a new bug from todo 323** — `advance_shadow_counters_sync` has had this same gap since it was
introduced (Phase 143 Plan 02/143.1). Todo 323's `advance_active_counters_sync` mirrors it exactly,
as intended ("mirrors the existing... shape exactly" — its own commit message). The project's
primary defense is architectural, not per-statement: "ProcessPoolExecutor workers are compute-only
... All DB writes go through a single serial connection in main" (CLAUDE.md invariant) — `ic_engine.py`
is the only writer expected to touch `concept_gate` during a corpus run. The residual risk is a
genuinely concurrent *second* corpus run or an operator override script racing the same row, which
is possible but not the documented common case.

**Fix, if pursued:** add `AND status = %s` (the status the caller believes the concept is currently
in) to both `_ADVANCE_SHADOW_COUNTERS_SYNC_SQL` and `_ADVANCE_ACTIVE_COUNTERS_SYNC_SQL`, check
rowcount, and treat 0 rows as a safe no-op (log + skip) the same way `record_transition_sync` does.
Fix both together — fixing only the active side (todo 323's new code) while leaving the shadow side
unlocked would be an inconsistent half-fix of the same pattern.

## Finding 4 - per-run write/log volume increased from shadow_only-only to every active concept

`ic_engine.py`'s `_apply_feature_transitions` (`services/ic_engine.py:4354`) now calls
`advance_active_counters_sync` once per **active** concept every corpus run (not just concepts
about to be demoted) — each call does its own `conn.transaction()` single-row UPDATE commit plus an
INFO log line (`concept_registry_service.py:900-915`). `active` is the majority/terminal status
(concept_registry's `feature` domain row count tracks `FeatureVector`'s field count 1:1, currently
in the low hundreds), where previously only `shadow_only` concepts (a small minority) incurred this
cost via `advance_shadow_counters_sync`.

In absolute terms this is small — on the order of a couple hundred sequential single-row commits
and log lines, inside a corpus run that itself runs for a day or more (`ic_engine.py`'s own IC
bootstrap work dominates by orders of magnitude) — not the "log per-row inside a loop over millions
of corpus rows" pattern CLAUDE.md's own guidance targets. But it's still real overhead in the
direction CLAUDE.md flags: this codebase's established pattern for exactly this shape (many-row,
same-table column update) is `bulk_update_by_key`, which this code doesn't use.

**Fix, if pursued:** collect `(feature_name, passed)` pairs across the per-feature loop instead of
calling `advance_active_counters_sync` inline per feature, then issue one batched UPDATE (via
`bulk_update_by_key` or a `CASE ... WHEN` VALUES-list UPDATE) after the loop, same shape as
`is_demotion_eligible`'s per-concept checks already read from the in-memory cache rather than the
DB. Not urgent — no measured latency impact reported, corpus-run wall clock is dominated elsewhere.

## Priority

Not filed against PRIORITIES.md yet — low urgency, no correctness impact observed live, both
findings are pre-existing-pattern-adjacent rather than novel regressions. Triage into P2/P3 at next
PRIORITIES.md pass.
