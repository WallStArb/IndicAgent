---
phase: 170-concept-registry-feature-domain-migration-feature-registry-r
plan: 06
subsystem: database
tags: [postgresql, psycopg, asyncpg, concept_registry, feature_registry, ic_engine, ensemble_trainer, lifecycle-governance, shadow-mode]

requires:
  - phase: 170-04
    provides: ConceptRegistryService's synchronous psycopg lifecycle path (load_sync/record_transition_sync/advance_shadow_counters_sync/is_promotion_eligible/get_all_concepts)
provides:
  - "ic_engine reads all feature lifecycle state (fingerprint watermark, alignment gate, status map, status-refresh SQL) from concept_registry(domain='feature') instead of feature_registry"
  - "ic_engine's post-run lifecycle hook dual-writes every demotion/promotion/counter-advance to BOTH feature_registry and concept_registry, comparing outcomes and raising loudly on any disagreement"
  - "A per-run registry_dual_write_verified integrity_monitor fact -- the sole positive artifact Plan 08's irreversible DROP gate can use to prove the shadow-mode comparison actually ran"
  - "ensemble_trainer's alignment gate reads concept_registry directly via a behaviourally-tested extracted function, with zero FeatureRegistryService references left in the file"
  - "Discovered and fixed a live data-divergence bug: migration 284's 2 gate-less tombstone concept_registry rows would have permanently broken the alignment gate and the fingerprint hash-equality invariant if left unhandled"
affects: [170-07, 170-08]

tech-stack:
  added: []
  patterns:
    - "Excluding gate-less tombstone rows via INNER JOIN concept_gate (not a metadata filter) -- matches ConceptRegistryService's own _LOAD_CONCEPTS_SYNC_SQL semantics exactly, so every concept_registry(domain='feature') read in the codebase (ic_engine's raw SQL, ensemble_trainer's raw SQL, ConceptRegistryService's own query) agrees on what counts as a real, governed concept"
    - "Emit an unconditional, exclusively-named integrity_monitor fact as positive proof a code path executed -- an absence of failure facts cannot distinguish 'ran clean' from 'never ran'; a fact that can ONLY be produced by the code path in question can"
    - "Dual-write divergence: accumulate a divergences list across the per-feature loop rather than raising mid-loop, so a comparison failure never leaves the two registries in different per-feature states for features already processed in the same run"

key-files:
  created:
    - tests/unit/services/test_ensemble_trainer_alignment_gate.py
  modified:
    - services/ic_engine.py
    - services/ensemble_trainer.py
    - tests/unit/test_ic_engine_fingerprint.py
    - tests/unit/test_ic_engine_lifecycle_hook.py
    - tests/unit/test_ic_engine_staleness.py

key-decisions:
  - "_fingerprint_computational_key drops BOTH the pre-cutover ('feature_registry') and post-cutover ('concept_registry') watermark key names via a shared _LEGACY_REGISTRY_WATERMARK_KEYS constant, not just the new name -- a single-name filter would spuriously invalidate every cell in the corpus on the FIRST post-cutover run (a stored fingerprint still carries the old key; the freshly-computed one carries the new key; a filter that only strips one leaves an unmatched entry on the other side), i.e. exactly the ~70h recompute this plan exists to avoid. Proven by the new test_computational_key_unchanged_by_registry_key_rename."
  - "Migration 284's 2 gate-less tombstone concept_registry rows (new_high_flag/new_low_flag, kept only to preserve orphaned feature_transition_log history) are excluded from every raw-SQL concept_registry(domain='feature') read in this plan (ic_engine's watermark + status-refresh SQL, ensemble_trainer's alignment gate) via an INNER JOIN to concept_gate -- matching ConceptRegistryService's own _LOAD_CONCEPTS_SYNC_SQL, which already excludes them the same way. Discovered live: the plan's literal domain-only-filtered SQL produced 251 names vs feature_registry's 249, breaking both the alignment gate and the md5 hash-equality acceptance criterion."
  - "Task 1 keeps registry_svc (FeatureRegistryService) constructed/loaded in main() even though the alignment gate no longer reads it -- it remains the write-side counterpart Task 2's dual write needs; only Plan 08 removes it."
  - "The parity precondition inside _apply_feature_transitions branches ic_engine's demote/promote status decision on the CONCEPT-side status map (concept_status_by_feature), not the feature_registry-side one -- consistent with Task 1's 'repoint reads to concept_registry' intent; registry_svc is now write-only from that point forward."
  - "Task 3's ensemble_trainer alignment gate is a plain async function reading asyncpg directly, NOT a ConceptRegistryService instantiation -- the service's only async surface (record_comparison_outcome) is unrelated to a one-line name-set check, and adding an async load() would be scaffolding for a single caller."

