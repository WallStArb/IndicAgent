---
**Created:** 2026-07-14
**Area:** intelligence / governance
**Type:** refactor
**Priority:** P1 (raised from P2, 2026-08-04 -- user confirmed direction: feature_registry is an
  anachronism, migrate ASAP once the real remaining gate clears, don't leave it as a permanent
  parallel system)
**Effort:** 1-2 sessions
**Risk:** medium (touches the live feature lifecycle path: ic_engine post-run hook + ensemble_trainer alignment gate)
**Gate:** todo 117 is DONE (2026-07-19, confirmed 2026-08-04 -- unrelated to this migration's own
  actuator, it proved feature_registry's operator-override CLI pattern). The real remaining gate
  is the corpus rebuild landing real `alpha_ensemble_ic` rows (0 rows as of 2026-08-04) so the
  H-1/M-B live-data rehearsal below can run for the first time -- not a separate task, just
  waiting on the in-flight corpus rebuild. Execute immediately once that data exists: run the
  rehearsal, fold in L-5/L-6 below as part of the same pass, then cut ic_engine/ensemble_trainer
  over and retire feature_registry.
---

# 118 - Migrate domain='feature' (feature_registry) into the Concept Registry

Concept Registry MVP shipped 2026-07-13 (todo 058, migration 225 -- corrected 2026-08-04 from
the stale "231/232" citation the plan doc originally used before renumbering; 231/232 are
unrelated: controlled-vocabulary schema and ic_engine bootstrap threads, respectively) with
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
   verifies identical lifecycle decisions (shadow mode first). **"Retire" means
   literal DROP TABLE + delete `feature_registry_service.py` and all its callers
   (2026-08-04, explicit user override of the rename-not-drop default this
   project otherwise uses for v2.x-style retirements) -- clean removal, no
   frozen/archived tables left behind, once step 1's migration has verified
   `concept_transition_log`/replay preserves everything worth keeping from
   `feature_transition_log`. Because this is a one-way door, step 1 must
   actually replay `feature_transition_log` into `concept_transition_log` (not
   the lighter genesis-seed-with-a-pointer-back alternative that was originally
   offered as a choice) -- a pointer back to a table that's about to be dropped
   is a dangling reference, not a real preservation path.**

## Schema gaps found comparing feature_registry against concept_registry -- port before dropping (2026-08-04)

- **L-8 (multi-parent lineage, confirmed real not hypothetical):** `feature_registry.parent_features`
  is genuinely multi-valued in production -- 8 live interaction features each have exactly 2
  parents (e.g. `vol_body_product` <- `{body_ratio, volume_z}`). `concept_registry.parent_concept_id`
  is a single FK column and cannot represent this. Resolve before migrating: either a
  `concept_parent` many-to-many join table (real referential integrity per parent, heavier) or
  widen to `parent_concept_ids UUID[]` (mirrors feature_registry's own approach, no FK
  enforcement per element). **Recommendation (2026-08-04, Renaissance-lens review): build the
  join table.** `feature_registry.parent_features` is not a pattern worth preserving -- it
  references parents by name string with zero referential integrity, meaning a renamed or
  deleted parent can silently orphan the array with nothing in Postgres ever complaining. That
  is exactly the "what fails silently?" failure mode this project's own design checklist exists
  to catch. A join table with FK constraints on both `child_concept_id` and `parent_concept_id`
  makes an orphaned reference structurally impossible rather than merely unlikely. This is a
  one-way migration -- fix the weakness now, while touching this data anyway, rather than carry
  it forward and pay for a second migration once more domains (`hmm_variant`, `regime_model`)
  have real rows depending on the same lineage mechanism. Pick this before step 1's migration,
  not during it.
- **L-9 (cascade-deprecation trigger, concept_registry has zero equivalent) -- concrete design
  (2026-08-04):** `feature_registry` has a real DB trigger
  (`trg_cascade_parent_deprecation`/`fn_cascade_parent_deprecation`): deprecating a tier-0
  parent auto-deprecates every tier-1 feature listing it in `parent_features`, with a
  `trigger_reason='parent_cascade'` audit row. `concept_registry` has no trigger and no
  equivalent logic anywhere. Rebuild against L-8's `concept_parent` join table:

  ```sql
  CREATE OR REPLACE FUNCTION fn_cascade_concept_parent_deprecation()
  RETURNS trigger LANGUAGE plpgsql AS $$
  BEGIN
      IF NEW.status = 'deprecated' AND OLD.status != 'deprecated' THEN
          UPDATE concept_registry
          SET status = 'deprecated'
          WHERE status != 'deprecated'
            AND concept_id IN (
                SELECT child_concept_id FROM concept_parent WHERE parent_concept_id = NEW.concept_id
            );

          INSERT INTO concept_transition_log (concept_id, domain, name, from_status, to_status, trigger_reason, triggered_at)
          SELECT cr.concept_id, cr.domain, cr.name, 'active', 'deprecated', 'parent_cascade', NOW()
          FROM concept_registry cr
          JOIN concept_parent cp ON cp.child_concept_id = cr.concept_id
          WHERE cp.parent_concept_id = NEW.concept_id AND cr.status != 'deprecated';
      END IF;
      RETURN NEW;
  END;
  $$;

  CREATE TRIGGER trg_cascade_concept_parent_deprecation
  AFTER UPDATE OF status ON concept_registry
  FOR EACH ROW EXECUTE FUNCTION fn_cascade_concept_parent_deprecation();
  ```

  Two improvements over a literal port, not just a translation: (a) no `tier = '1_interaction'`
  string filter -- scoping comes from the join table itself, so cascading works across every
  domain automatically, not just features; (b) the inner `UPDATE` re-fires this same trigger on
  each child it touches, so multi-level dependency chains (grandchild depends on child depends
  on parent) cascade automatically without extra code. That recursion is only safe because the
  DAG has no cycles -- add an explicit cycle-check constraint on `concept_parent` inserts
  (recursive CTE guard rejecting any insert that would make a concept its own ancestor) so that
  invariant is enforced, not just assumed.
- **L-10 (control/canary mechanism, actively queried not decorative) -- concrete design
  (2026-08-04):** `is_control`/`control_expectation` are read by two live scripts --
  `ops_canary_integrity_assert.py` (asserts each control feature's measured IC matches its
  pre-registered expectation: negative controls should show no edge, `canary_acausal_placebo`
  should show a known acausal-leak artifact, as a sanity check that the measurement pipeline
  itself hasn't silently broken) and `ops_ensemble_ablation.py` (flags a "control breach" if a
  control feature ever earns real ensemble weight). These belong on `concept_registry` itself,
  not `concept_gate` -- they describe *what kind* of concept this is (identity, alongside
  `domain`/`sensitivity`), not current gate/eval state:

  ```sql
  ALTER TABLE concept_registry
      ADD COLUMN is_control BOOLEAN NOT NULL DEFAULT false,
      ADD COLUMN control_expectation TEXT
          CHECK (control_expectation IS NULL OR control_expectation IN ('negative_control', 'positive_control'));
  ```

  Repoint both scripts from `feature_registry` to
  `concept_registry WHERE domain='feature' AND is_control = true` as part of this migration --
  not folded into `metadata` JSONB, since both scripts do real `WHERE is_control = true`
  filtering today and moving to JSONB predicates would be a pure regression for no benefit.
- **Everything else folds into `metadata` JSONB, no dedicated columns needed:** `tier`,
  `formula_short`, `normalization`, `linear_ready`, `requires_htf`, `window_apr_keys[]`,
  `source_dims`, `notes` are recipe details, not gating logic -- matches this doc's own
  established `metadata.apr_namespace` pattern for exactly this kind of domain-specific detail.
  `min_ic_sharpe`/`min_ic_n` already generalize cleanly to `concept_gate.min_gate_metric`/
  `min_gate_n` (no action needed). `last_ic_value`/`last_ic_sharpe` collapsing to
  `concept_gate`'s single `last_eval_metric` is NOT a gap -- deliberate consequence of keeping
  governance lean and leaving full measurement richness in `feature_ic_scores` (2026-08-04
  measurement/governance/reporting split) -- don't re-add a second metric column later thinking
  something was missed.

## Registry-mechanism hardening (from Phase 160 review, do before automating the promotion path)

- H-1: Before the first live --challenger-concept promotion cycle, run the F3 evidence-mass floor empirical-viability check - measure sum(n_independent) delta across two successive alpha_ensemble_ic corpus vintages vs min_new_observations=2000; if the rolling-window delta is structurally ~0/negative, redefine the F3 delta (per-stratum growth over the same strata set, or corpus new-bar count) or revisit the migration-226 seed (corrected 2026-08-04 from stale "232" citation) before the floor is load-bearing. **Cannot check yet as of 2026-07-14: alpha_ensemble_ic has 0 rows (corpus rebuild not yet complete).**
- **Live-data rehearsal (Fable code review, 2026-07-14, finding M-B):** the recording block in `ops_ensemble_weight_compare.py` (the `--challenger-concept` path calling `ConceptRegistryService.record_comparison_outcome`) has never executed against real data — `alpha_ensemble_ic` is empty, so every unit test covers pure helpers or mocks only, never the live `main()` recording path. A migration-drift bug (fixed 2026-07-14, commit `6f1b4257`) and a runtime crash on the durable-annotation insert (same commit) both survived unit tests and a full plan-review pass undetected. Before the Phase 143.1 E1-vs-E2 re-run becomes the first real consumer of this path: once `alpha_ensemble_ic` has real rows, run one full rehearsal of `--challenger-concept` end-to-end (ideally against a scratch/staging DB first) and confirm the registry write, the transition log row, and the `observation` annotation all land as expected before trusting this mechanism for a real promotion decision.
- L-2: CAS the record_win/record_loss gate-cache read-modify-write (currently not compare-and-swapped, load outside any transaction) before the feature hot path inherits it under ic_engine write pressure.
- L-3: Make REGISTRY: FAILED paths exit non-zero once the recording path is invoked from ops_corpus_pipeline_run.sh automation (silent-failure class this project forbids).
- L-4: Validate operator-supplied concept args (--champion-concept and any others) against the registry when the path is automated (manual-CLI existence check already added in plan 160-03).
- **L-5 (2026-08-04 architecture review, schema gap):** `concept_gate` has no equivalent of
  `feature_registry.consecutive_shadow_passes` / `observations_since_demotion` -- checked live
  schema, those columns don't exist on `concept_gate` or `concept_registry`. Scope item 2
  ("port record_transition_sync's semantics... onto concept tables") is not just a code port;
  it needs a schema addition first, or the shadow_only -> active recovery mechanics
  (Phase 143's LIFECYCLE-01 amendments) silently regress on migration. Add these columns to
  `concept_gate` in the same migration that seeds `domain='feature'` rows, don't discover the
  gap mid-port.
- **L-6 (2026-08-04 architecture review, enforcement gap):** `concept_registry_service.py`'s own
  docstring (L-7 in that file) states FDR enforcement "lives entirely upstream in
  ops_ensemble_weight_compare.py" -- the service itself never checks `concept_gate.fdr_required`
  before writing a promotion. That's a documented assumption, not an enforced invariant: a future
  second caller of `record_comparison_outcome` (which this migration adds -- ic_engine and
  ensemble_trainer both become callers) that skips the FDR check would silently promote a feature
  without multiplicity correction. Before this migration lands, move the `fdr_required` check
  into `record_comparison_outcome` itself (fail closed if required and not passed), rather than
  trusting every future caller to remember it.

- **L-7 (2026-08-04 architecture review, cross-cutting):** [252](252-ic-engine-fingerprint-invalidation-hard-deletes-history.md)
  found `ic_engine.py`'s fingerprint invalidation hard-deletes `feature_ic_scores` history on
  any code/APR change, with no archive. Whatever fix 252 lands on should reuse the same
  provenance key (`code_content_key`/`apr_snapshot_key`/`upstream_watermark`) as the identity
  this migration's `concept_transition_log` rows key off of -- a feature's measurement history
  and its governance transition history describe the same underlying event and should be
  traceable through one shared fingerprint, not two independently-invented versioning schemes.
  Sequence 252 before or alongside this migration, not after.

## Closure (2026-08-10, Phase 170 complete)

**Status: DONE.** Per-item disposition:
- Scope 1 (migration): DONE. Migration 284 seeded 249 rows/gates/lineage + replayed
  `feature_transition_log`; migration 310 backfilled provenance for 43 more (Phase 151's
  direct-seed features); migration 311 DROPped both source tables. Full replay chosen
  over genesis-seed-with-pointer as required.
- Scope 2 (port record_transition_sync): DONE, Plan 04 (`ConceptRegistryService` sync
  psycopg path).
- Scope 3 (repoint consumers): DONE, Plans 06/07 (`ic_engine` lifecycle hook,
  `ensemble_trainer` alignment gate, `docs/analysis/feature-decay-queries.sql`).
- Scope 4 (retire, literal DROP): DONE, migration 311 + Task 1's code deletion
  (`feature_registry_service.py` + its test module).
- L-8 (multi-parent lineage join table): DONE, migration 283, `concept_parent`.
- L-9 (cascade-deprecation trigger): DONE, migration 283, `fn_cascade_concept_parent_deprecation`.
- L-10 (control/canary columns): DONE, migration 283, `concept_registry.is_control`/`control_expectation`.
- H-1 (F3 evidence-mass floor viability): MEASURED, Plan 05 (self-blocked on `alpha_ensemble_ic`
  at the time; not a blocker for the `feature`-domain scope, which uses `record_transition_sync`
  not `record_comparison_outcome`).
- L-2/L-3/L-4 (CAS gate-cache, non-zero exit, operator-arg validation): DONE, Plan 02.
- L-5 (shadow-recovery counter columns): DONE, migration 283.
- L-6 (fail-closed FDR enforcement inside the service): DONE, Plan 02.
- **L-7: CONTRACT RECORDED, NOT IMPLEMENTED.** Todo 252 (fingerprint-tuple reuse for
  `concept_transition_log` provenance) remains explicitly out of this migration's scope;
  its eventual fix must reuse `code_content_key`/`apr_snapshot_key`/`upstream_watermark`.

**Deviation from this todo's own written plan:** the live `registry_dual_write_verified`
evidence bar for the DROP (Plan 08) was found to be structurally unreachable under the
OOS-pin discipline (every in-sample `ic_engine` run's `training_window_end` clamps to the
same already-evaluated window), not merely unmet. Retired on the static parity check
(`ops_concept_feature_migration_verify.py`, VERDICT: PASS) plus explicit user
authorization instead. Full rationale: migration 311's header comment and
`docs/research/concept-unified-registry.md`'s 2026-08-10 revision-history entry.

## References

- docs/research/concept-unified-registry.md (Invariants 8/9; the
  FeatureRegistryService CAS critique is already implemented in
  ConceptRegistryService - reuse it)
- docs/plans/archive/2026-07-13-concept-registry-mvp-implementation-plan.md (todo 058)
- docs/research/intel-14-integrity-monitor.md OQ3 (resolved as described above)
- src/intelligence/feature_registry_service.py, services/ic_engine.py