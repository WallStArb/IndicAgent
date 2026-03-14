---
phase: 30
slug: redpanda-migration
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-13
---

# Phase 30 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.4.0 + pytest-asyncio |
| **Config file** | `pytest.ini` (project root) |
| **Quick run command** | `.venv/bin/pytest tests/unit/ -x -q` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -v` |
| **Estimated runtime** | ~60 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/unit/ -x -q`
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green (1659+ tests)
- **Max feedback latency:** ~60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 30-01-01 | 01 | 0 | KAFKA-01,02 | unit | `.venv/bin/pytest tests/unit/core/test_kafka_utils.py -x` | ❌ W0 | ⬜ pending |
| 30-01-02 | 01 | 0 | KAFKA-04 | unit | `.venv/bin/pytest tests/unit/core/test_kafka_init_topics.py -x` | ❌ W0 | ⬜ pending |
| 30-01-03 | 01 | 1 | KAFKA-03 | unit | `.venv/bin/pytest tests/unit/test_stream_keys.py -x` | ✅ extend | ⬜ pending |
| 30-01-04 | 01 | 1 | KAFKA-01,02 | unit | `.venv/bin/pytest tests/unit/core/test_kafka_utils.py -x` | ❌ W0 | ⬜ pending |
| 30-01-05 | 01 | 1 | KAFKA-04 | unit | `.venv/bin/pytest tests/unit/core/test_kafka_init_topics.py -x` | ❌ W0 | ⬜ pending |
| 30-02-01 | 02 | 1 | KAFKA-05 | unit | `.venv/bin/pytest tests/unit/service_tests/test_indicator_service.py -x` | ✅ extend | ⬜ pending |
| 30-02-02 | 02 | 1 | KAFKA-08 | unit | `.venv/bin/pytest tests/unit/ -x -q` | ✅ | ⬜ pending |
| 30-03-01 | 03 | 1 | KAFKA-06 | unit | `.venv/bin/pytest tests/unit/service_tests/test_signal_generator_service.py -x` | ✅ extend | ⬜ pending |
| 30-03-02 | 03 | 1 | KAFKA-08 | unit | `.venv/bin/pytest tests/unit/ -x -q` | ✅ | ⬜ pending |
| 30-04-01 | 04 | 1 | KAFKA-07 | unit | `.venv/bin/pytest tests/unit/test_sse_stream_builder.py -x` | ✅ extend | ⬜ pending |
| 30-04-02 | 04 | 1 | KAFKA-08 | unit | `.venv/bin/pytest tests/unit/ -x -q` | ✅ | ⬜ pending |
| 30-05-01 | 05 | 1 | KAFKA-08 | unit | `.venv/bin/pytest tests/unit/ -v` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/core/test_kafka_utils.py` — stubs for KAFKA-01 (producer wrapper) and KAFKA-02 (consumer wrapper)
- [ ] `tests/unit/core/test_kafka_init_topics.py` — stubs for KAFKA-04 (topic creation script)
- [ ] `production/scripts/kafka_init_topics.py` — topic creation script (tested by KAFKA-04)

*Wave 0 must be complete before Plan 1 execution begins.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| E2E pipeline flow post-migration | KAFKA-E2E | Requires live Redpanda + TWS | `historical_backfill.py --replay-only --days 1`, verify intelligence_features + signal_ledger populated |
| Dashboard SSE receives events | KAFKA-SSE | Requires browser + live pipeline | Open dashboard, verify signal cards update after replay |
| DragonflyDB fully removed | KAFKA-CLEAN | Requires docker compose inspection | `cd production && docker compose ps` — no DragonflyDB container running |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