requirements-completed: [S-3, S-4]

duration: ~35min active (task 1 committed 13:43 local; tasks 2-3 resumed and committed 19:06-19:10 local after a mid-session interruption)
completed: 2026-08-04
---

# Phase 170 Plan 06: ic_engine + ensemble_trainer Concept Registry Cutover (Shadow Mode) Summary

**Both live feature-lifecycle writers (ic_engine, ensemble_trainer) now read from concept_registry(domain='feature'); ic_engine additionally dual-writes every lifecycle transition to both registries in shadow mode, comparing outcomes and emitting a per-run `registry_dual_write_verified` integrity_monitor fact that is Plan 08's sole authorising evidence for the eventual DROP.**

## Performance

- **Duration:** ~35 min of active execution across 3 tasks (task 1 committed 2026-08-04T13:43:05-04:00; a mid-session interruption occurred; tasks 2-3 resumed and committed 2026-08-04T19:06:10-04:00 and 2026-08-04T19:10:38-04:00)
- **Tasks:** 3/3 complete
- **Files modified:** 7 (2 created, 5 modified)

## Accomplishments

- **Task 1** repointed every ic_engine READ of feature lifecycle state (fingerprint watermark, alignment gate, feature status map, status-refresh SQL) from `feature_registry` to `concept_registry(domain='feature')`, with a live-verified byte-identical status hash before/after the cutover.
- **Task 2** made ic_engine's post-run lifecycle hook dual-write every demotion/promotion/shadow-counter-advance to both `feature_registry` (via the retained `FeatureRegistryService`) and `concept_registry` (via `ConceptRegistryService`'s sync API), with a status-parity precondition at hook entry, per-transition outcome comparison, and a per-run `registry_dual_write_verified` fact that is the one positive artifact proving the comparison actually ran (vs. never running at all).
- **Task 3** repointed ensemble_trainer's alignment gate to a directly-testable `_assert_concept_registry_alignment(conn)` function reading `concept_registry` via asyncpg, deleted the `FeatureRegistryService` import entirely, and re-proved end-to-end parity (`ops_concept_feature_migration_verify.py` → `VERDICT: PASS`).
- **Found and fixed a real, load-bearing data-divergence bug** in both Task 1 and Task 3: migration 284 (Plan 03) seeded 2 gate-less "tombstone" `concept_registry` rows to preserve orphaned `feature_transition_log` history. The plan's literal SQL (`WHERE domain = 'feature'`, no join) would have permanently broken the alignment gate (251 concept names vs. 249 `FeatureVector` fields) and the md5 hash-equality acceptance criterion on every single run. Fixed by joining `concept_gate` in every raw-SQL concept-registry read, matching `ConceptRegistryService`'s own `_LOAD_CONCEPTS_SYNC_SQL` semantics (an `INNER JOIN` that already excludes tombstones the same way).
- **Found and fixed a fingerprint-safety gap**: a naive single-name rename of the watermark's status-hash key (`"feature_registry"` → `"concept_registry"`) would have spuriously invalidated every cell in the corpus on the first post-cutover run (a stored pre-cutover fingerprint still carries the old key name; a freshly-computed post-cutover one carries the new name; a filter dropping only one leaves an unmatched entry on the other side) — exactly the ~70h recompute this plan exists to avoid. Fixed with `_LEGACY_REGISTRY_WATERMARK_KEYS`, dropping both names, and proven by the new `test_computational_key_unchanged_by_registry_key_rename`.

## Task Commits

Each task was committed atomically:

