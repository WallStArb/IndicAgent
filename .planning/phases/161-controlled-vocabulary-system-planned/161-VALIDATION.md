---
phase: 161
slug: controlled-vocabulary-system-planned
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-16
---

# Phase 161 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (see `pytest.ini`) |
| **Config file** | `/home/bg/dev/indicagent/pytest.ini` |
| **Quick run command** | `.venv/bin/pytest tests/unit/test_vocabulary_service.py -x -q` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -q` |
| **Estimated runtime** | ~30 seconds (unit) |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/unit/test_vocabulary_service.py -x -q`
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

No tracked requirement IDs exist for this phase (no `.planning/REQUIREMENTS.md` entries map to
Phase 161 — confirmed absent). Behavior-level test mapping from RESEARCH.md governs instead; the
planner should attach the matching automated command to whichever task implements each behavior.

| Behavior | Requirement | Test Type | Automated Command | File Exists | Status |
|----------|-------------|-----------|-------------------|-------------|--------|
| `VocabularyService.codes()`/`.label()`/`.group_codes()` return correct values for all 6 seeded namespaces | — | unit | `pytest tests/unit/test_vocabulary_service.py -x` | ❌ W0 | ⬜ pending |
| `VocabularyService` cache is populated at `initialize()`; no DB calls on subsequent reads | — | unit | `pytest tests/unit/test_vocabulary_service.py::test_no_db_calls_after_init -x` | ❌ W0 | ⬜ pending |
| Column-backed drift audit filters `''`/empty placeholder values and scopes by `regime_group` per namespace | — | unit | `pytest tests/unit/test_vocabulary_drift_audit.py -x` | ❌ W0 | ⬜ pending |
| Three-way ENUM divergence check (registry rows vs Python enum vs `pg_enum` catalog) | — | unit | `pytest tests/unit/test_vocabulary_service.py::test_enum_divergence_check -x` | ❌ W0 | ⬜ pending |
| `/api/vocabulary/{namespace}` returns seeded namespaces correctly, 404/empty for unknown namespace | — | integration (requires_db) | `pytest tests/integration/test_vocabulary_api.py -x -m requires_db` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_vocabulary_service.py` — cache behavior, `codes()`/`label()`/`group_codes()`, ENUM divergence logic. Model on `tests/unit/test_concept_registry_service.py`'s pure-Python, no-DB, dataclass-fixture (`_state(**overrides)`) style.
- [ ] `tests/unit/test_vocabulary_drift_audit.py` — `''`-filter and per-namespace `regime_group`-scoping logic, isolated from the DB.
- [ ] `tests/integration/test_vocabulary_api.py` — `/api/vocabulary/{namespace}` route against a real (test) DB; `requires_db` marker already exists in `pytest.ini`, no new marker/framework install needed.

---

## Manual-Only Verifications

*None — all phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
