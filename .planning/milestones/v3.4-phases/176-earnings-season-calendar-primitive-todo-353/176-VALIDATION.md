---
phase: 176
slug: earnings-season-calendar-primitive-todo-353
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-22
---

# Phase 176 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing, `tests/unit/`) |
| **Config file** | existing project pytest config — no new config needed |
| **Quick run command** | `.venv/bin/pytest tests/unit/intelligence/test_feature_factory_p7.py tests/unit/services/test_feature_vector_writer_column_mapping.py -x` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -q` |
| **Estimated runtime** | ~unknown, existing full-suite baseline |

---

## Sampling Rate

- **After every task commit:** Run the quick run command above.
- **After every plan wave:** Run the full suite command.
- **Before `/gsd:verify-work`:** Full suite must be green.
- **Phase completion criterion (not a unit test):** a real `feature_ic_scores` FDR/walk-forward
  gate pass against the corpus, per CONTEXT.md's Phase Boundary — "this phase ends at a real
  `feature_ic_scores` FDR/walk-forward gate pass, same as any other new primitive."

---

## Per-Task Verification Map

| Workstream | Behavior | Test Type | Automated Command | File Exists |
|---|---|---|---|---|
| Primitive compute | `_earnings_season_flag`/`_days_since_quarter_end` pure-function correctness at window boundaries (day 13/14/42/43, quarter boundaries) | unit | `pytest tests/unit/intelligence/test_feature_factory_p7.py -k earnings_season -x` | ❌ Wave 0 — new tests, mirror `test_opex_flag_third_friday` |
| Persistence column mapping | New fields land at the correct positional SQL param index, no silent shift of existing fields | unit | `pytest tests/unit/services/test_feature_vector_writer_column_mapping.py -x` | ⚠️ Existing file, needs update |
| `FeatureVector` construction-site parity | `compute()`/`compute_batch()`/`_cold_start_vector()` all populate the 2 new fields with real values | unit/integration | `pytest tests/unit/intelligence/test_feature_factory_batch_parity.py -x` | ⚠️ Existing file, needs extension |
| Regime-pass construction (per-symbol) | `_build_regime_passes()` appends the new `earnings_season` pass correctly, no double-append | unit | `pytest tests/unit/services/test_ic_engine.py -k regime_passes -x` | ⚠️ Existing file, needs new test mirroring `symbol_hmm` pass-construction tests |
| `regime_scope` CHECK constraint | New value `'earnings_season'` accepted, old 3 values still enforced | integration | migration-apply test or direct `psql` smoke check | ❌ Wave 0 |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/intelligence/test_feature_factory_p7.py` — new `earnings_season_flag`/
      `days_since_quarter_end` pure-function tests (boundary days, cold-start `bar_ts=None`)
- [ ] `tests/unit/services/test_feature_vector_writer_column_mapping.py` — new positional-index
      test for the 2 new fields
- [ ] `tests/unit/services/test_ic_engine.py` — new `_build_regime_passes()` test for the
      `earnings_season` pass
- [ ] A smoke check that the widened `regime_scope` CHECK constraint accepts
      `'earnings_season'` and still rejects an arbitrary 5th value

---

## Manual-Only Verifications

None identified — this phase is a pure data-pipeline addition (no UI, no external service
integration) and every behavior above maps to an automated test.

---

*Phase: 176-earnings-season-calendar-primitive-todo-353*
