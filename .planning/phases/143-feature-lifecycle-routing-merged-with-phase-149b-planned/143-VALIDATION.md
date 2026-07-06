---
phase: 143
slug: feature-lifecycle-routing-merged-with-phase-149b-planned
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-05
---

# Phase 143 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 6.0+ (`pytest.ini`), `asyncio_mode = auto`, `--strict-markers` |
| **Config file** | `pytest.ini` |
| **Quick run command** | `.venv/bin/pytest tests/unit/intelligence/test_feature_registry_service.py tests/unit/test_ic_engine_idempotency.py -q` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -q` |
| **Estimated runtime** | ~30s quick, ~5min full |

---

## Sampling Rate

- **After every task commit:** `.venv/bin/pytest tests/unit/intelligence/ tests/unit/test_ic_engine_*.py tests/unit/test_ensemble_trainer*.py -q`
- **After every plan wave:** `.venv/bin/pytest tests/unit/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD-01 | 01 | 0 | LIFECYCLE-00 | V5 | Degenerate HMM model flagged, occupation gate blocks weight use | unit | `pytest tests/unit/test_regime_writer_occupation_gate.py -x` | ❌ Wave 0 | ⬜ pending |
| TBD-02 | 01 | 0 | LIFECYCLE-00 | — | `hmm_churn` rolling label-change rate computed correctly | unit | `pytest tests/unit/test_regime_writer_churn.py -x` | ❌ Wave 0 | ⬜ pending |
| TBD-03 | 02 | 1 | LIFECYCLE-01 | — | `shadow_only -> active` transition requires 2 passing runs + observation floor | unit | `pytest tests/unit/intelligence/test_feature_registry_service.py::TestRecordTransitionSync -x` | ❌ Wave 1 (extend existing file) | ⬜ pending |
| TBD-04 | 02 | 1 | LIFECYCLE-01 | — | Automated `ic_demotion` targets `shadow_only`, never `deprecated` | unit | `pytest tests/unit/intelligence/test_feature_registry_service.py::TestRecordTransitionSync -x` | ❌ Wave 1 (same file) | ⬜ pending |
| TBD-05 | 02 | 1 | LIFECYCLE-02 | — | `ensemble_trainer` filters `feature_status_at_eval = 'active'` (regression check only) | unit | `pytest tests/unit/test_ensemble_trainer.py -x` | ✅ existing | ⬜ pending |
| TBD-06 | 03 | 2 | LIFECYCLE-03 | V5 | ic_engine post-run hook writes exactly one `feature_transition_log` row per real transition, zero on hold | unit | `pytest tests/unit/test_ic_engine_lifecycle_hook.py -x` | ❌ Wave 2 | ⬜ pending |
| TBD-07 | 03 | 2 | LIFECYCLE-04 | — | Regime-shift guard holds all weights when >=60% of cells fail simultaneously | unit | `pytest tests/unit/test_ic_engine_lifecycle_hook.py::test_regime_shift_guard -x` | ❌ Wave 2 (same file) | ⬜ pending |
| TBD-08 | 03 | 2 | LIFECYCLE-05 | — | Staleness gauge computes correct day-count, fires `IC_ENGINE_STALE` at threshold | unit | `pytest tests/unit/test_ic_engine_staleness.py -x` | ❌ Wave 2 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky. Task IDs are placeholders — planner assigns real `{plan}-{seq}` IDs.*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_regime_writer_occupation_gate.py` — stubs for LIFECYCLE-00 P2b (degenerate-model occupation-fraction gate)
- [ ] `tests/unit/test_regime_writer_churn.py` — stubs for LIFECYCLE-00 P2c (`hmm_churn` feature column)
- [ ] `tests/unit/test_ic_engine_lifecycle_hook.py` — new file; mock `FeatureRegistryService.record_transition_sync` and the write connection; covers LIFECYCLE-03/04
- [ ] `tests/unit/test_ic_engine_staleness.py` — stubs for LIFECYCLE-05
- [ ] Extend `tests/unit/intelligence/test_feature_registry_service.py` with `TestRecordTransitionSync` covering the new sync method (INSERT + UPDATE in one transaction, rollback on error)
- [ ] No framework install needed — pytest, pytest-asyncio already present and configured

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| LIFECYCLE-00 P3 empirical threshold calibration | LIFECYCLE-00 | Requires judgment against live corpus-run distributions, not a fixed assertion | Run `ic_engine` against current corpus, inspect occupation-fraction distribution, confirm calibrated threshold matches todo 026/034 findings before locking as APR default |
| LIFECYCLE-06 decay diagnostics dashboard | LIFECYCLE-06 | Explicitly deferred until routed system has operated >=30 days (per ROADMAP) | N/A this phase — do not build Superset dashboard now |

---

## Threat Model Summary (ASVS L1)

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | No new auth surface — internal batch job |
| V3 Session Management | No | No sessions involved |
| V4 Access Control | No | No new API endpoints or user-facing controls |
| V5 Input Validation | Marginal | New APR key `alpha.ic.staleness_alert_days` gets `min_value`/`max_value` bounds in `config_schema`, matching existing pattern (e.g. migration 161's bounds on `alpha.decay.materiality_threshold`) |
| V6 Cryptography | No | No secrets, keys, or crypto operations introduced |

No external input surface — the only "input" is IC values `ic_engine` already computed and committed earlier in the same run, read back via parameterized SQL. Continue the project-wide parameterized-query convention (`%(name)s` / `$1` placeholders) in all new queries; zero string-interpolated SQL for values.

---

## Environment Availability

| Dependency | Required By | Available | Fallback |
|------------|--------------|-----------|----------|
| PostgreSQL/TimescaleDB | All migrations, `feature_registry`/`integrity_monitor` reads/writes | Yes (verified live) | — |
| Python venv: psycopg2, asyncpg, structlog, opentelemetry | `ic_engine.py`, `feature_registry_service.py` edits | Yes (existing, already imported) | — |

No new external tools, services, or runtimes required.
