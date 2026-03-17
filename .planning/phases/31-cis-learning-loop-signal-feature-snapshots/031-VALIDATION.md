---
phase: 31
slug: cis-learning-loop-signal-feature-snapshots
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-16
---

# Phase 31 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | `pytest.ini` / `pyproject.toml` |
| **Quick run command** | `.venv/bin/pytest tests/unit/ -v -x` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -v` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/unit/ -v -x`
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 31-01-01 | 01 | 1 | LEARN-01 | unit | `.venv/bin/pytest tests/unit/test_cis_weights_migration.py -v` | ❌ W0 | ⬜ pending |
| 31-01-02 | 01 | 1 | LEARN-01 | unit | `.venv/bin/pytest tests/unit/test_cis_scorer_load_weights.py -v` | ❌ W0 | ⬜ pending |
| 31-01-03 | 01 | 2 | LEARN-02 | unit | `.venv/bin/pytest tests/unit/test_weight_updater.py -v` | ❌ W0 | ⬜ pending |
| 31-01-04 | 01 | 2 | LEARN-03 | unit | `.venv/bin/pytest tests/unit/test_weight_updater.py::test_binary_labels -v` | ❌ W0 | ⬜ pending |
| 31-01-05 | 01 | 3 | LEARN-04 | unit | `.venv/bin/pytest tests/unit/test_promote_weights.py -v` | ❌ W0 | ⬜ pending |
| 31-02-01 | 02 | 1 | FEAT-01 | unit | `.venv/bin/pytest tests/unit/test_signal_features.py -v` | ❌ W0 | ⬜ pending |
| 31-02-02 | 02 | 1 | FEAT-02 | unit | `.venv/bin/pytest tests/unit/test_signal_ledger_shadow.py -v` | ❌ W0 | ⬜ pending |
| 31-02-03 | 02 | 2 | SHAD-01 | unit | `.venv/bin/pytest tests/unit/test_signal_generator_shadow.py -v` | ❌ W0 | ⬜ pending |
| 31-02-04 | 02 | 3 | SHAD-02 | manual | N/A — service log inspection | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_cis_weights_migration.py` — stubs for LEARN-01 (migration 034 schema)
- [ ] `tests/unit/test_cis_scorer_load_weights.py` — stubs for LEARN-01 (update_weights runtime load)
- [ ] `tests/unit/test_weight_updater.py` — stubs for LEARN-02, LEARN-03 (binary labels, cluster training)
- [ ] `tests/unit/test_promote_weights.py` — stubs for LEARN-04 (CLI promotion p-value gate)
- [ ] `tests/unit/test_signal_features.py` — stubs for FEAT-01 (signal_features hypertable write)
- [ ] `tests/unit/test_signal_ledger_shadow.py` — stubs for FEAT-02 (is_shadow column, LedgerEntry)
- [ ] `tests/unit/test_signal_generator_shadow.py` — stubs for SHAD-01 (shadow signal co-write)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| CIS scorer log shows "Loaded weights from DB for cluster=eq_index tf=1m" | LEARN-01 | Requires live DB with ≥100 resolved signals + 30-min refresh cycle | Run `weight_updater` manually; restart `market-analysis` service; tail `logs/market_analysis_service.log` |
| Shadow signals fire alongside production signals in real-time | SHAD-02 | Requires live market data feed during market hours | Query `signal_ledger WHERE is_shadow=TRUE` after market open; compare counts with `is_shadow=FALSE` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
