---
phase: 143
slug: feature-lifecycle-routing-merged-with-phase-149b-planned
status: draft
nyquist_compliant: true
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

- **After every task commit:** `.venv/bin/pytest tests/unit/intelligence/ tests/unit/test_ic_engine_*.py tests/unit/test_ensemble_trainer*.py tests/unit/test_regime_writer_*.py -q`
- **After every plan wave:** `.venv/bin/pytest tests/unit/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

Real task IDs assigned as `{plan}-{task}`. Waves match PLAN.md frontmatter (`wave: 1/2/3`).
Migration-only tasks (01-01, 02-01, 03-01) are verified by their own `psql` apply/assert commands in
the PLAN and are not repeated here; this map tracks the behavior-bearing (test) tasks.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-02 | 01 | 1 | LIFECYCLE-00 | T-143-02 | Degenerate HMM model flagged; occupation gate skips write | unit | `pytest tests/unit/test_regime_writer_occupation_gate.py -x` | ❌ create in 01-02 | ⬜ pending |
| 01-03 | 01 | 1 | LIFECYCLE-00 | — | `hmm_churn` rolling label-change rate computed correctly | unit | `pytest tests/unit/test_regime_writer_churn.py -x` | ❌ create in 01-03 | ⬜ pending |
| 02-02 | 02 | 2 | LIFECYCLE-01 | T-143-03 | `shadow_only -> active` requires 2 passing runs + 2000-obs floor; automated `ic_demotion` targets `shadow_only`, never `deprecated` | unit | `pytest tests/unit/intelligence/test_feature_registry_service.py::TestRecordTransitionSync -x` | ❌ extend existing file | ⬜ pending |
| 03-02 | 03 | 3 | LIFECYCLE-03 | T-143-07 | Post-run hook writes exactly one `feature_transition_log` row per real transition, zero on hold | unit | `pytest tests/unit/test_ic_engine_lifecycle_hook.py -x` | ❌ create in 03-02 | ⬜ pending |
| 03-02 | 03 | 3 | LIFECYCLE-04 | T-143-06 | Regime-shift guard holds all weights when >=60% of active cells fail simultaneously | unit | `pytest tests/unit/test_ic_engine_lifecycle_hook.py::test_regime_shift_guard -x` | ❌ same new file | ⬜ pending |
| 03-02 | 03 | 3 | LIFECYCLE-05 | T-143-08 | Staleness gauge computes correct day-count, fires `IC_ENGINE_STALE` at threshold | unit | `pytest tests/unit/test_ic_engine_staleness.py -x` | ❌ create in 03-02 | ⬜ pending |
| 03-03 | 03 | 3 | LIFECYCLE-02 | — | `ensemble_trainer` filters `feature_status_at_eval = 'active'` (regression lock only) | unit | `pytest tests/unit/test_ensemble_trainer.py -x` | ✅ existing (extend) | ⬜ pending |
| 03-03 | 03 | 3 | LIFECYCLE-06 | — | Decay diagnostics SQL exists (ad-hoc, no dashboard) | file check | `test -f docs/analysis/feature-decay-queries.sql` | ❌ create in 03-03 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky.*

---

## Wave Requirements (test files created inside the owning task, TDD-first)

- [ ] `tests/unit/test_regime_writer_occupation_gate.py` — LIFECYCLE-00 P2b (degenerate-model occupation gate) — created in task 01-02
- [ ] `tests/unit/test_regime_writer_churn.py` — LIFECYCLE-00 P2c (`hmm_churn` feature) — created in task 01-03
- [ ] `tests/unit/intelligence/test_feature_registry_service.py::TestRecordTransitionSync` — LIFECYCLE-01 sync transition writer + promotion eligibility — extended in task 02-02
- [ ] `tests/unit/test_ic_engine_lifecycle_hook.py` (incl. `test_regime_shift_guard`) — LIFECYCLE-03/04; mock `FeatureRegistryService.record_transition_sync` + fake `write_conn` — created in task 03-02
- [ ] `tests/unit/test_ic_engine_staleness.py` — LIFECYCLE-05 — created in task 03-02
- [ ] `tests/unit/test_ensemble_trainer.py` — LIFECYCLE-02 regression lock on `feature_status_at_eval = 'active'` — extended in task 03-03
- [ ] No framework install needed — pytest, pytest-asyncio already present and configured

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| LIFECYCLE-00 P3 empirical threshold calibration | LIFECYCLE-00 | Requires judgment against live corpus-run distributions, not a fixed assertion | Run `ic_engine` against current corpus, inspect occupation-fraction distribution, confirm `feature.hmm.min_state_occupation` default matches todo 026/034 findings before locking as APR default. NOT attempted in the plan; defaults ship at plan-doc values. |
| LIFECYCLE-06 decay diagnostics dashboard | LIFECYCLE-06 | Explicitly deferred until routed system has operated >= 30 days (per ROADMAP) | N/A this phase — ad-hoc SQL only; do not build Superset dashboard now |

---

## Threat Model Summary (ASVS L1)

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | No new auth surface — internal batch job |
| V3 Session Management | No | No sessions involved |
| V4 Access Control | No | No new API endpoints or user-facing controls |
| V5 Input Validation | Marginal | New APR key `alpha.ic.staleness_alert_days` + `feature.hmm.min_state_occupation`/`churn_window` get `min_value`/`max_value` bounds in `config_schema`, matching migration 161's pattern |
| V6 Cryptography | No | No secrets, keys, or crypto operations introduced |

No external input surface — the only "input" is IC values `ic_engine` already computed and committed earlier in the same run, read back via parameterized SQL. Continue the project-wide parameterized-query convention (`%(name)s` / `$1` placeholders); zero string-interpolated SQL for values. No new packages installed (supply-chain gate N/A).

---

## Environment Availability

| Dependency | Required By | Available | Fallback |
|------------|--------------|-----------|----------|
| PostgreSQL/TimescaleDB | All migrations, `feature_registry`/`integrity_monitor` reads/writes | Yes (verified live) | — |
| Python venv: psycopg2, asyncpg, structlog, opentelemetry | `ic_engine.py`, `feature_registry_service.py`, `regime_writer.py` edits | Yes (existing, already imported) | — |

No new external tools, services, or runtimes required.
