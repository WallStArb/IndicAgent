---
phase: 182
slug: security-classification-hierarchy-todo-384
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-25
---

# Phase 182 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. Source: 182-RESEARCH.md
> "Validation Architecture". Requirement IDs are CONTEXT.md decisions D-01..D-11.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (`.venv/bin/pytest`) |
| **Config file** | `pytest.ini` (root; `integration` marker registered) |
| **Quick run command** | `.venv/bin/pytest tests/unit/test_classification_service.py tests/unit/test_migration_number_uniqueness.py -x` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -q` (GitHub CI gate) plus `.venv/bin/pytest tests/integration/test_instrument_classification_coverage.py -m integration` (local, live DB) |
| **Estimated runtime** | ~10 seconds quick; full unit suite ~6 minutes |

---

## Sampling Rate

- **After every task commit:** quick run command
- **After every plan wave:** full unit suite plus the integration coverage test against the live DB
- **Before `/gsd:verify-work`:** full unit suite green and integration coverage test green; the
  verification notes state that the integration piece is not GitHub-CI-enforced
- **Max feedback latency:** 10 seconds (quick)

---

## Per-Task Verification Map

Filled by the planner per task. Required coverage by decision:

| Decision | Behavior | Test Type | Automated Command | File Exists | Status |
|----------|----------|-----------|-------------------|-------------|--------|
| D-01 | Three tables with exact constraints; seed rejects a parent/level disagreement | integration | `pytest tests/integration/test_classification_schema.py -m integration` | ❌ W0 | ⬜ pending |
| D-02/03/04 | Node tree shape; codes embed parent; four levels | unit (seed data importable) | `pytest tests/unit/test_classification_seed_shape.py -x` | ❌ W0 | ⬜ pending |
| D-05 | Single names at level 4; broad ETFs at level 1-2 | integration | `pytest tests/integration/test_instrument_classification_coverage.py -m integration -k depth` | ❌ W0 | ⬜ pending |
| D-06 | `source_ref` is one of the allowed values | integration | same file `-k source_ref` | ❌ W0 | ⬜ pending |
| D-07 | Every `valid_from` >= build date | integration | same file `-k valid_from` | ❌ W0 | ⬜ pending |
| D-08 | As-of lookup; `unclassified` fallback, never NULL | unit | `pytest tests/unit/test_classification_service.py -x` | ❌ W0 | ⬜ pending |
| D-09 | Seed-time RAISE guard; onboarding hard-fails without a classification; nightly drift audit; integration coverage | unit + integration + migration guard | `pytest tests/unit/test_instrument_onboarding*.py -x`; integration coverage test | ❌ W0 | ⬜ pending |
| D-10 | `Instrument.sector` builders read the classification | unit | `pytest tests/unit/ -k "sector or instrument_from_row" -x` | ❌ W0 | ⬜ pending |
| D-11 | Migration 364+ unique, applied and committed together | unit | `pytest tests/unit/test_migration_number_uniqueness.py -x` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_classification_service.py` (D-08), mirroring `test_vocabulary_service.py`
- [ ] `tests/unit/_classification_fakes.py` (`FakeClassificationService`), mirroring `_vocabulary_fakes.py`
- [ ] `tests/unit/test_classification_seed_shape.py` (D-02..D-04)
- [ ] `tests/integration/test_instrument_classification_coverage.py` (D-05, D-06, D-07, D-09)
- [ ] `tests/integration/test_classification_schema.py` (D-01), or folded into the coverage file

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Reviewed single-name industry assignments are economically right | D-06 | Human review of IBKR-seeded candidates | Review the committed mapping table before the seed migration is applied |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
