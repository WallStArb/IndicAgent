---
phase: 16
slug: llm-intelligence-layer
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-05
---

# Phase 16 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pyproject.toml |
| **Quick run command** | `.venv/bin/pytest tests/unit/service_tests/test_llm_writer_service.py -v` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -q` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/unit/service_tests/test_llm_writer_service.py -v`
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 16-01-01 | 01 | 1 | LLM-01 | file check | `grep -c "create_hypertable" production/migrations/019_llm_intelligence_layer.sql` | ❌ W0 | pending |
| 16-01-02 | 01 | 1 | LLM-01 | unit (RED) | `.venv/bin/pytest tests/unit/service_tests/test_llm_writer_service.py -v 2>&1 \| grep -c "ERROR\|FAILED"` | ❌ W0 | pending |
| 16-02-01 | 02 | 2 | LLM-04 | unit (GREEN) | `.venv/bin/pytest tests/unit/service_tests/test_llm_writer_service.py -v` | ❌ W0 | pending |
| 16-02-02 | 02 | 2 | LLM-04 | regression | `.venv/bin/pytest tests/unit/ -q` | ✅ | pending |
| 16-03-01 | 03 | 3 | LLM-02 | unit | `.venv/bin/pytest tests/unit/service_tests/test_ai_narrative_service.py -v -k "llm_emit or routing"` | ❌ W0 | pending |
| 16-03-02 | 03 | 3 | LLM-05 | unit | `.venv/bin/pytest tests/unit/service_tests/test_ai_narrative_service.py -v -k "adaptive_routing"` | ❌ W0 | pending |
| 16-04-01 | 04 | 4 | LLM-03 | unit | `.venv/bin/pytest tests/unit/service_tests/test_signal_lifecycle_service.py -v -k "outcome_emit"` | ❌ W0 | pending |
| 16-05-01 | 05 | 5 | LLM-04 | manual | See Manual-Only Verifications | — | pending |
| 16-05-02 | 05 | 5 | LLM-01–05 | integration | See Manual-Only Verifications | — | pending |

*Status: pending · green · red · flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/service_tests/test_llm_writer_service.py` — created in 16-01 (TDD RED)
- [ ] `tests/unit/service_tests/test_ai_narrative_service.py` — must add llm emit + routing test stubs in 16-03
- [ ] `tests/unit/service_tests/test_signal_lifecycle_service.py` — must add outcome emit test stubs in 16-04

*Existing test infrastructure (pytest, conftest, fixtures) covers all phase requirements — no new framework install needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `llm_calls` rows appear within 30s of LLM call | LLM-01 | Requires live IBKR + Ollama | `docker exec timescaledb psql -U postgres -d indicagent -c "SELECT count(*) FROM llm_calls WHERE called_at > now()-interval '1 min'"` |
| Outcome back-fill within 60s of signal exit | LLM-02/03 | Requires signal lifecycle event | `SELECT count(*) FROM llm_calls WHERE outcome IS NOT NULL` |
| `llm_model_scores` updated after recompute | LLM-04 | Requires DB + 15-min cadence | `SELECT score_updated_at FROM llm_model_scores ORDER BY score_updated_at DESC LIMIT 1` |
| Provider chain reordered for significant model | LLM-05 | Requires n>=30 outcomes + p<0.05 | Check ai_narrative_service logs for "Adaptive routing: promoting model" |
| `indicagent-llm-writer` systemd unit running | LLM-04 | Requires systemd + deployment | `systemctl status indicagent-llm-writer` |
| Prometheus metrics on port 9117 | LLM-04 | Requires running service | `curl -s localhost:9117/metrics \| grep llm_writer_calls_consumed` |

---

## Validation Architecture

*(From RESEARCH.md — Nyquist compliance requires automated unit tests for pure functions + manual integration checks for each success criterion)*

### SC-1: LLM call → `llm_calls` row within 30s
**Automated:** Unit test that `_parse_llm_call_fields()` returns correct dict given a valid stream fields payload.
**Integration:** Query `llm_calls` count after services running 5 min.

### SC-2: Signal exit → outcome back-fill within 60s
**Automated:** Unit test that `_parse_outcome_fields()` returns correct dict, and UPDATE SQL is triggered.
**Integration:** Query `llm_calls WHERE outcome IS NOT NULL` after a signal closes.

### SC-3: `llm_model_scores` recomputed every 15 min
**Automated:** Unit test `_build_score_insert_params()` significance gate (p < 0.05 AND n >= 30).
**Integration:** Check `score_updated_at` column freshness.

### SC-4: Adaptive routing promotes significant model
**Automated:** Unit test `_maybe_reorder_providers()` moves best model to index 0 when is_significant=True.
**Integration:** Monitor service logs for promotion event.

### SC-5: Systemd unit running with metrics
**Manual only:** `systemctl status indicagent-llm-writer` + curl metrics endpoint.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
