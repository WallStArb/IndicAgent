---
phase: 160-concept-registry-mvp
plan: 03
subsystem: Concept Registry
tags: [concept-registry, ensemble-strategy, governance, mvp, invariant-1]
wave: 2
dependency_graph:
  requires: [160-01, 160-02]
  provides: [160-04]
  affects: [ensemble-weight-comparison, concept-registry-governance]
tech_stack:
  added: []
  patterns: [tdd, backward-compatibility, pure-helper-extraction, registry-wiring]
key_files:
  created: []
  modified:
    - path: scripts/ops/alpha/ops_ensemble_weight_compare.py
      description: Added _registry_outcome pure helper, 3 CLI args, and comprehensive registry-recording block with M-2/M-6/L-4 enhancements
    - path: tests/unit/test_ensemble_weight_compare.py
      description: Added 3 new tests for _registry_outcome covering WIN-strata mean, no-win-strata, and empty cases
decisions:
  - id: D-160-03-01
    title: Concept identity via CLI not weight_version
    rationale: weight_version is a per-corpus-build epoch tag (migration 224) and does not identify the recipe; recipe is determined by APR state at trainer run time
    impact: Concepts named explicitly via --challenger-concept/--champion-concept; corpus_build_ref defaults to challenger weight_version
metrics:
  duration: PT45M
  completed_date: 2026-07-14T13:48:00Z
---

# Phase 160 Plan 03: ConceptRegistryAPI Summary

**One-liner:** Registry-invariant-1 enforcement — deterministic win-decision gate wired to ConceptRegistryService via pure `_registry_outcome` helper, optional CLI args, and M-2/M-6/L-4 auditability enhancements.

## Task Execution

**Task 5: Wire the win-decision gate to the registry (invariant 1)** ✅ COMPLETE

### TDD Execution (RED → GREEN → COMMIT)

**RED Phase:** Added 3 failing tests to `tests/unit/test_ensemble_weight_compare.py`:
- `test_registry_outcome_win_metric_is_mean_ci_lower_over_win_strata_only` — WIN strata mean=0.03 (veto excluded)
- `test_registry_outcome_no_win_strata` — No WIN → (False, None, 2000.0)
- `test_registry_outcome_empty` — Empty list → (False, None, 0.0)

All tests failed with expected `NameError: name '_registry_outcome' is not defined`. Existing tests (17) remained passing.

**GREEN Phase:** Implemented `_registry_outcome(rows)` pure helper in `scripts/ops/alpha/ops_ensemble_weight_compare.py`:
- Extracts WIN-strata `ic_ci_lower` values only (D-15 citation rule: never `ic_value`)
- Computes mean over WIN strata, excluding WIN-FDR-VETO from eval_metric
- Sums `n_independent` over ALL compared strata (evidence mass consumed)
- Returns `(won, eval_metric, eval_n)` 3-tuple, preserving exact test expectations

All 20 tests passed (17 existing + 3 new).

**Wiring Phase:** Added service integration and CLI surface:
- Imported `ConceptRegistryService` and `ConceptNotFoundError` from plan 160-02
- Added 3 optional CLI args: `--challenger-concept`, `--champion-concept`, `--corpus-build-ref`
- Replaced final `return 0` with comprehensive registry-recording block including:
  - **Base:** Outcome row construction, `_registry_outcome` call, APR key resolution, service call
  - **M-2 (auditability):** Computed `win_strata_count` and `win_only_n` for transition notes
  - **M-6 (durable evidence):** Append-only `concept_annotation` row for every recording action
  - **L-4 (champion validation):** Existence check before any write, prevents typo corruption

### Commit

```
feat(concept-registry): wire win-decision gate to ConceptRegistryService (invariant 1, todo 058)

- Add _registry_outcome pure helper to reduce per-stratum verdicts to registry-recordable outcome
- Add --challenger-concept, --champion-concept, --corpus-build-ref CLI args
- Wire registry-recording block with M-2 notes (win_strata_count, win_only_n), M-6 append-only concept_annotation, and L-4 champion validation
- Maintain backward compatibility: report-only path unchanged without --challenger-concept
- TDD: 3 new tests for _registry_outcome (mean over WIN strata only, veto excluded, empty case)
- All 40 tests pass (20 ensemble_weight_compare + 20 concept_registry_service)
```

Commit hash: `1692386b` (on `feature/160-04-concept-registry-documentation-finalization`)

Files modified: `scripts/ops/alpha/ops_ensemble_weight_compare.py` (+189 lines), `tests/unit/test_ensemble_weight_compare.py` (+34 lines)

## Verification Results

### Unit Tests
- ✅ All 20 `test_ensemble_weight_compare.py` tests pass
- ✅ All 20 `test_concept_registry_service.py` tests pass
- ✅ Combined test run: 40/40 passed in 0.90s

### Backward Compatibility (M-5)
- ✅ Report-only invocation (`--champion run_2025122405150000 --challenger run_2025122405150000_mv`, NO `--challenger-concept`) produces byte-identical output to baseline
- ✅ Exit code 0 maintained
- ✅ No `REGISTRY:` line without `--challenger-concept`

### M-5 Known Verification Gap (Stated)
**ACCEPTED:** `alpha_ensemble_ic` has 0 rows (corpus rebuild in flight), so the backward-compatibility smoke test hits the early-exit path (`"no comparable strata"`) and never reaches the modified tail of `main()` or the recording block. This verifies the early-exit path is unchanged, NOT the full report path or the recording block under live data. The recording block, M-2 notes, M-6 annotation, and L-4 validation are therefore covered by UNIT tests only, not by a live run. This gap is documented here per acceptance criteria and will close once the corpus rebuild completes and `alpha_ensemble_ic` is repopulated.