1. **Task 1: Repoint ic_engine's registry READS to concept_registry** - `3de7ae55` (feat)
2. **Task 2: Dual-write the lifecycle hook with a loud divergence assertion and a per-run verification fact** - `29c4b3db` (feat)
3. **Task 3: Repoint ensemble_trainer's alignment gate, prove it behaviourally, and re-verify end-to-end parity** - `34a0609b` (feat)

## Files Created/Modified

- `services/ic_engine.py` - `_watermark_feature_registry` → `_watermark_concept_registry` (concept_registry+concept_gate join, docstring updated); watermark dict key + `_fingerprint_computational_key` filter renamed to `"concept_registry"` with legacy-key dual-drop safety; alignment gate replaced with `ConceptRegistryService(domain='feature')`; `_FEATURE_STATUS_REFRESH_SQL` repointed with the same concept_gate join; `_apply_feature_transitions`/`_run_lifecycle_hook` gained a `concept_svc` parameter and now dual-write every transition with a parity precondition, per-transition divergence comparison, and the `registry_dual_write_verified`/`registry_divergence` integrity_monitor emits.
- `services/ensemble_trainer.py` - `FeatureRegistryService` import and instantiation removed; new `_assert_concept_registry_alignment(conn)` async function (concept_registry + concept_gate join query) replaces the inline gate; `ensemble_trainer.registry_loaded` renamed to `ensemble_trainer.concept_registry_loaded`; a one-line comment added to the untouched `feature_status_at_eval = 'active'` filter.
- `tests/unit/test_ic_engine_fingerprint.py` - renamed every `feature_registry`-keyed watermark test/fixture to `concept_registry`; added `test_computational_key_unchanged_by_registry_key_rename`.
- `tests/unit/test_ic_engine_lifecycle_hook.py` - added `_FakeConceptRegistryService` + `_make_registries()` helper (mirroring the existing `_FakeRegistryService` pattern with the concept sync API's keyword-only shape); updated all 25 pre-existing call sites to the new `_run_lifecycle_hook` signature; updated 2 assertions whose expected `integrity_monitor` insert count moved from 1 to 2 (the new unconditional `registry_dual_write_verified` fact); added 5 new dual-write tests (see Deviations).
- `tests/unit/test_ic_engine_staleness.py` - updated its 2 direct `_run_lifecycle_hook` calls (imported from the lifecycle-hook test module) for the new `concept_svc` parameter.
- `tests/unit/services/test_ensemble_trainer_alignment_gate.py` (new) - 3 behavioural tests: pass-on-exact-match, raise-on-drift (asserting both symmetric-difference names appear in the message), and a pinned assertion that the query scopes to `domain = 'feature'` with no `status` filter.

## Decisions Made

See `key-decisions` in frontmatter. Summary: the fingerprint computational key must drop both the old and new watermark key names (not just the new one) to avoid a spurious full-corpus recompute on the first post-cutover run; every raw-SQL `concept_registry(domain='feature')` read in this plan joins `concept_gate` to exclude migration 284's 2 tombstone rows, matching `ConceptRegistryService`'s own query shape; `registry_svc` stays constructed in `main()` through Task 1 (needed for Task 2's dual write, removed only in Plan 08); the demote/promote status branch reads the concept-side map, not the registry-side one; `ensemble_trainer`'s gate is a plain function, not a `ConceptRegistryService` instantiation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Migration 284's tombstone rows would have broken the alignment gate and hash-equality invariant on every run**
- **Found during:** Task 1, verifying the acceptance criterion's two md5 hashes
- **Issue:** The plan's literal SQL for `_watermark_concept_registry`/the alignment gate/`_FEATURE_STATUS_REFRESH_SQL` filters only on `domain = 'feature'`. Migration 284 (Plan 03) seeded 2 gate-less "tombstone" rows (`new_high_flag`/`new_low_flag`, `metadata->>'migrated_from'='feature_transition_log'`) to preserve orphaned `feature_transition_log` history whose feature no longer exists in `feature_registry`. An unscoped `domain='feature'` count is 251 (249 real + 2 tombstones) — never equal to `feature_registry`'s 249 rows or `FeatureVector`'s 249 fields. Verified live: unscoped hashes were `80d30aee7b7766db9b6a18f2466cd6c3` vs `4fadbe90ab6050fa12e7f25196f32b28` (unequal, the plan's own stop condition).
- **Fix:** Joined `concept_gate` (`INNER JOIN concept_gate cg ON cg.concept_id = cr.concept_id` / `USING (concept_id)`) in `_watermark_concept_registry`, `_FEATURE_STATUS_REFRESH_SQL`, and `ensemble_trainer`'s `_assert_concept_registry_alignment` — tombstones carry no `concept_gate` row by design (migration 284's own header), so the join naturally excludes them, matching `ConceptRegistryService`'s own `_LOAD_CONCEPTS_SYNC_SQL`. The alignment gate itself (`ConceptRegistryService.get_all_concepts()`, used via `load_sync`) already excludes tombstones correctly since it goes through that same query — no fix needed there.
- **Files modified:** `services/ic_engine.py`, `services/ensemble_trainer.py`.
- **Verification:** Live query after the fix: both hashes equal `4fadbe90ab6050fa12e7f25196f32b28`. `ops_concept_feature_migration_verify.py` → `VERDICT: PASS` (11/11 checks). Live alignment-gate dry run (`ConceptRegistryService.load_sync(conn, domain="feature")` vs `dataclasses.fields(FeatureVector)`) confirmed `n_concepts=249`, symmetric difference empty.
- **Committed in:** `3de7ae55` (Task 1), `34a0609b` (Task 3).

