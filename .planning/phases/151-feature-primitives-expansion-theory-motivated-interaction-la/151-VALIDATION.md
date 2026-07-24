---
phase: 151
slug: feature-primitives-expansion-theory-motivated-interaction-la
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-24
---

# Phase 151 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | `pytest.ini` (repo root) |
| **Quick run command** | `.venv/bin/pytest tests/unit/intelligence/test_feature_factory_batch.py -q` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -q` |
| **Estimated runtime** | full suite: several minutes (unit-only, no live DB) |

---

## Sampling Rate

- **After every task commit:** Run the targeted `tests/unit/intelligence/` subset covering the touched feature family
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -q` (full suite)
- **Before `/gsd:verify-work`:** Full suite must be green, plus a live IC sweep run confirming the 28 new atomics + interaction candidates produce non-degenerate `feature_ic_scores` rows (statistical measurement, not unit-testable)
- **Max feedback latency:** ~60 seconds (targeted subset)

---

## Per-Task Verification Map

| Deliverable | Test Type | Automated Command | File Exists | Status |
|---|---|---|---|---|
| 28 new atomic primitives compute correctly (Wave 1) | unit | `.venv/bin/pytest tests/unit/intelligence/test_feature_factory_batch.py -x` (extend) | ✅ existing file, ❌ new cases W0 | ⬜ pending |
| `feature_registry`/`FeatureVector` alignment holds after new columns | unit | `.venv/bin/pytest tests/unit/intelligence/test_feature_registry_service.py -x` | ✅ existing file | ⬜ pending |
| New APR keys load correctly via `ConfigService` | unit | new test in `tests/unit/intelligence/` | ❌ W0 | ⬜ pending |
| Interaction features (`tier=1_interaction`) register with correct `parent_features` shape | unit/integration | extend `tests/unit/test_ic_engine_clustering.py`-style pattern | ❌ W0 | ⬜ pending |
| Wave 4 regime-conditioned clustering | unit | extend `tests/unit/test_ic_engine_clustering.py` | ✅ existing file, ❌ new cases W0 | ⬜ pending |
| Sparse event-flag IC methodology (`opex_flag`/`quad_witching_flag`) | manual/script | new small analysis script | ❌ not automated by design | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Unit tests for each of the 28 new atomic compute functions (extend `tests/unit/intelligence/test_feature_factory_batch.py` and/or `test_feature_factory_p7.py` pattern)
- [ ] Unit test confirming new APR keys load with correct defaults via `FeatureFactoryConfig`
- [ ] Unit test confirming `feature_registry` row count matches `FeatureVector` field count after each wave's migration (extends existing `test_feature_registry_service.py` alignment-gate coverage)
- [ ] Unit test confirming every new `tier=1_interaction` registry row has exactly 2 non-empty `parent_features` (guards against the parent_features-shape pitfall found in research — ROADMAP text says `parent_features=[]`, live precedent and pilot script require exactly 2)
- [ ] Extend `tests/unit/test_ic_engine_clustering.py` for Wave 4's regime-conditioned clustering behavior

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `opex_flag`/`quad_witching_flag` predictive value | Phase 151 calendar candidates (todo 104) | Sparse (~4%) binary flag — Spearman/standard IC is the wrong instrument; needs episode-clustered BCa bootstrap of flag days vs. matched control days | Run the small analysis script per `docs/research/signal-temporal-atomic-primitives.md`'s methodology split; compare flag-day vs. control-day forward returns via bootstrap CI |
| Full IC sweep of 28 atomics + interaction candidates | Wave 1 / Wave 3 gate | Statistical measurement against live `feature_ic_scores`, not a code-correctness unit test | Run `ic_engine.py` sweep, confirm non-degenerate BH-FDR results in both the corpus-wide pool (atomics) and the dedicated interaction pool |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
