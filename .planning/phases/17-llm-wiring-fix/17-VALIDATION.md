---
phase: 17
slug: llm-wiring-fix
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-03-06
---

# Phase 17 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pytest.ini |
| **Quick run command** | `.venv/bin/pytest tests/unit/ -x -q` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -v` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/unit/ -x -q`
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| signal_id-thread | 01 | 1 | LLM-04 | unit | `.venv/bin/pytest tests/unit/service_tests/test_signal_generator_service.py -v -k signal_id` | ✅ | ⬜ pending |
| narrative-signal-id | 01 | 1 | LLM-04 | unit | `.venv/bin/pytest tests/unit/service_tests/test_ai_narrative_helpers.py -v -k signal_id` | ✅ | ⬜ pending |
| session-regime-buckets | 02 | 1 | LLM-05 | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_session_extremes_setup.py -v` | ✅ | ⬜ pending |
| score-routing-smoke | 02 | 2 | LLM-05 | unit | `.venv/bin/pytest tests/unit/service_tests/test_llm_writer_service.py -v -k routing` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements. Test files already exist:
- `tests/unit/service_tests/test_signal_generator_service.py`
- `tests/unit/service_tests/test_ai_narrative_helpers.py`
- `tests/unit/intelligence/trading/test_session_extremes_setup.py`
- `tests/unit/service_tests/test_llm_writer_service.py`

New test cases are additions/updates to existing files — no new files needed.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| signal_id flows to llm_calls in production | LLM-04 | Requires live IBKR + signal firing | After deploy: `docker exec timescaledb psql -U postgres -d indicagent -c "SELECT count(*) FROM llm_calls WHERE signal_id IS NOT NULL"` — should increase after next signal fires |
| outcome back-fill matches llm_calls rows | LLM-04 | Requires signal lifecycle completion | After signal exits: `SELECT signal_id, outcome FROM llm_calls WHERE signal_id IS NOT NULL AND outcome IS NOT NULL LIMIT 5` |
| session_extreme_* regime keys accumulate in llm_model_scores | LLM-05 | Requires live signals + score recompute cycle | `SELECT regime, count(*) FROM llm_model_scores GROUP BY regime ORDER BY count DESC` — should show session_extreme_london/ny/both buckets |
| _preferred_models populated after score recompute | LLM-05 | Requires 30+ rows per bucket (n>=30 gate) | Check service logs for "adaptive routing activated" or query `llm_model_scores WHERE n_samples >= 30` |

---

## Validation Architecture (from RESEARCH.md)

### Break 1: signal_id threading (LLM-04)
- **Unit test:** mock `build_ledger_entries()` returning entries with `was_selected=True` and a known UUID; assert stream message contains `signal_id` key with that UUID
- **Unit test:** `parse_aggregated_signal()` with `signal_id` in message → assert returned dict contains `signal_id`
- **Unit test:** `_build_llm_call_payload()` with `signal_data["signal_id"] = "some-uuid"` → assert payload `signal_id` is not `""`
- **Production query:** `SELECT count(*) FROM llm_calls WHERE signal_id IS NOT NULL` — increases after each signal

### Break 2: regime vocabulary (LLM-05)
- **Unit test:** `SessionExtremesSetup` london session → `regime_context == "session_extreme_london"` and `"session:london"` in `supporting_factors`
- **Unit test:** `SessionExtremesSetup` ny session → `regime_context == "session_extreme_ny"` and `"session:ny"` in `supporting_factors`
- **Unit test:** `SessionExtremesSetup` overlap → `regime_context == "session_extreme_both"` and `"session:both"` in `supporting_factors`
- **Regression:** existing tests `test_regime_context_london` and `test_regime_context_ny` must be updated to new expected values
- **Production query:** `SELECT DISTINCT regime FROM llm_calls ORDER BY regime` — must NOT contain `"london"`, `"ny"`, `"both"`; must contain `"session_extreme_*"` variants after signals fire

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
