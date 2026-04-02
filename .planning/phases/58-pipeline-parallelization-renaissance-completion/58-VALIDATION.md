---
phase: 58
slug: pipeline-parallelization-renaissance-completion
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-04-01
---

# Phase 58 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (asyncio_mode=auto, asyncio_default_fixture_loop_scope=function) |
| **Config file** | `pytest.ini` (project root) |
| **Quick run command** | `.venv/bin/pytest tests/unit/test_pipeline_determinism.py tests/unit/test_pipeline_exception_isolation.py -v -x` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -v` |
| **Estimated runtime** | ~30 seconds (unit only) |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/unit/test_pipeline_determinism.py tests/unit/test_pipeline_exception_isolation.py -v -x`
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green (2677+ passing; 2 pre-existing failures in `test_bar_writer_agent.py` are out of scope)
- **Max feedback latency:** ~30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 58-01-T1 | 01 | 1 | PIPE-01, PIPE-02, PIPE-03 | unit (import check) | `.venv/bin/python -c "from src.observability.metrics import PLUGIN_DURATION_MS, PLUGIN_ERRORS_TOTAL, THREAD_POOL_WORKERS; print('ok')"` | ✅ after task | ⬜ pending |
| 58-01-T2 | 01 | 1 | PIPE-01, PIPE-02, PIPE-03, PIPE-06 | unit | `.venv/bin/pytest tests/unit/test_pipeline_parallelization.py -v -x` | ✅ existing | ⬜ pending |
| 58-02-T1 | 02 | 2 | PIPE-04, PIPE-03 | unit | `.venv/bin/pytest tests/unit/test_pipeline_determinism.py -v -x --timeout=120` | ❌ W0 | ⬜ pending |
| 58-02-T2 | 02 | 2 | PIPE-05, PIPE-01, PIPE-02 | unit | `.venv/bin/pytest tests/unit/test_pipeline_exception_isolation.py -v -x --timeout=120` | ❌ W0 | ⬜ pending |
| 58-03-T1 | 03 | 2 | PIPE-03 | manual/script | `.venv/bin/python production/scripts/benchmark_thread_pool.py 2>/dev/null \| head -6` | ❌ W0 | ⬜ pending |
| 58-03-T2 | 03 | 2 | PIPE-06 | grep | `grep -c "METRICS_PORT" production/systemd/indicagent-intelligence-pipeline@.service` | ❌ W0 | ⬜ pending |
| 58-03-T3 | 03 | 2 | PIPE-06 | manual smoke | `systemctl status indicagent-intelligence-pipeline@1` | N/A (checkpoint) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_pipeline_determinism.py` — covers PIPE-04 (determinism) and PIPE-03 (configurable pool size subtest via `test_thread_pool_size_configurable`)
- [ ] `tests/unit/test_pipeline_exception_isolation.py` — covers PIPE-01 (`test_plugin_duration_recorded`), PIPE-02 (`test_error_counter_increments`), PIPE-05 (pipeline never crashes)
- [ ] `production/scripts/benchmark_thread_pool.py` — covers PIPE-03 empirical validation (manual benchmark, not automated test)
- [ ] `production/systemd/indicagent-intelligence-pipeline@.service` — template unit file (covers PIPE-06)

Wave 0 files are created by Plan 58-02 (tests) and Plan 58-03 (benchmark + template unit). They are not prerequisites for Wave 1 (Plan 58-01 can execute independently).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `indicagent-intelligence-pipeline@1.service` installed and active | PIPE-06 | Requires sudo + live systemd | `sudo systemctl is-active indicagent-intelligence-pipeline@1` → expected: `active` |
| `PLUGIN_DURATION_MS` visible in Grafana per plugin after RTH session | PIPE-01 | Requires live market data | Check Grafana → `intelligence_pipeline_plugin_duration_ms` metric, filter by `plugin_name` label |
| Thread pool benchmark results documented in README_PROFILING.md | PIPE-03 | Benchmark requires running system | Run `production/scripts/benchmark_thread_pool.py`, review curve, set `INTELLIGENCE_THREAD_POOL_WORKERS` in `.env` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
