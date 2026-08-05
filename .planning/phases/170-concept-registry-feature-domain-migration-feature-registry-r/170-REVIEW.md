---
phase: 170-concept-registry-feature-domain-migration-feature-registry-r
reviewed: 2026-08-05T01:06:14Z
depth: standard
files_reviewed: 33
files_reviewed_list:
  - production/migrations/283_concept_registry_feature_domain_schema.sql
  - production/migrations/284_concept_registry_feature_domain_seed.sql
  - scripts/analysis/ops_primitive_discovery_report.py
  - scripts/ops/alpha/ops_broadcast_feature_audit.py
  - scripts/ops/alpha/ops_canary_integrity_assert.py
  - scripts/ops/alpha/ops_concept_feature_migration_verify.py
  - scripts/ops/alpha/ops_concept_registry_override.py
  - scripts/ops/alpha/ops_ensemble_ablation.py
  - scripts/ops/alpha/ops_ensemble_weight_compare.py
  - scripts/ops/alpha/ops_ic_shrinkage.py
  - scripts/ops/alpha/ops_interaction_primitives_pilot.py
  - scripts/ops/alpha/ops_lookahead_horizon_response.py
  - scripts/ops/corpus/ops_corpus_pipeline_run.sh
  - services/ensemble_trainer.py
  - services/ic_engine.py
  - src/config/vocabulary_drift.py
  - src/intelligence/concept_registry_service.py
  - src/intelligence/feature_factory.py
  - src/intelligence/schemas.py
  - src/intelligence/statistics/ic_math.py
  - src/observability/metrics.py
  - tests/integration/test_concept_parent_lineage.py
  - tests/integration/test_concept_registry_sync_lifecycle.py
  - tests/integration/test_feature_vectors_schema.py
  - tests/unit/intelligence/test_swing_fib_trend_structure_primitives.py
  - tests/unit/scripts/test_ops_concept_registry_override.py
  - tests/unit/scripts/test_ops_ic_null_calibration_feature_filter.py
  - tests/unit/services/test_ensemble_trainer_alignment_gate.py
  - tests/unit/test_concept_registry_service.py
  - tests/unit/test_ensemble_weight_compare.py
  - tests/unit/test_ic_engine_fingerprint.py
  - tests/unit/test_ic_engine_lifecycle_hook.py
  - tests/unit/test_ic_engine_staleness.py
  - tests/unit/test_ic_shrinkage_step.py
  - tests/unit/test_interaction_primitives_parent_order.py
findings:
  critical: 1
  warning: 3
  info: 2
  total: 6
status: issues_found
---

# Phase 170: Code Review Report

