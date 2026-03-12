---
phase: 29
slug: renaissance-signal-quality
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-12
---

# Phase 29 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | `pytest.ini` (standard discovery) |
| **Quick run command** | `.venv/bin/pytest tests/unit/intelligence/ tests/unit/monitoring/ -x -q` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -v` |
| **Estimated runtime** | ~45 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/unit/intelligence/ tests/unit/monitoring/ -x -q`
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~45 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 29-T0-01 | T0 | 1 | QUAL-01 | unit | `.venv/bin/pytest tests/unit/intelligence/test_cis_scorer.py -x` | ✅ exists — extend | ⬜ pending |
| 29-T1A-01 | T1-A | 1 | QUAL-02 | unit | `.venv/bin/pytest tests/unit/intelligence/test_aggregator.py -x` | ✅ exists — extend | ⬜ pending |
| 29-T1B-01 | T1-B | 1 | QUAL-03 | unit | `.venv/bin/pytest tests/unit/service_tests/test_lifecycle_freshness.py -x` | ❌ Wave 0 gap | ⬜ pending |
| 29-T1C-01 | T1-C | 1 | QUAL-04 | unit | `.venv/bin/pytest tests/unit/intelligence/test_aggregator.py -x` | ✅ exists — extend | ⬜ pending |
| 29-T1DE-01 | T1-D/E | 1 | QUAL-05 | unit | `.venv/bin/pytest tests/unit/intelligence/test_cis_scorer.py -x` | ✅ exists — extend | ⬜ pending |
| 29-T1DE-02 | T1-D/E | 1 | QUAL-06 | unit | `.venv/bin/pytest tests/unit/intelligence/test_cis_scorer.py -x` | ✅ exists — extend | ⬜ pending |
| 29-T2H-01 | T2-Hurst | 2 | QUAL-07 | unit | `.venv/bin/pytest tests/unit/intelligence/context/test_hurst_exponent.py -x` | ❌ Wave 0 gap | ⬜ pending |
| 29-T2S-01 | T2-Shannon | 2 | QUAL-08 | unit | `.venv/bin/pytest tests/unit/intelligence/context/test_shannon_entropy.py -x` | ❌ Wave 0 gap | ⬜ pending |
| 29-T3K-01 | T3-KS | 3 | QUAL-09 | unit | `.venv/bin/pytest tests/unit/monitoring/test_ks_drift_monitor.py -x` | ❌ Wave 0 gap | ⬜ pending |
| 29-T3C-01 | T3-CUSUM | 3 | QUAL-10 | unit | `.venv/bin/pytest tests/unit/monitoring/test_cusum_monitor.py -x` | ❌ Wave 0 gap | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/intelligence/context/test_hurst_exponent.py` — stubs for QUAL-07
- [ ] `tests/unit/intelligence/context/test_shannon_entropy.py` — stubs for QUAL-08
- [ ] `tests/unit/monitoring/__init__.py` — package init for new monitoring test module
- [ ] `tests/unit/monitoring/test_ks_drift_monitor.py` — stubs for QUAL-09
- [ ] `tests/unit/monitoring/test_cusum_monitor.py` — stubs for QUAL-10
- [ ] `tests/unit/service_tests/test_lifecycle_freshness.py` — stubs for QUAL-03

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `drift_monitor_service` systemd unit runs and logs healthy | QUAL-09/10 | Requires live infra (Redis + PostgreSQL + systemd) | `sudo systemctl status indicagent-drift-monitor`, check `journalctl -u indicagent-drift-monitor -n 50` |
| KS drift Redis key visible in live pipeline | QUAL-09 | Requires real Redis stream data | `.venv/bin/python -c "import redis; r=redis.Redis(); keys=r.keys('*drift:ks*'); print(keys)"` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 45s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