**2. [Rule 1 - Bug] A single-name watermark-key filter would trigger a spurious full-corpus recompute on the first post-cutover run**
- **Found during:** Task 1, writing the plan-mandated `test_computational_key_unchanged_by_registry_key_rename` test
- **Issue:** The plan's literal instruction renames the watermark dict key `"feature_registry"` → `"concept_registry"` and updates `_fingerprint_computational_key`'s filter to drop only the new name. A fingerprint stored by yesterday's (pre-cutover) code still carries `"feature_registry"` in its `upstream_watermark`; the very next run's freshly-computed fingerprint carries `"concept_registry"` instead. Filtering only the new name would leave the OLD stored fingerprint's `"feature_registry"` entry unfiltered while the NEW one has nothing to compare it against — a computational-key mismatch on literally every cell in the corpus on the first post-cutover run, i.e. the ~70h recompute this entire plan exists to avoid.
- **Fix:** Added `_LEGACY_REGISTRY_WATERMARK_KEYS = frozenset({"feature_registry", "concept_registry"})`; `_fingerprint_computational_key` drops both names. This is a permanent no-op once every stored fingerprint has been refreshed to the new key, and correct during the transition.
- **Files modified:** `services/ic_engine.py`, `tests/unit/test_ic_engine_fingerprint.py` (the new test proves computational-key equality between an old-key-named and a new-key-named fingerprint, otherwise identical).
- **Verification:** `test_computational_key_unchanged_by_registry_key_rename` passes; full `tests/unit/` suite green.
- **Committed in:** `3de7ae55`.

