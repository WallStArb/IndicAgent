---
phase: 39
slug: data-quality-db-health
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-19
---

# Phase 39 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | `pyproject.toml` — `[tool:pytest]` section |
| **Quick run command** | `.venv/bin/pytest tests/unit/scripts/ tests/unit/service_tests/ -v -x -q` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -v` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/unit/scripts/ tests/unit/service_tests/ -v -x -q`
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 39-01-01 | 01 | 0 | DATA-01 | unit | `.venv/bin/pytest tests/unit/scripts/test_repair_cis_nulls.py -v -x` | ✅ (needs exit-1 test) | ⬜ pending |
| 39-02-01 | 02 | 0 | DATA-02 | unit | `.venv/bin/pytest tests/unit/scripts/test_validate_alpha.py -v -x` | ✅ | ⬜ pending |
| 39-03-01 | 03 | 0 | DATA-03 | unit | `.venv/bin/pytest tests/unit/scripts/test_rebuild_ohlcv.py -v -x` | ❌ W0 | ⬜ pending |
| 39-03-02 | 03 | 0 | DATA-03 | unit | `.venv/bin/pytest tests/unit/scripts/test_rebuild_ohlcv.py::test_verify_v2_latency_gate_fails -v` | ❌ W0 | ⬜ pending |
| 39-04-01 | 04 | 0 | DATA-04 | manual | `docker exec timescaledb psql -U postgres -d indicagent -c "EXPLAIN ANALYZE UPDATE signal_ledger SET status='active' WHERE symbol='ES' AND timeframe='1m' AND status='pending' AND computed_at > NOW() - INTERVAL '1 hour'"` | manual-only | ⬜ pending |
| 39-05-01 | 05 | 0 | DATA-05 | unit | `.venv/bin/pytest tests/unit/service_tests/test_gap_fill_service.py::test_rth_window_generation -v -x` | ❌ W0 | ⬜ pending |
| 39-05-02 | 05 | 0 | DATA-05 | unit | `.venv/bin/pytest tests/unit/service_tests/test_gap_fill_service.py::test_detect_gaps -v` | ❌ W0 | ⬜ pending |
| 39-05-03 | 05 | 0 | DATA-05 | manual | Run gap-fill twice on same symbol; `SELECT COUNT(*) FROM market_data_ohlcv WHERE symbol='ES' AND timeframe='1m'` must return same count both times | manual-only | ⬜ pending |
| 39-06-01 | 06 | 0 | DATA-06 | unit | `.venv/bin/pytest tests/unit/intelligence/test_signal_status_enum.py -v -x` | ❌ W0 | ⬜ pending |
| 39-06-02 | 06 | 0 | DATA-06 | smoke | `grep -r '"pending"\|"active"\|"regime_suppressed"' services/ \| wc -l` must return `0` | smoke | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/scripts/test_rebuild_ohlcv.py` — stubs for DATA-03 verification gate logic (pure function tests, no DB): `test_verify_v2_chunk_count_gate_fails`, `test_verify_v2_latency_gate_fails`, `test_verify_v2_passes`
- [ ] `tests/unit/service_tests/test_gap_fill_service.py` — covers RTH window generation (DATA-05), gap detection logic: `test_rth_window_generation`, `test_detect_gaps`, `test_fetch_only_missing`
- [ ] `tests/unit/intelligence/test_signal_status_enum.py` — covers DATA-06 enum equality, str subclass behavior: `test_enum_str_equality`, `test_enum_values_unchanged`, `test_all_terminal_statuses`

*Existing infrastructure: pytest configured, `tests/unit/scripts/test_repair_cis_nulls.py` ✅, `tests/unit/scripts/test_validate_alpha.py` ✅*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `signal_ledger` lifecycle UPDATE uses index scan, latency < 5ms | DATA-04 | Requires live TimescaleDB with data; cannot mock hypertable chunk behavior | `docker exec timescaledb psql -U postgres -d indicagent -c "EXPLAIN ANALYZE UPDATE signal_ledger SET status='active' WHERE symbol='ES' AND timeframe='1m' AND status='pending' AND computed_at > NOW() - INTERVAL '1 hour'"` — confirm `Index Scan` in output, `Execution Time:` < 5ms |
| Gap-fill ON CONFLICT idempotency | DATA-05 | Requires live DB + IBKR connection | Run gap-fill service for one symbol, record row count, run again, assert count unchanged |
| `market_data_ohlcv` aggregate query < 500ms post-rebuild | DATA-03 | Requires live DB with data post-rename | `docker exec timescaledb psql -U postgres -d indicagent -c "\timing" -c "SELECT date_trunc('day', timestamp) AS day, symbol, COUNT(*) FROM market_data_ohlcv WHERE symbol='ES' AND timeframe='1m' GROUP BY 1,2 ORDER BY 1 DESC LIMIT 30;"` — confirm < 500ms |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
