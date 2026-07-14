---
**Created:** 2026-07-14
**Area:** intelligence / governance
**Type:** refactor
**Priority:** P2
**Effort:** 1-2 sessions
**Risk:** medium (touches the live feature lifecycle path: ic_engine post-run hook + ensemble_trainer alignment gate)
**Gate:** none - Phase 143 (the previous blocker) completed 2026-07-10
---

# 118 - Migrate domain='feature' (feature_registry) into the Concept Registry

Concept Registry MVP shipped 2026-07-13 (todo 058, migrations 231/232) with
domain='ensemble_strategy' seeded. The `domain` CHECK already includes 'feature';
zero feature rows were seeded, per todo 058 item 7.

The original sequencing blocker is resolved: Phase 143's LIFECYCLE-01 amendments
(demote-to-shadow_only, evidence-based shadow_only -> active recovery, deprecated
operator-only) shipped 2026-07-10 against feature_registry itself
(FeatureRegistryService.record_transition_sync / advance_shadow_counters_sync).
That answers intel-14 OQ3's build-time check: 143 did NOT route through
concept_registry, so the migration is now a plain fold-in.

## Scope

1. Migration: one concept_registry row per feature_registry row (150 rows,
   derived from FeatureVector fields - verify count at build time), concept_gate
   rows carrying min_ic_sharpe/min_ic_n/fdr_required/fdr_alpha, genesis or
   history-preserving transition rows (decide: replay feature_transition_log into
   concept_transition_log vs genesis-seed with a pointer back).
2. Port record_transition_sync's semantics (CAS + counter resets + deprecated
   operator-only) onto concept tables, or teach ConceptRegistryService a sync
   psycopg2 path for ic_engine's no-event-loop context.
3. Repoint consumers: ic_engine post-run lifecycle hook, ensemble_trainer
   alignment gate + eligibility reads, integrity_monitor diagnostics queries.
4. Retire feature_registry/feature_transition_log only after a full corpus run
   verifies identical lifecycle decisions (shadow mode first).

## Registry-mechanism hardening (from Phase 160 review, do before automating the promotion path)

- H-1: Before the first live --challenger-concept promotion cycle, run the F3 evidence-mass floor empirical-viability check - measure sum(n_independent) delta across two successive alpha_ensemble_ic corpus vintages vs min_new_observations=2000; if the rolling-window delta is structurally ~0/negative, redefine the F3 delta (per-stratum growth over the same strata set, or corpus new-bar count) or revisit the migration-232 seed before the floor is load-bearing.
- L-2: CAS the record_win/record_loss gate-cache read-modify-write (currently not compare-and-swapped, load outside any transaction) before the feature hot path inherits it under ic_engine write pressure.
- L-3: Make REGISTRY: FAILED paths exit non-zero once the recording path is invoked from ops_corpus_pipeline_run.sh automation (silent-failure class this project forbids).
- L-4: Validate operator-supplied concept args (--champion-concept and any others) against the registry when the path is automated (manual-CLI existence check already added in plan 160-03).

## References

- docs/research/concept-unified-registry.md (Invariants 8/9; the
  FeatureRegistryService CAS critique is already implemented in
  ConceptRegistryService - reuse it)
- docs/plans/2026-07-13-concept-registry-mvp-implementation-plan.md (todo 058)
- docs/research/intel-14-integrity-monitor.md OQ3 (resolved as described above)
- src/intelligence/feature_registry_service.py, services/ic_engine.py