**3. [Rule 4-adjacent, resolved via plan's own explicit fallback instruction] New dual-write tests placed in a different file than named**
- **Found during:** Task 2, reading `tests/unit/services/test_ic_engine.py` per the plan's read_first instruction
- **Issue:** The plan names `tests/unit/services/test_ic_engine.py` for the 5 new dual-write tests, but that file (176 lines) is scoped entirely to a Renaissance-primitive IC-query-structure skeleton test (Phase 142.5) with zero lifecycle-hook fixtures — it has no fake connection, no fake registry service, nothing that reaches `_run_lifecycle_hook`/`_apply_feature_transitions`.
- **Fix:** The plan itself anticipates this ("or a new sibling module if that file's fixtures do not reach the hook -- decide by reading it"). Added the 5 new tests to `tests/unit/test_ic_engine_lifecycle_hook.py`, the actual sibling module with the fake conn/registry doubles (`_FakeLifecycleConn`, `_FakeRegistryService`) that already exercises this exact hook, plus a new `_FakeConceptRegistryService` + `_make_registries()` helper mirroring the existing pattern.
- **Files modified:** `tests/unit/test_ic_engine_lifecycle_hook.py` (not `tests/unit/services/test_ic_engine.py`).
- **Verification:** All 5 named tests exist and pass (`test_lifecycle_hook_dual_writes_both_registries`, `test_lifecycle_hook_raises_on_status_parity_mismatch`, `test_lifecycle_hook_raises_on_transition_outcome_divergence`, `test_lifecycle_hook_emits_dual_write_verified_fact_on_clean_run`, `test_promotion_passes_fdr_attestation`).
- **Committed in:** `29c4b3db`.

**4. [Rule 3 - Blocking] tests/unit/test_ic_engine_staleness.py broke on the new concept_svc parameter**
- **Found during:** Task 2, full-suite verification after the signature change
- **Issue:** This file imports `_FakeRegistryService`/`_run_lifecycle_hook` directly from `test_ic_engine_lifecycle_hook.py` and calls the hook itself (2 call sites) — not in the plan's `files_modified` list, but broken by the new required `concept_svc` parameter.
- **Fix:** Updated the import to `_make_registries` and both call sites to construct/pass a matching `concept` fake.
- **Files modified:** `tests/unit/test_ic_engine_staleness.py`.
- **Verification:** Both tests pass; full `tests/unit/` suite green.
- **Committed in:** `29c4b3db`.

---

**Total deviations:** 4 (2 load-bearing data/correctness bugs found via the plan's own mandated verification steps, 1 test-location judgment call the plan explicitly delegated, 1 blocking cross-file signature fix)
**Impact on plan:** All four were necessary for correctness or for the plan's own stated acceptance criteria to be satisfiable at all — none represent scope creep. The two Rule 1 fixes are the kind of thing this plan's own verification steps (md5 hash equality, the key-rename test) exist specifically to catch, and did.

## Issues Encountered

A monthly API spend-limit interruption occurred mid-session between Task 1 (committed 13:43) and Tasks 2-3 (committed 19:06-19:10); Task 1's work was already fully committed and verified before the interruption, so execution resumed cleanly from Task 2 with no rework.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- ic_engine is now in true shadow mode: every lifecycle transition lands on both registries, compared, with a durable `integrity_monitor` audit trail (`registry_dual_write_verified` / `registry_divergence`). Plan 07 and Plan 08 can proceed once a real corpus run has exercised this dual write (Plan 08's Task 1 gate explicitly checks for at least one non-hold lifecycle-hook run's `registry_dual_write_verified` fact, bounded by this plan's merge commit timestamp).
- `ensemble_trainer.py` is fully off `feature_registry` — zero references remain (import, gate, or comment).
- `ic_engine.py` still imports `FeatureRegistryService` and constructs/loads it in `main()` — intentional, required for Task 2's dual write; Plan 08 removes it after the shadow-mode evidence gate passes.
- The two tombstone-row / concept_gate-join fixes discovered here are load-bearing for Plan 08 too: its own migration 285 pre-drop guards (row-count parity, status parity) should be checked against the SAME concept_gate-scoped counting convention this plan established, not a bare `domain='feature'` count, or Plan 08's guards could reproduce the same divergence this plan just fixed.
- `ops_concept_feature_migration_verify.py` still reports `VERDICT: PASS` (11/11 checks) against live `indicagent`.

---
*Phase: 170-concept-registry-feature-domain-migration-feature-registry-r*
*Completed: 2026-08-04*

## Self-Check: PASSED

- FOUND: services/ic_engine.py
- FOUND: services/ensemble_trainer.py
- FOUND: tests/unit/services/test_ensemble_trainer_alignment_gate.py
- FOUND: tests/unit/test_ic_engine_lifecycle_hook.py
- FOUND: tests/unit/test_ic_engine_fingerprint.py
- FOUND: tests/unit/test_ic_engine_staleness.py
- FOUND: .planning/phases/170-concept-registry-feature-domain-migration-feature-registry-r/170-06-SUMMARY.md
- FOUND: 3de7ae55 (Task 1 commit)
- FOUND: 29c4b3db (Task 2 commit)
- FOUND: 34a0609b (Task 3 commit)
- FOUND: cf1629e8 (SUMMARY commit)