### M-2: Transition Notes with Stratum-Grain Narrowness
✅ Constructed `notes` string contains:
- `win_strata={count}` — number of WIN strata
- `win_only_n={sum}` — summed n_independent over WIN strata only
- `total_strata={len}` — all compared strata
- `gate_n={eval_n}` — all-strata summed n_independent

Verified by code inspection: notes string construction directly computes these values and passes them to `record_comparison_outcome(...)`.

### M-6: Durable Empirical Annotations
✅ Recording block appends `source='empirical'` `concept_annotation` row for every `record_win`, `record_loss`, or `promote` action. Annotation content includes: `action`, `won`, `eval_metric`, `eval_n`, `win_strata_count`, `corpus_build_ref`. Guarded append-only (no `ON CONFLICT` clause that would overwrite prior outcome rows).

Verified by code inspection: annotation INSERT guarded by `decision.action in ("record_win", "record_loss", "promote")` conditional.

### L-4: Champion Concept Validation
✅ When `--champion-concept` is provided, block validates existence against `concept_registry` on the acquired connection before any write. Unknown champion prints `REGISTRY: FAILED - unknown champion concept '{name}'` and returns 0, skipping all writes.

Verified by code inspection: validation branch precedes APR resolution and service call.

## Deviations from Plan

### Auto-fixed Issues
**None** — Plan executed exactly as written.

### H-1 Deferred Verification Gate (Critical Pre-Live-Use Check)
**DOCUMENTED:** The F3 evidence-mass floor (`min_new_observations=2000`) blocks re-eval when `(eval_n - last_eval_n) < 2000`. `eval_n` is the summed challenger `n_independent` over compared strata. Under rolling-window corpus rebuilds (fixed backfill depths: 5m:5y, 1h:15y, etc.), successive corpus builds SLIDE the window rather than grow it, so the delta between builds may be ~0 or negative. With `min_promotion_consecutive=2`, promotion needs a second passing eval — if the delta never grows by 2000 between builds, NO candidate can promote through the automated path.

**BEFORE FIRST LIVE `--challenger-concept` PROMOTION RUN:** Empirically measure `sum(n_independent)` in `alpha_ensemble_ic` across two successive corpus-build vintages and confirm the delta plausibly clears `min_new_observations=2000` for at least one real stratum-pair. If it does NOT, redefine the F3 delta (against per-stratum `n_independent` growth over the SAME strata set, or against the corpus build's new-bar count) and/or revisit migration 232's seed of `ensemble_strategy_min_new_observations`.

**CARRIED FORWARD:** This gate is recorded in follow-on todo 118 (`pending/118-migrate-feature-domain-into-concept-registry.md`) so it is not lost if the corpus rebuild finishes after this phase's execution. The recording path is unit-test-only in this MVP — no live promotion is attempted before this check runs.

### M-1 Accepted Residual Risk (Composition-Sensitive eval_n)
**ACCEPTED:** `_registry_outcome` sums `n_independent` over ALL compared strata, so `eval_n` is composition-sensitive:
- Dropping strata → negative delta (permanent block)
- Adding strata → inflates delta with zero new data
- `alpha.ensemble_ic.gate_lookahead` changes → inflates delta
- HOLD-verdict strata (degenerate p-values) → still contribute full `n_independent` toward passing `min_gate_n`

No code guard added (e.g., excluding HOLD-verdict strata from `eval_n` sum) because the entire F3 delta definition is under the H-1 empirical review and may be redefined. Guarding HOLD prematurely would optimize a formula that may change (Musk step 5: do not optimize what may be deleted). This risk is documented as accepted pending the H-1 check.

### L-3 Documented Exit-Code Caveat (Automation Hardening)
**DOCUMENTED:** All `REGISTRY: FAILED` paths in the recording block `return 0` (exit code 0), consistent with this script's informational-exit-0 convention today. When the recording path is later invoked from `ops_corpus_pipeline_run.sh` automation, a failed registry write becomes a silent failure — the exact class this project's principles forbid. This is recorded in follow-on todo 118 (automation hardening). No change now, since the path is operator-invoked and unit-test-only in this MVP.

## Threat Surface Scan

| Flag | File | Description |
|------|------|-------------|
| No new threat surface | N/A | All registry interactions flow through plan 160-02's validated ConceptRegistryService; CLI args follow existing operator-invocation pattern; M-6 append-only annotations preserve audit trail without new attack surface |

## Success Criteria

- ✅ `_registry_outcome` passes all 3 new tests with exact expected 3-tuples (mean=0.03 over WIN strata only, veto excluded)
- ✅ Report-only invocation is byte-identical to baseline (no REGISTRY line, exit 0)
- ✅ Empty-table verification gap explicitly stated in SUMMARY (M-5)
- ✅ Recording block calls ConceptRegistryService with APR-resolved floors
- ✅ M-2 transition notes carry win_strata_count + WIN-only n
- ✅ M-6 durable source='empirical' annotations appended per outcome
- ✅ L-4 champion validation guards against typos
- ✅ H-1 F3 evidence-mass viability check documented as pre-live-use gate and carried into todo 118
- ✅ Combined test run (40 tests) fully green

## Status

**PLAN COMPLETE** — All tasks executed, all verification criteria met, all deviations documented. Registry invariant 1 is now enforced: `ops_ensemble_weight_compare.py` is the sole deterministic status-flipper for `domain='ensemble_strategy'`.