**Reviewed:** 2026-08-05T01:06:14Z
**Depth:** standard
**Files Reviewed:** 33 (`diff_base` supplied by the workflow, `e7936fa91fa04ed3ac71b52c030507701719df24^`, resolves to 2026-06-05 — roughly two months before this phase's actual work; it was not usable for scoping and was ignored in favor of the explicit `files` list. The real Phase 170 commit range was reconstructed as `b0f9f371^..75d5c5fa` for diff context.)
**Status:** issues_found

## Summary

Reviewed the Phase 170 concept_registry/feature_domain migration: two SQL migrations (283 schema, 284 data fold-in + transition-log replay), the `ConceptRegistryService` sync lifecycle path, `ic_engine.py`'s dual-write shadow-mode lifecycle hook, `ensemble_trainer.py`'s repointed alignment gate, seven repointed `ops_*` scripts, and the associated unit/integration test suites.

Overall this is unusually careful work: idempotent migrations with hard integrity assertions, a documented and tested cycle guard + cascade trigger, a fail-closed FDR guard on promotion (both async and sync paths), a parity precondition + divergence detector wrapping the new dual write, and a real DB-touching test suite proving the lineage/cascade mechanisms rather than just asserting SQL string shape. No SQL injection, no hardcoded secrets, no eval/exec usage, no empty catch blocks were found.

One genuine functional defect was found (BLOCKER): the repointed `ops_concept_registry_override.py` actuator can never successfully promote any concept to `active` in any domain, because every seeded `concept_gate.fdr_required` in the database defaults to `true` and the script has no way to supply `fdr_passed=True` — and the failure it hits instead is reported as a generic "optimistic lock miss / rerun" hint, which is actively misleading for this specific, deterministic failure mode. The remaining findings are quality/robustness gaps that do not rise to data-loss or security concerns.

## Critical Issues

### CR-01: `ops_concept_registry_override.py` cannot ever promote a concept to `active`, and misreports why

**File:** `scripts/ops/alpha/ops_concept_registry_override.py:64-156` (see especially 108-131)
**Issue:**
`ConceptRegistryService.record_transition_sync` fail-closes any transition to `to_status == "active"` when the concept's `concept_gate.fdr_required` is true and the caller did not pass `fdr_passed=True` (`src/intelligence/concept_registry_service.py:187-193` sync-path guard, mirrored at the async `decide_comparison_action`). Every `concept_gate` row seeded so far defaults `fdr_required` to `true`:
- `production/migrations/169_feature_registry.sql:44` — `fdr_required BOOLEAN NOT NULL DEFAULT true` (source column migration 284 copies verbatim into every `domain='feature'` `concept_gate` row via `fr.fdr_required`).
- `production/migrations/226_concept_registry_seed_ensemble_strategy.sql:97` — `... SELECT concept_id, 'ensemble_ic_ci_lower', 'oos_holdout', NULL, true FROM concept_registry WHERE domain = 'ensemble_strategy'` (also hardcodes `true`).

No migration or seed sets `fdr_required = false` anywhere in the repo. `ops_concept_registry_override.py`'s `argparse` surface (`--domain`, `--feature-name`, `--to-status`, `--reason`) has **no flag to supply `fdr_passed`**, and its call to `record_transition_sync` (lines 108-117) never passes one — so it always defaults to `None` (unproven). Consequently, `--to-status active` against literally any concept in the database will deterministically return `applied=False` from `record_transition_sync` every single time, for every concept, forever — this is not a race condition, it is a structural gap in the CLI surface.

Worse, the failure branch that fires (lines 119-131) cannot distinguish this from an actual optimistic-lock race:
```python
if not applied:
    # No commit needed here: nothing was written (either an optimistic-lock
    # no-op or, if to_status='active', the FDR fail-closed guard -- see ...
    _logger.error(
        "ops_concept_registry_override.optimistic_lock_miss",
        ...
        hint="status changed between read and write -- rerun to pick up the new status",
    )
    return 1
```
The event name (`optimistic_lock_miss`) and the `hint` text both actively tell the operator to "rerun" — which will fail identically every time for the FDR-gated case, since nothing about a rerun changes `fdr_passed`. An operator debugging a real incident (e.g. trying to manually re-activate a concept) gets no indication that the actual blocker is the FDR guard, and no way to satisfy it from this tool. `_VALID_STATUSES` (line 50) still advertises `"active"` as a supported `--to-status` choice with no caveat in `--help`.

**Fix:** Either (a) add a `--fdr-passed` flag (operator attests they have separately confirmed multiplicity correction, mirroring `ops_ensemble_weight_compare.py`'s pattern) and thread it through to `record_transition_sync`, or (b) if manual promotion to `active` is deliberately meant to be unreachable via this actuator, remove `"active"` from `_VALID_STATUSES` and say so in the docstring. Either way, disambiguate the two failure causes in the log/return path, e.g.:
```python
if not applied:
    fdr_required = ConceptRegistryService()._fdr_required_sync(conn, args.domain, args.feature_name) \
        if args.to_status == "active" else False
    if fdr_required:
        _logger.error(
            "ops_concept_registry_override.blocked_fdr_unverified",
            domain=args.domain, feature_name=args.feature_name,
            hint="concept_gate.fdr_required is true; this actuator has no --fdr-passed "
                 "flag to satisfy it -- promotion to 'active' cannot be forced here",
        )
    else:
        _logger.error(
            "ops_concept_registry_override.optimistic_lock_miss",
            ...
            hint="status changed between read and write -- rerun to pick up the new status",
        )
    return 1
```

## Warnings

### WR-01: Dual-write divergence detection is batched to end-of-run, not fail-fast

**File:** `services/ic_engine.py:3970-4180` (approx.; `_apply_feature_transitions`)
**Issue:** The Phase 170 Plan 06 dual write iterates every feature in `cells_by_feature`, calling both `registry_svc.record_transition_sync(...)` (feature_registry, self-committing) and `concept_svc.record_transition_sync(...)` (concept_registry, self-committing) per feature, appending any per-feature mismatch to a local `divergences` list — but the `RuntimeError` that halts the run is only raised **after the entire per-feature loop has completed**, not as soon as the first divergence is detected. Because each side's transition self-commits independently (no shared outer transaction spans the whole loop), a divergence discovered on feature #1 does not stop features #2..N from also being written — potentially compounding several split-brained concept_registry rows (out of sync with the still-authoritative feature_registry) within a single run before the crash finally halts further processing. The parity precondition at the top of the *next* run will catch this, but only after the fact.
**Fix:** Raise immediately on the first detected divergence (or wrap the per-feature dual-write pair in a check-then-continue that stops the loop as soon as one mismatch is found), so the blast radius of a broken invariant is bounded to at most one feature per run rather than the whole remaining cohort.

### WR-02: Stale comment claims `registry_svc` is "write-only" from Plan 06 on, but a live read remains

**File:** `services/ic_engine.py` (`_apply_feature_transitions`, shadow_only branch)
**Issue:** The function's docstring/inline comment states: *"ic_engine's status-branching READ below uses the concept-side map (concept_status_by_feature) ... registry_svc remains a WRITE target only from this point on."* In practice, the shadow_only→active promotion-eligibility check still reads from `registry_svc`:
```python
if registry_svc.is_promotion_eligible(
    feature_name,
    config.decay_recovery_min_observations,
    config.decay_recovery_min_passes,
):
```
This is not incorrect today (feature_registry remains the authoritative source until Plan 08's DROP, and any registry_svc/concept_svc counter divergence is independently caught by the comparison block a few lines above), but the comment overstates what was actually repointed — only the top-level status branch was repointed to `concept_status_by_feature`; the promotion-eligibility read was not. A future maintainer reading only the comment (not the code) could reasonably believe `concept_svc` already drives every lifecycle decision.
**Fix:** Correct the comment to scope its claim precisely to the status branch, e.g. "the STATUS branch below reads from concept_status_by_feature; the shadow-counter promotion-eligibility check below still reads registry_svc (unchanged from before Plan 06) and is verified against concept_svc's own counters via the divergence check above."

### WR-03: `ops_canary_integrity_assert.py`'s registry JOIN doesn't defend against tombstone rows, inconsistent with sibling scripts

**File:** `scripts/ops/alpha/ops_canary_integrity_assert.py:76-85` (`_CANARY_ROWS_SQL`)
**Issue:** Every other Phase 170-repointed `ops_*` script that reads `concept_registry` for `domain='feature'` data (`ops_broadcast_feature_audit.py`, `ops_ic_shrinkage.py`, `ops_lookahead_horizon_response.py`, `ops_concept_feature_migration_verify.py`) defensively `INNER JOIN concept_gate` to exclude migration 284's two gate-less tombstone rows, each with a comment explaining why. `ops_canary_integrity_assert.py`'s `_CANARY_ROWS_SQL` instead does a bare `JOIN concept_registry r ON r.name = s.feature_name AND r.domain = 'feature'` with no `concept_gate` join. This happens to be harmless today only because migration 284 hardcodes `is_control = false` on both tombstone rows, so `WHERE r.is_control = true` naturally excludes them — but the pattern is inconsistent with every sibling script's stated defensive convention, and a future tombstone-seeding path that doesn't hardcode `is_control = false` would silently reintroduce the gap this file's siblings guard against.
**Fix:** Add the same `JOIN concept_gate cg ON cg.concept_id = r.concept_id` for consistency with the rest of the repointed scripts, even though it is currently a no-op.

## Info

### IN-01: Migration 284's tombstone rows hardcode `enabled = false` rather than deriving it from status

**File:** `production/migrations/284_concept_registry_feature_domain_seed.sql:248-271`
**Issue:** The main feature seed derives `enabled` from `(fr.status = 'active')` (line 149), correctly maintaining the `enabled = (status='active')` invariant the rest of the schema enforces (`_check_enabled_invariant` in `ops_concept_feature_migration_verify.py`, the cascade trigger, `record_transition_sync`'s CAS UPDATE). The tombstone-row INSERT for orphaned `feature_transition_log` entries instead hardcodes `false` unconditionally, regardless of `s.to_status` (the orphan's last known status, which could theoretically be `'active'`). Live-verified today to pass (both orphaned features' last known status was non-active), so this is not a currently-live bug, but it's a latent invariant violation risk if this migration is ever re-derived against a different history where an orphan's last known status happened to be `'active'`.
**Fix:** Derive `enabled` the same way the main seed does: `(s.to_status = 'active')` instead of the literal `false`, for consistency and defense-in-depth (the row would still be logically inert — no `concept_gate` row, no code path drives an inert tombstone — but the invariant would hold unconditionally rather than by data-dependent luck).

### IN-02: `scripts/analysis/ops_primitive_discovery_report.py` remains an unimplemented skeleton, swept into this diff for an unrelated comment fix

**File:** `scripts/analysis/ops_primitive_discovery_report.py`
**Issue:** This file predates Phase 170 (added in Phase 142.5) and both its core functions (`generate_primitive_discovery_report`, `_write_report`) still unconditionally `raise NotImplementedError`. Phase 170's commit `fb638e86` ("sweep comment-only feature_registry references") touched only a single docstring line (`feature_registry` → `concept_registry (domain='feature')`) with no functional change. Not a defect introduced by this phase, but flagged for awareness since it appeared in the review's file list: this script is dead weight until a follow-on phase implements it.
**Fix:** No action required for Phase 170; tracked here only so a future reviewer doesn't mistake the doc-only touch for evidence this script is live.

---

_Reviewed: 2026-08-05T01:06:14Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
